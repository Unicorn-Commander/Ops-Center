"""Stripe automatic tax follows platform settings, then the environment."""
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def _reload(monkeypatch):
    import stripe_integration
    return importlib.reload(stripe_integration)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row_value", "env_value", "expected"),
    [("1", "0", True), ("0", "1", False), (None, "1", True), (None, None, False)],
)
async def test_automatic_tax_platform_row_precedes_environment(
    monkeypatch, row_value, env_value, expected
):
    if env_value is None:
        monkeypatch.delenv("STRIPE_AUTOMATIC_TAX", raising=False)
    else:
        monkeypatch.setenv("STRIPE_AUTOMATIC_TAX", env_value)
    mod = _reload(monkeypatch)

    async def fake_get_credential_async(key):
        assert key == "STRIPE_AUTOMATIC_TAX"
        if row_value is not None:
            return row_value
        return env_value or ""

    monkeypatch.setattr(mod, "get_credential_async", fake_get_credential_async)
    assert await mod.automatic_tax_enabled() is expected


@pytest.mark.asyncio
async def test_tax_kwargs_keep_checkout_shape_when_enabled(monkeypatch):
    mod = _reload(monkeypatch)
    monkeypatch.setattr(mod, "automatic_tax_enabled", AsyncMock(return_value=True))
    kw = await mod._tax_kwargs()
    assert kw["automatic_tax"] == {"enabled": True}
    assert kw["customer_update"] == {"address": "auto", "name": "auto"}
    assert kw["billing_address_collection"] == "required"
    assert kw["tax_id_collection"] == {"enabled": True}


@pytest.mark.asyncio
async def test_checkout_reads_tax_toggle_at_call_time(monkeypatch):
    mod = _reload(monkeypatch)
    monkeypatch.setattr(mod, "automatic_tax_enabled", AsyncMock(return_value=True))
    create = Mock(return_value=SimpleNamespace(id="cs_fixture", url="https://checkout.example.test"))
    monkeypatch.setattr(mod.stripe.checkout.Session, "create", create)

    await mod.stripe_integration.create_checkout_session(
        "cus_fixture",
        "price_fixture",
        "fictional@example.com",
        "byok",
        org_id="00000000-0000-4000-8000-000000000101",
    )

    assert create.call_args.kwargs["automatic_tax"] == {"enabled": True}
    assert mod.automatic_tax_enabled.await_count == 1
