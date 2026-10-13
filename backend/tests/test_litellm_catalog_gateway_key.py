"""Unit tests for the model catalog's gateway credential boundary."""

import logging
import sys
import types
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException


def _install_import_stubs_for_catalog_test():
    """Keep this focused unit test independent of optional app integrations."""
    try:
        import stripe  # noqa: F401
    except ModuleNotFoundError:
        stripe = types.ModuleType("stripe")
        stripe.api_key = None
        sys.modules["stripe"] = stripe

    try:
        import asyncpg  # noqa: F401
    except ModuleNotFoundError:
        asyncpg = types.ModuleType("asyncpg")
        for name in ("Pool", "Record", "Connection", "PoolAcquireContext"):
            setattr(asyncpg, name, object)
        asyncpg.create_pool = None
        asyncpg.connect = None
        sys.modules["asyncpg"] = asyncpg

    if "usage_metering" not in sys.modules:
        usage_metering = types.ModuleType("usage_metering")
        usage_metering.usage_meter = object()
        sys.modules["usage_metering"] = usage_metering


_install_import_stubs_for_catalog_test()

try:  # The handler imports the full backend application dependency graph.
    import litellm_api
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"litellm_api is not importable here: {exc}", allow_module_level=True)


class FakeConnection:
    async def fetchrow(self, _query, *_args):
        return None


class FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield FakeConnection()


class FakeCreditSystem:
    db_pool = FakePool()

    async def get_user_tier(self, _user_id):
        return "unit"


class FakeByokManager:
    async def list_user_providers(self, _user_id):
        return []


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class RecordingAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        del args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if url.endswith("/v1/models"):
            return FakeResponse({"data": [{"id": "gpt-4o", "created": 1}]})
        return FakeResponse({"data": []})


@pytest.fixture(autouse=True)
def isolate_catalog_dependencies(monkeypatch):
    RecordingAsyncClient.calls = []
    monkeypatch.delenv("LITELLM_CATALOG_KEY", raising=False)
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(litellm_api, "get_credential", lambda _name: "")
    monkeypatch.setattr(litellm_api.httpx, "AsyncClient", RecordingAsyncClient)

    federation = types.ModuleType("federation_llm_bridge")

    async def no_federated_models():
        return {}

    federation.federated_models = no_federated_models
    monkeypatch.setitem(sys.modules, "federation_llm_bridge", federation)


@pytest.mark.asyncio
async def test_configured_catalog_credential_is_forwarded_as_bearer(monkeypatch):
    monkeypatch.setattr(
        litellm_api,
        "get_credential",
        lambda name: "unit-catalog-credential" if name == "LITELLM_MASTER_KEY" else "",
    )

    result = await litellm_api.list_models_categorized(
        user_id="unit-user",
        byok_manager=FakeByokManager(),
        credit_system=FakeCreditSystem(),
    )

    assert RecordingAsyncClient.calls[0]["headers"] == {
        "Authorization": "Bearer unit-catalog-credential"
    }
    assert result["summary"]["total_models"] == 1


@pytest.mark.asyncio
async def test_catalog_environment_fallback_is_forwarded_as_bearer(monkeypatch):
    monkeypatch.setenv("LITELLM_CATALOG_KEY", "unit-catalog-environment")

    await litellm_api.list_models_categorized(
        user_id="unit-user",
        byok_manager=FakeByokManager(),
        credit_system=FakeCreditSystem(),
    )

    assert RecordingAsyncClient.calls[0]["headers"] == {
        "Authorization": "Bearer unit-catalog-environment"
    }


@pytest.mark.asyncio
async def test_missing_catalog_credential_returns_503_without_outbound_call(caplog, monkeypatch):
    class UnexpectedAsyncClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("HTTP client must not be created without a gateway credential")

    monkeypatch.setattr(litellm_api.httpx, "AsyncClient", UnexpectedAsyncClient)
    caplog.set_level(logging.WARNING, logger=litellm_api.logger.name)

    with pytest.raises(HTTPException) as exc_info:
        await litellm_api.list_models_categorized(
            user_id="unit-user",
            byok_manager=FakeByokManager(),
            credit_system=FakeCreditSystem(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "gateway key not configured"
    warnings = [
        record
        for record in caplog.records
        if record.getMessage() == "gateway_key_not_configured"
    ]
    assert len(warnings) == 1
    assert warnings[0].endpoint == "/api/v1/llm/models/categorized"
    assert RecordingAsyncClient.calls == []
