"""The 402 door check reserves prompt + completion, and settlement survives a client disconnect.

These drive the real ``litellm_api.chat_completions`` handler with the real
``CreditSystem.calculate_cost`` pricing, faking only the edges: the database
rows, the org-credit integration, BYOK keys and the upstream HTTP provider.

1. The wider door estimate must NOT refuse zero-cost, credit-exempt or BYOK
   requests, even with a huge max_tokens and an empty balance.
2. It must refuse (402, provider never called) a paid request whose prompt +
   completion estimate the payer cannot cover.
3. A streaming charge must still be written when the client disconnects after
   the provider finished (Starlette cancels / closes the generator).
"""

import asyncio
import json
import sys
import types
from contextlib import asynccontextmanager

import pytest

try:  # the handler module pulls in the whole app; skip where its deps are absent
    import litellm_api
    import billing_settlement
    from litellm_credit_system import CreditSystem
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"litellm_api is not importable here: {exc}", allow_module_level=True)

from fastapi import HTTPException


CLOUD_PROVIDER = {
    "id": 1, "name": "OpenRouter", "type": "openrouter", "api_key_encrypted": "unit-test-placeholder",
    "api_base_url": "https://openrouter.ai/api/v1", "config": {},
}


class FakeConn:
    async def fetchrow(self, query, *args):
        if "JOIN llm_providers" in query or "FROM llm_providers" in query:
            return CLOUD_PROVIDER
        return None  # no llm_models rate row: pricing falls through to MODEL_RATES_USD_PER_MTOK

    async def fetchval(self, query, *args):
        return None

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        return "OK"


class FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield FakeConn()


class FakeRedis:
    async def get(self, *a):
        return None

    async def setex(self, *a):
        return True

    async def delete(self, *a):
        return 1


class Credits(CreditSystem):
    """Real calculate_cost; balances and debits faked."""

    def __init__(self, tier="professional", balance=0.0):
        super().__init__(FakePool(), FakeRedis())
        self.tier, self.balance, self.debits = tier, balance, []

    async def get_user_tier(self, user_id):
        return self.tier

    async def get_user_credits(self, user_id):
        return self.balance

    async def check_monthly_cap(self, user_id, amount):
        return True

    async def debit_credits(self, user_id, amount, metadata):
        self.debits.append({"user_id": user_id, "amount": amount, "metadata": metadata})
        return self.balance - amount, "txn-1"


class Org:
    """Mirrors has_sufficient_credits(): remaining millicredits >= int(needed * 1000)."""

    def __init__(self, org_id=None, remaining_millicredits=0):
        self.org_id, self.remaining, self.deductions = org_id, remaining_millicredits, []

    async def has_sufficient_org_credits(self, user_id, credits_needed, request_state=None):
        if not self.org_id:
            return False, None, "User does not belong to any organization"
        return self.remaining >= int(credits_needed * 1000), self.org_id, "checked"

    async def deduct_org_credits(self, **kwargs):
        self.deductions.append(kwargs)
        return True, self.org_id, self.remaining

    async def get_user_org_credits(self, user_id, request_state=None):
        return self.org_id, self.remaining, self.remaining

    async def get_user_org_id(self, user_id, request_state=None):
        return self.org_id


class Byok:
    def __init__(self, keys=None):
        self.keys = keys or {}

    async def get_all_user_keys(self, user_id):
        return self.keys


