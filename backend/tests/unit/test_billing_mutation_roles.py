"""Real routers enforce database membership roles before any billing provider I/O."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from test_billing_registered_routes import routes, import_route, fake_module
from test_payment_methods_org_routes import payment_routes
from test_billing_read_org_isolation import billing

ORG = "22222222-2222-4222-8222-222222222222"


def membership(monkeypatch, session, role):
    import billing_org_identity as identity
    session["user"]["sub"] = "subject-b"
    # Global session privileges must never bypass an ordinary org membership.
    session["user"].update(role="admin", is_admin=True)
    # Being owner of another org must not grant billing rights in selected B.
    lookup = AsyncMock(return_value=[
        {"org_id": "11111111-1111-4111-8111-111111111111", "role": "owner"},
        {"org_id": ORG, "role": role},
    ])
    monkeypatch.setattr(identity, "_membership_orgs", lookup)
    return lookup


async def call(app, method, path, body=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                cookies={"session_token": "fixture"}) as client:
        return await client.request(method, path, json=body)


STRIPE_MUTATIONS = [
    ("/subscriptions/checkout", {"tier_id": "professional"}),
    ("/portal/create", None),
    ("/subscription/cancel", {"subscription_id": "sub_b"}),
    ("/subscription/upgrade", {"new_tier_id": "professional"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "owner", "admin", "billing_admin"])
@pytest.mark.parametrize("path,body", STRIPE_MUTATIONS)
async def test_stripe_mutations_require_selected_org_billing_role(routes, monkeypatch, role, path, body):
    import asyncpg
    membership(monkeypatch, routes.selected, role)
    boundary = AsyncMock(side_effect=HTTPException(418, "provider boundary reached"))
    if path.endswith("checkout"):
        monkeypatch.setattr(asyncpg, "connect", boundary)
    else:
        routes.service.get_customer_for_org = boundary
    response = await call(routes.app, "POST", "/api/v1/billing" + path, body)
    assert response.status_code == (403 if role == "member" else 418), response.text
    assert boundary.await_count == (0 if role == "member" else 1)
    routes.service.get_customer_by_email.assert_not_called()


PAYMENT_MUTATIONS = [
    ("POST", "/setup-intent", {}),
    ("POST", "/pm_b/set-default", None),
    ("DELETE", "/pm_b", None),
    ("PUT", "/billing-address", {"address": {"line1": "1 Test St", "city": "Test", "state": "NY", "postal_code": "10001"}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "owner", "admin", "billing_admin"])
@pytest.mark.parametrize("method,path,body", PAYMENT_MUTATIONS)
async def test_payment_mutations_require_selected_org_billing_role(payment_routes, monkeypatch, role, method, path, body):
    app, manager, _, _, session = payment_routes
    membership(monkeypatch, session, role)
    boundary = AsyncMock(side_effect=HTTPException(418, "provider boundary reached"))
    monkeypatch.setattr(manager, "get_stripe_customer_id", boundary)
    response = await call(app, method, "/api/v1/payment-methods" + path, body)
    assert response.status_code == (403 if role == "member" else 418), response.text
    assert boundary.await_count == (0 if role == "member" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "owner", "admin", "billing_admin"])
async def test_invoice_retry_requires_selected_org_billing_role(billing, monkeypatch, role):
    _, api, session, app = billing
    membership(monkeypatch, session, role)
    invoices = AsyncMock(return_value=[{"lago_id": "invoice-b", "number": "B"}])
    monkeypatch.setattr(api, "get_invoices_for", invoices)
    response = await call(app, "POST", "/api/v1/billing/invoices/invoice-b/retry")
    assert response.status_code == (403 if role == "member" else 200), response.text
    assert api.lago_retry_invoice_payment.await_count == (0 if role == "member" else 1)
    assert invoices.await_count == (0 if role == "member" else 1)


@pytest.fixture
def subscription_routes(monkeypatch):
    fake_module(monkeypatch, "get_credential", get_credential=lambda name: None)
    fake_module(monkeypatch, "email_notifications", EmailNotificationService=Mock())
    import_route(monkeypatch, "subscription_manager")
    import_route(monkeypatch, "lago_integration")
    fake_module(monkeypatch, "stripe_integration", OPS_CENTER_STRIPE_SUITE="unicorn-commander")
    fake_module(monkeypatch, "paid_org_provisioning", provision_paid_org=AsyncMock())
    api = import_route(monkeypatch, "subscription_api")
    session = {"user": {"email": "same@example.test", "org_id": ORG}}
    app = FastAPI()
    app.state.sessions = {"fixture": session}
    app.include_router(api.router)
    return api, session, app


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "owner", "admin", "billing_admin"])
@pytest.mark.parametrize("path", ["upgrade", "change", "cancel", "downgrade", "confirm-upgrade?checkout_session_id=cs_b"])
async def test_subscription_mutations_require_selected_org_billing_role(subscription_routes, monkeypatch, role, path):
    import stripe
    api, session, app = subscription_routes
    membership(monkeypatch, session, role)
    boundary = AsyncMock(side_effect=HTTPException(418, "provider boundary reached"))
    monkeypatch.setattr(api, "get_subscription", boundary)
    checkout = Mock(side_effect=HTTPException(418, "provider boundary reached"))
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", checkout)
    response = await call(app, "POST", "/api/v1/subscriptions/" + path, {"target_tier": "professional"})
    # Older change/cancel handlers wrap provider HTTP errors in a 500. This
    # sentinel stops before external I/O; its status only proves gate admission.
    admitted_status = 402 if path == "upgrade" else (500 if path in {"change", "cancel"} else 418)
    assert response.status_code == (403 if role == "member" else admitted_status), response.text
    if role == "member":
        boundary.assert_not_called()
        checkout.assert_not_called()
    elif path.startswith("confirm-upgrade"):
        checkout.assert_called_once_with("cs_b")
    elif path != "upgrade":
        boundary.assert_awaited_once_with(f"org_{ORG}")


@pytest.mark.asyncio
async def test_ordinary_member_retains_payment_reads(payment_routes, monkeypatch):
    app, manager, lookup, _, session = payment_routes
    membership(monkeypatch, session, "member")
    response = await call(app, "GET", "/api/v1/payment-methods")
    assert response.status_code == 200, response.text
    lookup.assert_awaited_once_with(f"org_{ORG}")
    manager.list_payment_methods.assert_awaited_once()
