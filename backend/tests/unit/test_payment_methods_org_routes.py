"""Actual payment-method router regressions; all providers are in-memory doubles."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import sys

import httpx
import pytest
from fastapi import FastAPI, HTTPException

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def payment_routes(monkeypatch):
    import billing_org_identity as identity
    # Provider tests authenticate one subject with persisted membership in both
    # fixture tenants. Selected context still chooses exactly one tenant.
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=[
        {"org_id": ORG_A, "role": "owner"}, {"org_id": ORG_B, "role": "owner"},
    ]))
    import payment_methods_api as api
    import payment_methods_manager as manager_module
    manager = manager_module.PaymentMethodsManager()
    lookup = AsyncMock(side_effect=lambda org: {"id": "cus_a" if org == f"org_{ORG_A}" else "cus_b"})
    monkeypatch.setitem(sys.modules, "stripe_integration", SimpleNamespace(
        stripe_integration=SimpleNamespace(get_customer_for_org=lookup)))
    legacy = Mock(return_value=SimpleNamespace(data=[SimpleNamespace(id="cus_a")]))
    monkeypatch.setattr(manager_module.stripe.Customer, "list", legacy)
    manager.list_payment_methods = AsyncMock(return_value={"payment_methods": [], "default_payment_method_id": None, "count": 0})
    manager.create_setup_intent = AsyncMock(return_value={"client_secret": "fake", "setup_intent_id": "seti_fake"})
    manager.set_default_payment_method = AsyncMock(return_value=True)
    manager.remove_payment_method = AsyncMock(return_value=True)
    manager.update_billing_address = AsyncMock(return_value=True)
    manager.get_upcoming_invoice = AsyncMock(return_value=None)
    manager.get_payment_method_details = AsyncMock(return_value={"id": "pm_b", "customer": "cus_b"})
    session = {"user": {"sub": "subject", "email": "same@example.test", "org_id": ORG_B}, "org_id": ORG_B}
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_current_user] = lambda: session
    app.dependency_overrides[api.get_payment_methods_manager] = lambda: manager
    return app, manager, lookup, legacy, session


ROUTES = [
    ("GET", "", None, "list_payment_methods", 200),
    ("POST", "/setup-intent", {"metadata": {"org_id": ORG_A}}, "create_setup_intent", 200),
    ("POST", "/pm_b/set-default", None, "set_default_payment_method", 200),
    ("DELETE", "/pm_b", None, "remove_payment_method", 200),
    ("PUT", "/billing-address", {"address": {"line1": "1 Test St", "city": "Test", "state": "NY", "postal_code": "10001"}}, "update_billing_address", 200),
    ("GET", "/upcoming-invoice", None, "get_upcoming_invoice", 404),
    ("GET", "/pm_b/details", None, "get_payment_method_details", 200),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body,operation,expected", ROUTES)
async def test_real_routes_select_customer_by_org_not_shared_email(payment_routes, method, path, body, operation, expected):
    app, manager, lookup, legacy, session = payment_routes
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/api/v1/payment-methods" + path, json=body)
    assert response.status_code == expected, response.text
    lookup.assert_awaited_once_with(f"org_{ORG_B}")
    legacy.assert_not_called()
    call = getattr(manager, operation).await_args
    assert call is not None
    if operation == "get_payment_method_details":
        assert call.kwargs["stripe_customer_id"] == "cus_b"
    else:
        assert (call.kwargs.get("stripe_customer_id") or call.args[0]) == "cus_b"
    if operation == "create_setup_intent":
        assert call.kwargs["metadata"]["org_id"] == f"org_{ORG_B}"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body,operation,expected", ROUTES)
async def test_missing_org_fails_before_provider_lookup(payment_routes, method, path, body, operation, expected):
    app, manager, lookup, legacy, session = payment_routes
    session.clear()
    session["user"] = {"email": "same@example.test"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/api/v1/payment-methods" + path, json=body)
    assert response.status_code == 409
    lookup.assert_not_called()
    legacy.assert_not_called()
    getattr(manager, operation).assert_not_called()


@pytest.mark.asyncio
async def test_customer_lookup_does_not_fallback_for_legacy_data(payment_routes):
    app, manager, lookup, legacy, session = payment_routes
    lookup.side_effect = None
    lookup.return_value = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/payment-methods")
    assert response.status_code == 200
    assert response.json()["count"] == 0
    manager.list_payment_methods.assert_not_called()
    legacy.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["set_default_payment_method", "remove_payment_method", "get_payment_method_details"])
async def test_foreign_payment_method_rejected_before_mutation(monkeypatch, operation):
    import payment_methods_manager as module
    manager = module.PaymentMethodsManager()
    monkeypatch.setattr(module.stripe.PaymentMethod, "retrieve", Mock(return_value=SimpleNamespace(customer="cus_a")))
    modify = Mock()
    detach = Mock()
    subscriptions = Mock(return_value=SimpleNamespace(data=[]))
    monkeypatch.setattr(module.stripe.Customer, "modify", modify)
    monkeypatch.setattr(module.stripe.PaymentMethod, "detach", detach)
    monkeypatch.setattr(module.stripe.Subscription, "list", subscriptions)
    monkeypatch.setattr(module.stripe.PaymentMethod, "list", Mock(return_value=SimpleNamespace(data=[])))
    with pytest.raises(HTTPException) as exc:
        await getattr(manager, operation)(payment_method_id="pm_a", stripe_customer_id="cus_b")
    assert exc.value.status_code == 403
    modify.assert_not_called()
    detach.assert_not_called()
    subscriptions.assert_not_called()


@pytest.mark.asyncio
async def test_same_email_org_switch_and_retry_stay_pinned(payment_routes):
    app, manager, lookup, legacy, session = payment_routes
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for org in (ORG_A, ORG_B, ORG_B):
            session["org_id"] = org
            session["user"]["org_id"] = org
            response = await client.get("/api/v1/payment-methods")
            assert response.status_code == 200
    assert [call.args[0] for call in lookup.await_args_list] == [f"org_{ORG_A}", f"org_{ORG_B}", f"org_{ORG_B}"]
    assert [call.args[0] for call in manager.list_payment_methods.await_args_list] == ["cus_a", "cus_b", "cus_b"]
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_conflicting_session_org_rejected_before_provider_lookup(payment_routes):
    app, manager, lookup, legacy, session = payment_routes
    session["org_id"] = ORG_A
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/payment-methods")
    assert response.status_code == 409
    lookup.assert_not_called()
    legacy.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,operation", [
    ("POST", "/pm_a/set-default", "set_default_payment_method"),
    ("DELETE", "/pm_a", "remove_payment_method"),
    ("GET", "/pm_a/details", "get_payment_method_details"),
])
async def test_real_routes_reject_foreign_payment_method(payment_routes, monkeypatch, method, path, operation):
    import payment_methods_manager as module
    app, manager, lookup, legacy, session = payment_routes
    setattr(manager, operation, getattr(module.PaymentMethodsManager, operation).__get__(manager))
    monkeypatch.setattr(module.stripe.PaymentMethod, "retrieve", Mock(return_value=SimpleNamespace(customer="cus_a")))
    modify = Mock(side_effect=AssertionError("foreign customer must not mutate"))
    detach = Mock(side_effect=AssertionError("foreign payment method must not detach"))
    subscriptions = Mock(side_effect=AssertionError("reject ownership before subscription lookup"))
    monkeypatch.setattr(module.stripe.Customer, "modify", modify)
    monkeypatch.setattr(module.stripe.PaymentMethod, "detach", detach)
    monkeypatch.setattr(module.stripe.Subscription, "list", subscriptions)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/api/v1/payment-methods" + path)
    assert response.status_code == 403, response.text
    modify.assert_not_called()
    detach.assert_not_called()
    subscriptions.assert_not_called()
    legacy.assert_not_called()
