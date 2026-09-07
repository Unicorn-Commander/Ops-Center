"""Billing identity regressions; no credentials or running services required."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2]


def load_org_helper(module):
    # Load the actual route helpers without unrelated module-level service setup.
    tree = ast.parse((BACKEND / f"{module}.py").read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
             and n.name in {"get_current_user", "get_user_org_id"}]
    namespace = {"Request": object, "HTTPException": HTTPException,
                 "logger": logging.getLogger(__name__)}
    try:
        from billing_org_identity import resolve_billing_org
        namespace["resolve_billing_org"] = resolve_billing_org
    except ImportError:
        pass
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BACKEND / f"{module}.py"), "exec"), namespace)
    return namespace["get_user_org_id"]


def request_for(user):
    return SimpleNamespace(cookies={"session_token": "test-session"},
                           app=SimpleNamespace(state=SimpleNamespace(
                               sessions={"test-session": {"user": user}})))


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["subscription_api", "usage_api"])
async def test_missing_org_never_fabricates_from_email(module):
    with pytest.raises(HTTPException) as exc:
        await load_org_helper(module)(request_for({"email": "member@example.test"}))
    assert exc.value.status_code == 409

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["subscription_api", "usage_api"])
@pytest.mark.parametrize("org", [ORG_A, f"org_{ORG_A}"])
async def test_routes_use_canonical_lago_namespace(module, org):
    assert await load_org_helper(module)(request_for({"org_id": org})) == f"org_{ORG_A}"


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["subscription_api", "usage_api"])
async def test_routes_require_authenticated_session(module):
    request = request_for({"org_id": ORG_A})
    request.cookies = {}
    with pytest.raises(HTTPException) as exc:
        await load_org_helper(module)(request)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["org_member_unknown", "cus_example", "", None, "00000000-0000-0000-0000-000000000000"])
async def test_invalid_identity_rejected(value):
    from billing_org_identity import lago_org_id
    with pytest.raises(HTTPException):
        lago_org_id(value)


@pytest.mark.asyncio
async def test_session_and_keycloak_attributes(monkeypatch):
    import billing_org_identity as identity
    lookup = AsyncMock()
    monkeypatch.setattr(identity, "_membership_orgs", lookup)
    assert await identity.resolve_billing_org({"attributes": {"org_id": [ORG_A]}}) == f"org_{ORG_A}"
    assert await identity.resolve_billing_org({}, {"org_id": ORG_B}) == f"org_{ORG_B}"
    lookup.assert_not_called()
    with pytest.raises(HTTPException) as exc:
        await identity.resolve_billing_org({"org_id": ORG_A}, {"org_id": ORG_B})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_fallback_is_subject_scoped_not_email_or_other_local_id(monkeypatch):
    import billing_org_identity as identity
    lookup = AsyncMock(side_effect=[[{"org_id": ORG_A}], [{"org_id": ORG_B}]])
    monkeypatch.setattr(identity, "_membership_orgs", lookup)
    for subject, expected in [("subject-a", ORG_A), ("subject-b", ORG_B)]:
        assert await identity.resolve_billing_org({"sub": subject, "id": "unrelated", "email": "same@example.test"}) == f"org_{expected}"
    assert [call.args[0] for call in lookup.await_args_list] == ["subject-a", "subject-b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [{"org_id": ORG_A}, {"org_id": ORG_B}]])
async def test_absent_or_ambiguous_membership_fails_closed(monkeypatch, rows):
    import billing_org_identity as identity
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=rows))
    with pytest.raises(HTTPException) as exc:
        await identity.resolve_billing_org({"sub": "subject-a"})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_database_failure_is_retryable(monkeypatch):
    import billing_org_identity as identity
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(HTTPException) as exc:
        await identity.resolve_billing_org({"sub": "subject-a"})
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_membership_query_uses_subject_and_singular_user_mapping(monkeypatch):
    import billing_org_identity as identity
    conn = SimpleNamespace(fetch=AsyncMock(return_value=[{"org_id": ORG_A}]), close=AsyncMock())
    monkeypatch.setattr(identity.asyncpg, "connect", AsyncMock(return_value=conn))
    assert await identity.resolve_billing_org({"sub": "subject-a"}) == f"org_{ORG_A}"
    query, subject = conn.fetch.await_args.args
    assert subject == "subject-a"
    assert 'FROM "user" WHERE oauth_sub = $1' in query
    assert 'organization_members' in query
    assert 'LIMIT 1' not in query
    assert 'email' not in query
    conn.close.assert_awaited_once()


@pytest.fixture
def stripe_module(monkeypatch):
    # Import the real integration while preventing import-time credential and
    # Keycloak access; Stripe/Lago calls themselves are mocked in each test.
    import importlib.util
    import sys
    from types import ModuleType
    credential = ModuleType("get_credential")
    credential.get_credential = lambda name: None
    keycloak = ModuleType("keycloak_integration")
    keycloak.update_user_attributes = AsyncMock()
    keycloak.get_user_by_email = AsyncMock()
    monkeypatch.setitem(sys.modules, "get_credential", credential)
    monkeypatch.setitem(sys.modules, "keycloak_integration", keycloak)
    spec = importlib.util.spec_from_file_location("billing_test_stripe", BACKEND / "stripe_integration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_checkout_pins_org_on_session_and_subscription(stripe_module, monkeypatch):
    from unittest.mock import Mock
    create = Mock(return_value=SimpleNamespace(id="cs_example", url="https://checkout.example.test"))
    monkeypatch.setattr(stripe_module.stripe.checkout.Session, "create", create)
    await stripe_module.stripe_integration.create_checkout_session("cus_example", "price_example", "member@example.test", "professional", org_id=ORG_A)
    payload = create.call_args.kwargs
    assert payload["metadata"]["org_id"] == f"org_{ORG_A}"
    assert payload["subscription_data"]["metadata"]["org_id"] == f"org_{ORG_A}"
    create.reset_mock()
    with pytest.raises(HTTPException):
        await stripe_module.stripe_integration.create_checkout_session("cus_example", "price_example", "member@example.test", "professional")
    create.assert_not_called()


@pytest.mark.asyncio
async def test_stripe_customer_lookup_is_org_scoped(stripe_module, monkeypatch):
    from unittest.mock import Mock
    search = Mock(return_value=SimpleNamespace(data=[{"id": "cus_example"}]))
    monkeypatch.setattr(stripe_module.stripe.Customer, "search", search)
    for org in [ORG_A, ORG_B]:
        await stripe_module.stripe_integration.get_customer_for_org(org)
        assert search.call_args.kwargs["query"] == f"metadata['org_id']:'org_{org}'"
    search.return_value.data = [{"id": "cus_a"}, {"id": "cus_b"}]
    with pytest.raises(ValueError):
        await stripe_module.stripe_integration.get_customer_for_org(ORG_A)


@pytest.mark.asyncio
async def test_lago_retry_and_tenants_keep_same_canonical_key(stripe_module, monkeypatch):
    from unittest.mock import MagicMock
    client = AsyncMock()
    client.post.side_effect = [SimpleNamespace(status_code=503, text="unavailable"),
                               SimpleNamespace(status_code=201), SimpleNamespace(status_code=200)]
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(stripe_module.httpx, "AsyncClient", lambda: context)
    results = []
    for org in [ORG_A, ORG_A, ORG_B]:
        results.append(await stripe_module.stripe_integration.sync_to_lago("same@example.test", "professional", "cus_example", org_id=org))
    assert results == [False, True, True]
    customers = [call.kwargs["json"]["customer"] for call in client.post.await_args_list]
    assert [c["external_id"] for c in customers] == [f"org_{ORG_A}", f"org_{ORG_A}", f"org_{ORG_B}"]
    assert all(c["billing_configuration"]["provider_customer_id"] == "cus_example" for c in customers)
    before = client.post.await_count
    with pytest.raises(HTTPException):
        await stripe_module.stripe_integration.sync_to_lago("same@example.test", "professional", "cus_example")
    assert client.post.await_count == before


@pytest.mark.asyncio
async def test_webhook_threads_org_and_does_not_ack_failed_sync(stripe_module, monkeypatch):
    integration = stripe_module.stripe_integration
    keycloak = AsyncMock(return_value=True)
    lago = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(integration, "sync_to_keycloak", keycloak)
    monkeypatch.setattr(integration, "sync_to_lago", lago)
    session = {"customer": "cus_example", "subscription": "sub_example", "metadata": {
        "customer_email": "member@example.test", "org_id": ORG_A, "tier_name": "professional"}}
    assert (await integration._handle_checkout_completed(session))["status"] == "error"
    assert (await integration._handle_checkout_completed(session))["status"] == "success"
    assert [c.kwargs["org_id"] for c in lago.await_args_list] == [f"org_{ORG_A}"] * 2
    keycloak.reset_mock()
    lago.reset_mock()
    session["metadata"].pop("org_id")
    with pytest.raises(HTTPException):
        await integration._handle_checkout_completed(session)
    keycloak.assert_not_called()
    lago.assert_not_called()


@pytest.mark.asyncio
async def test_customer_creation_retry_is_idempotent_per_org(stripe_module, monkeypatch):
    from unittest.mock import Mock
    create = Mock(return_value=SimpleNamespace(id="cus_example"))
    monkeypatch.setattr(stripe_module.stripe.Customer, "create", create)
    for org in [ORG_A, ORG_A, ORG_B]:
        await stripe_module.stripe_integration.create_customer("member@example.test", metadata={"org_id": org})
    keys = [call.kwargs["idempotency_key"] for call in create.call_args_list]
    assert keys[0] == keys[1]
    assert keys[1] != keys[2]


@pytest.mark.asyncio
async def test_billing_checkout_route_threads_authenticated_org():
    from unittest.mock import Mock
    tree = ast.parse((BACKEND / "stripe_api.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_checkout_session")
    node.decorator_list = []
    integration = SimpleNamespace(get_customer_for_org=AsyncMock(return_value={"id": "cus_example"}),
                                  create_checkout_session=AsyncMock(return_value="https://checkout.example.test"))
    conn = SimpleNamespace(fetchrow=AsyncMock(return_value={"price_monthly": 1, "stripe_price_monthly": "price_example"}), close=AsyncMock())
    import os
    namespace = {"CheckoutSessionRequest": object, "Depends": lambda x: None,
                 "get_current_user_email": None, "get_current_billing_org": None,
                 "HTTPException": HTTPException, "asyncpg": SimpleNamespace(connect=AsyncMock(return_value=conn)),
                 "os": os, "stripe_integration": integration, "logger": logging.getLogger(__name__),
                 "CheckoutSessionResponse": Mock()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "stripe_api.py", "exec"), namespace)
    await namespace["create_checkout_session"](SimpleNamespace(billing_cycle="monthly", tier_id="professional"), "member@example.test", f"org_{ORG_A}")
    integration.get_customer_for_org.assert_awaited_once_with(f"org_{ORG_A}")
    assert integration.create_checkout_session.await_args.kwargs["org_id"] == f"org_{ORG_A}"


@pytest.mark.asyncio
async def test_upgrade_route_threads_authenticated_org(monkeypatch):
    import sys
    tree = ast.parse((BACKEND / "subscription_api.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "initiate_upgrade")
    node.decorator_list = []
    integration = SimpleNamespace(get_customer_for_org=AsyncMock(return_value={"id": "cus_example"}),
                                  create_checkout_session=AsyncMock(return_value="https://checkout.example.test"))
    monkeypatch.setitem(sys.modules, "stripe_integration", SimpleNamespace(stripe_integration=integration))
    plan = SimpleNamespace(stripe_price_id="price_example", price_monthly=1)
    namespace = {"Request": object, "UpgradeRequest": object, "HTTPException": HTTPException,
                 "get_current_user": AsyncMock(return_value={"email": "member@example.test"}),
                 "get_user_org_id": AsyncMock(return_value=f"org_{ORG_A}"),
                 "get_subscription": AsyncMock(return_value={"plan_code": "starter_monthly"}),
                 "getTierLevel": lambda tier: {"starter": 1, "professional": 2}[tier],
                 "subscription_manager": SimpleNamespace(get_plan=lambda tier: plan),
                 "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "subscription_api.py", "exec"), namespace)
    await namespace["initiate_upgrade"](request_for({"org_id": ORG_A}), SimpleNamespace(target_tier="professional"))
    integration.get_customer_for_org.assert_awaited_once_with(f"org_{ORG_A}")
    assert integration.create_checkout_session.await_args.kwargs["org_id"] == f"org_{ORG_A}"


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["subscription_api", "usage_api"])
async def test_http_boundary_rejects_missing_org_and_ignores_query_override(module):
    from fastapi import FastAPI, Request
    import httpx
    app = FastAPI()
    app.state.sessions = {"test-session": {"user": {"email": "member@example.test"}}}
    helper = load_org_helper(module)

    @app.get("/billing-identity")
    async def identity(request: Request):
        return {"org_id": await helper(request)}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies={"session_token": "test-session"}) as client:
        response = await client.get(f"/billing-identity?org_id={ORG_B}")
        assert response.status_code == 409
        app.state.sessions["test-session"]["user"]["org_id"] = ORG_A
        response = await client.get(f"/billing-identity?org_id={ORG_B}")
        assert response.status_code == 200
        assert response.json() == {"org_id": f"org_{ORG_A}"}


@pytest.mark.asyncio
async def test_lago_payload_over_loopback_http(stripe_module, monkeypatch):
    """Prove the serialized payload on a test-owned socket, with no real Lago."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import json
    from threading import Thread

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(stripe_module, "LAGO_API_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        for _ in range(2):
            assert await stripe_module.stripe_integration.sync_to_lago(
                "member@example.test", "professional", "cus_example", org_id=ORG_A
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(received) == 2
    for path, payload in received:
        assert path == "/api/v1/customers"
        customer = payload["customer"]
        assert customer["external_id"] == f"org_{ORG_A}"
        assert customer["billing_configuration"]["provider_customer_id"] == "cus_example"
