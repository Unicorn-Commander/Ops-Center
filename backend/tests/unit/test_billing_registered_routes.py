"""Exercise imported billing routers over HTTP with all remote effects mocked."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

ORG_A = "org_11111111-1111-4111-8111-111111111111"
ORG_B = "org_22222222-2222-4222-8222-222222222222"
EMAIL = "shared@example.test"
BACKEND = Path(__file__).resolve().parents[2]


def fake_module(monkeypatch, name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def import_route(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(name, BACKEND / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def subscription(org=ORG_B, customer="cus_b", subscription_id="sub_b"):
    return {"id": subscription_id, "customer": customer, "status": "active",
            "current_period_end": 1900000000, "cancel_at_period_end": False,
            "metadata": {"org_id": org, "suite": "unicorn-commander", "tier_name": "professional"},
            "items": {"data": [{"price": {"unit_amount": 100}}]}}


@pytest.fixture
def routes(monkeypatch):
    import billing_org_identity as identity
    # Provider tests authenticate one subject with persisted membership in both
    # fixture tenants. Selected context still chooses exactly one tenant.
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=[
        {"org_id": ORG_A, "role": "owner"}, {"org_id": ORG_B, "role": "owner"},
    ]))
    import stripe
    customers = {
        "cus_a": {"id": "cus_a", "email": EMAIL, "metadata": {"org_id": ORG_A}},
        "cus_b": {"id": "cus_b", "email": EMAIL, "metadata": {"org_id": ORG_B}},
    }
    selected = {"user": {"sub": "subject", "email": EMAIL, "org_id": ORG_B}}
    get_user = AsyncMock(return_value={"id": "subject", "email": EMAIL,
                                     "attributes": {"org_id": [ORG_B]}})
    fake_module(monkeypatch, "get_credential", get_credential=lambda name: None)
    fake_module(monkeypatch, "keycloak_integration", get_user_by_email=get_user,
                update_user_attributes=AsyncMock(),
                get_user_tier_info=AsyncMock(return_value={"subscription_tier": "professional"}))
    fake_module(monkeypatch, "email_notifications", EmailNotificationService=Mock())
    fake_module(monkeypatch, "lago_integration", **{
        name: AsyncMock(return_value=None) for name in
        ("create_subscription", "terminate_subscription", "get_subscription", "update_subscription_plan")})
    provision = AsyncMock(return_value={"status": "ok"})
    downgrade = AsyncMock(return_value={"status": "ok"})
    fake_module(monkeypatch, "paid_org_provisioning", provision_paid_org=provision, downgrade_org=downgrade)
    service = SimpleNamespace(
        get_customer_for_org=AsyncMock(side_effect=lambda org: customers["cus_a" if org == ORG_A else "cus_b"]),
        get_customer_by_email=AsyncMock(return_value=customers["cus_a"]),
        create_customer_portal_session=AsyncMock(return_value="https://billing.example.test/portal"),
        get_customer_payment_methods=AsyncMock(return_value=[]),
        get_customer_subscriptions=AsyncMock(side_effect=lambda customer: [subscription(
            ORG_A if customer == "cus_a" else ORG_B, customer, "sub_a" if customer == "cus_a" else "sub_b")]),
        cancel_subscription=AsyncMock(return_value=True), update_subscription=AsyncMock(return_value=True),
    )
    fake_module(monkeypatch, "stripe_integration", stripe_integration=service,
                OPS_CENTER_STRIPE_SUITE="unicorn-commander")
    fake_module(monkeypatch, "subscription_manager", subscription_manager=SimpleNamespace(
        get_plan=Mock(return_value=SimpleNamespace(stripe_price_id="price_test", stripe_annual_price_id="price_year", display_name="Pro"))))
    fake_module(monkeypatch, "redis_session", redis_session_manager=SimpleNamespace(get=lambda token: selected))
    retrieve = Mock(side_effect=lambda customer: customers[customer])
    monkeypatch.setattr(stripe.Customer, "retrieve", retrieve)
    monkeypatch.setattr(stripe.Customer, "search", Mock(side_effect=AssertionError("Unexpected Stripe search")))
    monkeypatch.setattr(stripe.Webhook, "construct_event", Mock(side_effect=lambda payload, *args: json.loads(payload)))
    # Guard against any accidentally introduced live database lookup.
    import asyncpg
    monkeypatch.setattr(asyncpg, "connect", AsyncMock(side_effect=AssertionError("Unexpected database connection")))
    webhooks = import_route(monkeypatch, "webhooks")
    monkeypatch.setattr(webhooks, "STRIPE_WEBHOOK_SECRET", "fixture-only-signature-secret")
    billing = import_route(monkeypatch, "stripe_api")
    app = FastAPI()
    app.include_router(webhooks.router)
    app.include_router(billing.router)
    return SimpleNamespace(app=app, service=service, customers=customers, selected=selected,
                           provision=provision, downgrade=downgrade, get_user=get_user, retrieve=retrieve)


async def request(routes, method, path, payload=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=routes.app),
                                base_url="http://test", cookies={"session_token": "fixture"}) as client:
        return await client.request(method, path, json=payload, headers={"stripe-signature": "fixture"})


def event(event_type="checkout.session.completed", org=ORG_A):
    metadata = {"suite": "unicorn-commander", "tier_name": "professional"}
    if org is not None:
        metadata["org_id"] = org
    return {"type": event_type, "data": {"object": {
        "id": "cs_fixture" if event_type.startswith("checkout") else "sub_a",
        "customer": "cus_a", "customer_email": EMAIL, "subscription": "sub_a",
        "payment_status": "paid", "metadata": metadata}}}


@pytest.mark.asyncio
@pytest.mark.parametrize("path,event_type", [
    ("/api/v1/webhooks/stripe", "checkout.session.completed"),
    ("/api/v1/webhooks/stripe/checkout-completed", "checkout.session.completed"),
    ("/api/v1/webhooks/stripe", "customer.subscription.deleted"),
])
async def test_webhook_pins_checkout_org_despite_selected_org_change(routes, path, event_type):
    # Both customers share an email; checkout was A, current session/Keycloak is B.
    response = await request(routes, "POST", path, event(event_type))
    assert response.status_code == 200, response.text
    effect = routes.downgrade if event_type.endswith("deleted") else routes.provision
    assert effect.await_count == 1
    assert effect.await_args.args[0] == ORG_A
    routes.get_user.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type,path", [
    ("checkout.session.completed", "/api/v1/webhooks/stripe"),
    ("customer.subscription.deleted", "/api/v1/webhooks/stripe"),
    ("checkout.session.completed", "/api/v1/webhooks/stripe/checkout-completed"),
])
@pytest.mark.parametrize("case", ["conflict", "missing_both", "missing_customer"])
async def test_webhook_rejects_ambiguous_or_conflicting_metadata(routes, event_type, case, path):
    payload = event(event_type, None if case == "missing_both" else ORG_A)
    routes.customers["cus_a"]["metadata"] = {"org_id": ORG_B} if case == "conflict" else {}
    response = await request(routes, "POST", path, payload)
    assert response.status_code >= 400, response.text
    routes.provision.assert_not_awaited()
    routes.downgrade.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_event_can_use_unambiguous_customer_metadata(routes):
    response = await request(routes, "POST", "/api/v1/webhooks/stripe", event(org=None))
    assert response.status_code == 200, response.text
    assert routes.provision.await_args.args[0] == ORG_A
    routes.get_user.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/webhooks/stripe", "/api/v1/webhooks/stripe/checkout-completed"])
async def test_foreign_suite_never_provisions_or_looks_up_customer(routes, path):
    payload = event()
    payload["data"]["object"]["metadata"]["suite"] = "another-suite"
    response = await request(routes, "POST", path, payload)
    assert response.status_code == 200
    routes.provision.assert_not_awaited()
    routes.downgrade.assert_not_awaited()
    routes.retrieve.assert_not_called()


BILLING_CASES = [
    ("POST", "/portal/create", None, "create_customer_portal_session"),
    ("GET", "/payment-methods", None, "get_customer_payment_methods"),
    ("GET", "/subscription-status", None, "get_customer_subscriptions"),
    ("POST", "/subscription/cancel", {"subscription_id": "sub_b"}, "cancel_subscription"),
    ("POST", "/subscription/upgrade", {"new_tier_id": "professional"}, "update_subscription"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,payload,effect", BILLING_CASES)
async def test_same_email_billing_routes_use_selected_org_customer(routes, method, path, payload, effect):
    response = await request(routes, method, "/api/v1/billing" + path, payload)
    assert response.status_code == 200, response.text
    routes.service.get_customer_for_org.assert_awaited_once_with(ORG_B)
    routes.service.get_customer_by_email.assert_not_awaited()
    call = getattr(routes.service, effect).await_args
    assert call is not None
    if effect in {"cancel_subscription", "update_subscription"}:
        assert call.kwargs["subscription_id"] == "sub_b"
    else:
        assert call.args[0] == "cus_b"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,payload,effect", BILLING_CASES)
async def test_missing_selected_org_fails_before_customer_lookup(routes, method, path, payload, effect):
    routes.selected["user"].pop("org_id")
    response = await request(routes, method, "/api/v1/billing" + path, payload)
    assert response.status_code >= 400, response.text
    routes.service.get_customer_for_org.assert_not_awaited()
    routes.service.get_customer_by_email.assert_not_awaited()
    getattr(routes.service, effect).assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", [
    ("/subscription/cancel", {"subscription_id": "sub_b"}),
    ("/subscription/upgrade", {"new_tier_id": "professional"}),
    ("/subscription-status", None),
])
@pytest.mark.parametrize("case", ["wrong_org", "missing_org", "wrong_customer"])
async def test_subscription_routes_reject_foreign_or_unpinned_subscription(routes, path, payload, case):
    sub = subscription()
    if case == "wrong_org":
        sub["metadata"]["org_id"] = ORG_A
    elif case == "missing_org":
        sub["metadata"].pop("org_id")
    else:
        sub["customer"] = "cus_a"
    routes.service.get_customer_subscriptions.side_effect = None
    routes.service.get_customer_subscriptions.return_value = [sub]
    response = await request(routes, "GET" if payload is None else "POST", "/api/v1/billing" + path, payload)
    assert response.status_code >= 400, response.text
    routes.service.cancel_subscription.assert_not_awaited()
    routes.service.update_subscription.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_customer_lookup_failure_is_retryable_without_wrong_org_mutation(routes):
    payload = event()
    routes.retrieve.side_effect = RuntimeError("fixture temporary outage")
    first = await request(routes, "POST", "/api/v1/webhooks/stripe", payload)
    assert first.status_code >= 500, first.text
    routes.provision.assert_not_awaited()
    routes.retrieve.side_effect = lambda customer: routes.customers[customer]
    retried = await request(routes, "POST", "/api/v1/webhooks/stripe", payload)
    assert retried.status_code == 200, retried.text
    assert routes.provision.await_count == 1
    assert routes.provision.await_args.args[0] == ORG_A


@pytest.mark.asyncio
async def test_portal_switching_selected_org_uses_distinct_same_email_customers(routes):
    for org in (ORG_A, ORG_B):
        routes.selected["user"]["org_id"] = org
        response = await request(routes, "POST", "/api/v1/billing/portal/create")
        assert response.status_code == 200, response.text
    assert [call.args[0] for call in routes.service.create_customer_portal_session.await_args_list] == ["cus_a", "cus_b"]
    routes.service.get_customer_by_email.assert_not_awaited()


@pytest.fixture
def confirm_routes(routes, monkeypatch):
    from enum import Enum
    from pydantic import BaseModel
    import stripe
    class FixturePlan(BaseModel):
        pass
    class FixtureService(str, Enum):
        billing = "billing"
    manager = sys.modules["subscription_manager"]
    monkeypatch.setattr(manager, "SubscriptionPlan", FixturePlan, raising=False)
    monkeypatch.setattr(manager, "ServiceAccessConfig", FixturePlan, raising=False)
    monkeypatch.setattr(manager, "ServiceType", FixtureService, raising=False)
    monkeypatch.setattr(manager, "PermissionLevel", FixtureService, raising=False)
    lago = sys.modules["lago_integration"]
    for name in ("get_customer", "get_subscription_by_email", "get_subscription_for",
                 "get_or_create_customer", "get_current_usage", "get_invoices"):
        monkeypatch.setattr(lago, name, AsyncMock(), raising=False)
    # Return a Stripe-shaped mapping supporting both item and attribute access.
    checkout = stripe.StripeObject.construct_from(event()["data"]["object"], None)
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", Mock(return_value=checkout))
    module = import_route(monkeypatch, "subscription_api")
    routes.app.include_router(module.router)
    routes.app.state.sessions = {"fixture": routes.selected}
    routes.checkout = checkout
    routes.lago = lago
    routes.keycloak_update = sys.modules["keycloak_integration"].update_user_attributes
    return routes


@pytest.mark.asyncio
@pytest.mark.parametrize("case,status", [("other_selected_org", 403), ("foreign_suite", 409), ("metadata_conflict", 409)])
async def test_confirm_upgrade_rejects_unowned_or_foreign_checkout(confirm_routes, case, status):
    routes = confirm_routes
    if case != "other_selected_org":
        routes.selected["user"]["org_id"] = ORG_A
    if case == "foreign_suite":
        routes.checkout.metadata["suite"] = "another-suite"
    elif case == "metadata_conflict":
        routes.customers["cus_a"]["metadata"]["org_id"] = ORG_B
    response = await request(routes, "POST", "/api/v1/subscriptions/confirm-upgrade?checkout_session_id=cs_fixture")
    assert response.status_code == status, response.text
    routes.provision.assert_not_awaited()
    routes.lago.create_subscription.assert_not_awaited()
    routes.lago.terminate_subscription.assert_not_awaited()
    routes.keycloak_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_upgrade_uses_pinned_selected_org_provisioner(confirm_routes):
    routes = confirm_routes
    routes.selected["user"]["org_id"] = ORG_A
    response = await request(routes, "POST", "/api/v1/subscriptions/confirm-upgrade?checkout_session_id=cs_fixture")
    assert response.status_code == 200, response.text
    routes.provision.assert_awaited_once()
    assert routes.provision.await_args.args[0] == ORG_A
    routes.lago.create_subscription.assert_not_awaited()
    routes.keycloak_update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["checkout.session.completed", "customer.subscription.deleted"])
@pytest.mark.parametrize("partial_result", [
    {"tier_set": False},
    {"lago_sub": False},
    {"cloud_cap": 0, "key_capped": False},
    {"lago_error": "fixture temporary failure"},
])
async def test_webhook_partial_provisioning_is_retryable(routes, event_type, partial_result):
    effect = routes.downgrade if event_type.endswith("deleted") else routes.provision
    effect.return_value = partial_result
    response = await request(routes, "POST", "/api/v1/webhooks/stripe", event(event_type))
    assert response.status_code == 503, response.text
    assert effect.await_args.args[0] == ORG_A
    # A repeated event still targets its pinned organization after recovery.
    effect.return_value = {"tier_set": True, "lago_sub": True, "cloud_cap": 0, "key_capped": True}
    retry = await request(routes, "POST", "/api/v1/webhooks/stripe", event(event_type))
    assert retry.status_code == 200, retry.text
    assert [call.args[0] for call in effect.await_args_list] == [ORG_A, ORG_A]