class Upstream:
    """Stands in for httpx.AsyncClient; records whether the provider was called."""

    calls = []
    stream_lines = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        Upstream.calls.append(json)
        body = {
            "id": "unit", "model": json.get("model") or "unit-model",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        return types.SimpleNamespace(
            status_code=200, json=lambda: body, text="{}", headers={}, content=b"{}",
        )

    @asynccontextmanager
    async def stream(self, method, url, json=None, headers=None):
        Upstream.calls.append(json)

        async def aiter_lines():
            for line in Upstream.stream_lines:
                yield line

        yield types.SimpleNamespace(status_code=200, aiter_lines=aiter_lines, aread=None)


class UsageMeter:
    async def track_usage(self, **kwargs):
        return None


@pytest.fixture(autouse=True)
def _edges(monkeypatch):
    Upstream.calls = []
    monkeypatch.setattr(litellm_api.httpx, "AsyncClient", Upstream)
    monkeypatch.setattr(litellm_api, "usage_meter", UsageMeter())
    federation = types.ModuleType("federation_llm_bridge")

    async def no_federated_node(model):
        return None

    federation.federated_node_for_model = no_federated_node
    monkeypatch.setitem(sys.modules, "federation_llm_bridge", federation)
    monkeypatch.setattr(litellm_api, "BILLING_ENABLED", True)
    monkeypatch.setattr(litellm_api, "CREDIT_EXEMPT_TIERS", {"internal"})
    monkeypatch.setenv("BILLING_SETTLE_FAILURE_MODE", "queue")
    monkeypatch.delenv("BILLING_DEFAULT_COMPLETION_TOKENS", raising=False)


def _request(model, max_tokens=None, stream=False):
    return litellm_api.ChatCompletionRequest(
        model=model, max_tokens=max_tokens, stream=stream,
        messages=[litellm_api.ChatMessage(role="user", content="hello there")],
    )


async def _call(monkeypatch, request, credits, org=None, byok=None):
    org = org or Org()
    monkeypatch.setattr(litellm_api, "get_org_credit_integration", lambda: org)
    return await litellm_api.chat_completions(
        request=request, user_id="unit-user", credit_system=credits,
        byok_manager=byok or Byok(), x_power_level=None,
    )


# --- 1. never refused by the wider estimate -------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_cost_model_is_not_refused_with_empty_balance_and_huge_max_tokens(monkeypatch):
    response = await _call(monkeypatch, _request("uc/chat-default", max_tokens=100_000), Credits(balance=0.0))
    assert len(Upstream.calls) == 1
    assert response["_metadata"]["cost_incurred"] == 0.0


@pytest.mark.asyncio
async def test_zero_cost_model_is_not_refused_for_an_org_with_zero_allocation_left(monkeypatch):
    org = Org(org_id="org-1", remaining_millicredits=0)
    await _call(monkeypatch, _request("uc/chat-default", max_tokens=100_000), Credits(), org=org)
    assert len(Upstream.calls) == 1
    assert org.deductions == []


@pytest.mark.asyncio
async def test_credit_exempt_tier_is_not_refused_on_a_paid_model(monkeypatch):
    credits = Credits(tier="internal", balance=0.0)
    response = await _call(monkeypatch, _request("openai/gpt-4o", max_tokens=100_000), credits)
    assert len(Upstream.calls) == 1
    assert response["_metadata"]["cost_incurred"] == 0.0 and credits.debits == []


@pytest.mark.asyncio
async def test_byok_is_not_refused_on_a_paid_model(monkeypatch):
    credits = Credits(balance=0.0)
    byok = Byok({"openrouter": "unit-test-byok-placeholder"})
    response = await _call(monkeypatch, _request("openai/gpt-4o", max_tokens=100_000), credits, byok=byok)
    assert len(Upstream.calls) == 1
    assert response["_metadata"]["using_byok"] is True and credits.debits == []


# --- 2. refused at the door --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paid_request_the_payer_cannot_cover_is_refused_before_the_provider_is_called(monkeypatch):
    # gpt-4o output rate is $10/Mtok: 100k reserved tokens ~ 1.0 credit > 0.5 balance
    with pytest.raises(HTTPException) as refused:
        await _call(monkeypatch, _request("openai/gpt-4o", max_tokens=100_000), Credits(balance=0.5))
    assert refused.value.status_code == 402
    assert Upstream.calls == []


@pytest.mark.asyncio
async def test_the_default_completion_allowance_is_reserved_when_max_tokens_is_absent(monkeypatch):
    # The prompt alone (3 tokens, ~$0.00003) fits a 0.001 balance; prompt + 1024 (~$0.0103) does not.
    with pytest.raises(HTTPException) as refused:
        await _call(monkeypatch, _request("openai/gpt-4o"), Credits(balance=0.001))
    assert refused.value.status_code == 402
    assert Upstream.calls == []
    org = Org(org_id="org-1", remaining_millicredits=5)  # 0.005 credits < 0.0103
    with pytest.raises(HTTPException) as refused:
        await _call(monkeypatch, _request("openai/gpt-4o"), Credits(), org=org)
    assert refused.value.status_code == 402


@pytest.mark.asyncio
async def test_billing_fallback_keeps_the_prompt_only_estimate(monkeypatch):
    """Widening the door must not change what a no-usage stream is billed."""
    Upstream.stream_lines = [
        'data: ' + json.dumps({"model": "openai/gpt-4o", "choices": [{"delta": {"content": "hi"}}]}),
        "data: [DONE]",
    ]
    org = Org(org_id="org-1", remaining_millicredits=10_000_000)
    response = await _call(monkeypatch, _request("openai/gpt-4o", max_tokens=4000, stream=True), Credits(), org=org)
    chunks = [chunk async for chunk in response.body_iterator]
    await billing_settlement.wait_for_background_settlements(timeout=2)
    assert chunks[-1] == "data: [DONE]\n\n"
    assert len(org.deductions) == 1
    assert org.deductions[0]["tokens_used"] == 3  # "hello there" -> 2 words x 1.5, not 3 + 4000


# --- 3. a client disconnect cannot drop a finished stream's charge ----------------------------------

def _usage_stream():
    return [
        'data: ' + json.dumps({"model": "openai/gpt-4o", "choices": [{"delta": {"content": "hi"}}]}),
        'data: ' + json.dumps({"model": "openai/gpt-4o", "choices": [],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}),
        "data: [DONE]",
    ]


@pytest.mark.asyncio
async def test_generator_closed_right_after_done_still_settles(monkeypatch):
    Upstream.stream_lines = _usage_stream()
    org = Org(org_id="org-1", remaining_millicredits=10_000_000)
    response = await _call(monkeypatch, _request("openai/gpt-4o", stream=True), Credits(), org=org)
    generator = response.body_iterator
    while (await generator.__anext__()) != "data: [DONE]\n\n":
        pass
    await generator.aclose()  # what a disconnect does to a suspended generator
    await billing_settlement.wait_for_background_settlements(timeout=2)
    assert len(org.deductions) == 1
    deduction = org.deductions[0]
    assert deduction["tokens_used"] == 30 and deduction["credits_used"] > 0
    assert deduction["request_id"]


@pytest.mark.asyncio
async def test_cancelling_the_stream_mid_settlement_does_not_lose_or_repeat_the_charge(monkeypatch):
    Upstream.stream_lines = _usage_stream()
    release = asyncio.Event()

    class SlowOrg(Org):
        async def deduct_org_credits(self, **kwargs):
            await release.wait()
            return await super().deduct_org_credits(**kwargs)

    org = SlowOrg(org_id="org-1", remaining_millicredits=10_000_000)
    response = await _call(monkeypatch, _request("openai/gpt-4o", stream=True), Credits(), org=org)
    received = []

    async def client():
        async for chunk in response.body_iterator:
            received.append(chunk)

    consumer = asyncio.ensure_future(client())
    for _ in range(100):
        await asyncio.sleep(0.01)
        if "data: [DONE]\n\n" in received:
            break
    await asyncio.sleep(0.05)  # the generator is now inside the settlement
    consumer.cancel()  # Starlette cancels the response task on http.disconnect
    with pytest.raises(asyncio.CancelledError):
        await consumer
    assert org.deductions == []
    release.set()
    await billing_settlement.wait_for_background_settlements(timeout=2)
    assert len(org.deductions) == 1


@pytest.mark.asyncio
async def test_a_stream_the_client_abandons_mid_way_is_not_billed_as_complete(monkeypatch):
    """Pre-existing behaviour kept: no [DONE] from the provider -> no completed-stream settlement."""
    Upstream.stream_lines = _usage_stream()
    org = Org(org_id="org-1", remaining_millicredits=10_000_000)
    response = await _call(monkeypatch, _request("openai/gpt-4o", stream=True), Credits(), org=org)
    generator = response.body_iterator
    await generator.__anext__()  # ": ping"
    await generator.__anext__()  # first content chunk
    await generator.aclose()
    await billing_settlement.wait_for_background_settlements(timeout=2)
    assert org.deductions == []


@pytest.mark.asyncio
async def test_byok_streaming_delivers_the_stream_and_bills_nothing(monkeypatch):
    """A local `import json` inside chat_completions left `json` unbound on the BYOK path,
    so stream_generator raised NameError right after ': ping' (and again in its handler)."""
    Upstream.stream_lines = _usage_stream()
    credits = Credits(balance=0.0)
    org = Org(org_id="org-1", remaining_millicredits=0)
    byok = Byok({"openrouter": "unit-test-byok-placeholder"})
    response = await _call(monkeypatch, _request("openai/gpt-4o", max_tokens=100_000, stream=True), credits, org=org, byok=byok)
    chunks = [chunk async for chunk in response.body_iterator]
    await billing_settlement.wait_for_background_settlements(timeout=2)
    assert chunks[-1] == "data: [DONE]\n\n"
    assert not any('"error"' in chunk for chunk in chunks)
    assert credits.debits == [] and org.deductions == []
