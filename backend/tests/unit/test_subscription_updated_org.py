"""Real webhook routes, with Stripe/database/provisioning replaced at boundaries."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from test_billing_registered_routes import fake_module, import_route, ORG_A, ORG_B, EMAIL


@pytest.fixture
def updated(monkeypatch):
    import stripe
    sub = {
        "id": "sub_a", "customer": "cus_a", "status": "active",
        "metadata": {"suite": "unicorn-commander", "org_id": ORG_A, "tier_name": "stale"},
        "items": {"data": [{"price": {"id": "price_pro"}}], "has_more": False},
    }
    customers = {
        "cus_a": {"id": "cus_a", "email": EMAIL, "metadata": {"org_id": ORG_A}},
        "cus_b": {"id": "cus_b", "email": EMAIL, "metadata": {"org_id": ORG_B}},
    }
    fake_module(monkeypatch, "get_credential", get_credential=lambda name: None)
    keycloak = fake_module(monkeypatch, "keycloak_integration",
                          get_user_by_email=AsyncMock(side_effect=AssertionError("No email resolution")),
                          update_user_attributes=AsyncMock())
    fake_module(monkeypatch, "email_notifications", EmailNotificationService=Mock())
    fake_module(monkeypatch, "lago_integration", **{
        name: AsyncMock() for name in
        ("create_subscription", "terminate_subscription", "get_subscription", "update_subscription_plan")})
    provision = AsyncMock(return_value={"tier_set": True, "lago_sub": True, "key_capped": True, "cloud_cap": 1})
    downgrade = AsyncMock(return_value={"tier_set": True, "lago_sub": True})
    fake_module(monkeypatch, "paid_org_provisioning", provision_paid_org=provision, downgrade_org=downgrade)
    fetch = AsyncMock(return_value=[{"tier_code": "professional"}])
    conn = SimpleNamespace(fetch=fetch)
    context = AsyncMock()
    context.__aenter__.return_value = conn
    db = fake_module(monkeypatch, "database", get_db_connection=AsyncMock(return_value=context))
    retrieve = Mock(return_value=copy.deepcopy(sub))
    monkeypatch.setattr(stripe.Subscription, "retrieve", retrieve)
    customer_retrieve = Mock(side_effect=lambda customer: customers[customer])
    monkeypatch.setattr(stripe.Customer, "retrieve", customer_retrieve)
    monkeypatch.setattr(stripe.Customer, "search", Mock(side_effect=AssertionError("No customer search")))
    monkeypatch.setattr(stripe.Webhook, "construct_event", Mock(side_effect=lambda payload, *args: json.loads(payload)))
    route = import_route(monkeypatch, "webhooks")
    monkeypatch.setattr(route, "STRIPE_WEBHOOK_SECRET", "fixture-only")
    app = FastAPI()
    app.include_router(route.router)
    # Selected org changed after checkout; the event must remain pinned to A.
    app.state.sessions = {"fixture": {"user": {"org_id": ORG_B, "email": EMAIL}}}
    return SimpleNamespace(app=app, event={"type": "customer.subscription.updated", "data": {"object": sub}},
                           latest=retrieve.return_value, retrieve=retrieve, customers=customers,
                           customer_retrieve=customer_retrieve, provision=provision, downgrade=downgrade,
                           fetch=fetch, db=db, keycloak=keycloak)


async def send(updated, path="/api/v1/webhooks/stripe"):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=updated.app),
                                base_url="http://test", cookies={"session_token": "fixture"}) as client:
        return await client.post(path, json=updated.event, headers={"stripe-signature": "fixture"})


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/webhooks/stripe", "/api/v1/webhooks/stripe/subscription-updated"])
async def test_updated_actual_router_syncs_pinned_org_from_actual_price(updated, path):
    response = await send(updated, path)
    assert response.status_code == 200, response.text
    updated.provision.assert_awaited_once()
    assert updated.provision.await_args.args == (ORG_A, "professional")
    updated.keycloak.get_user_by_email.assert_not_awaited()
    assert updated.fetch.await_args.args[1] == "price_pro"


@pytest.mark.asyncio
async def test_updated_uses_latest_subscription_price_not_delayed_event(updated):
    updated.event["data"]["object"]["items"]["data"][0]["price"]["id"] = "price_old"
    response = await send(updated)
    assert response.status_code == 200, response.text
    updated.retrieve.assert_called_once_with("sub_a")
    assert updated.fetch.await_args.args[1] == "price_pro"
    assert updated.provision.await_args.args == (ORG_A, "professional")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["event_org", "latest_org", "latest_customer", "latest_id", "latest_suite", "missing_customer_org"])
async def test_updated_rejects_identity_conflicts(updated, case):
    if case == "event_org":
        updated.event["data"]["object"]["metadata"]["org_id"] = ORG_B
    elif case == "latest_org":
        updated.latest["metadata"]["org_id"] = ORG_B
    elif case == "latest_customer":
        updated.latest["customer"] = "cus_b"
    elif case == "latest_id":
        updated.latest["id"] = "sub_b"
    elif case == "latest_suite":
        updated.latest["metadata"]["suite"] = "other"
    else:
        updated.customers["cus_a"]["metadata"] = {}
    response = await send(updated)
    assert response.status_code == 409, response.text
    updated.provision.assert_not_awaited()
    updated.downgrade.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unmapped", "ambiguous", "multiple_items", "paginated", "missing_price"])
async def test_updated_rejects_ambiguous_price_without_grant(updated, case):
    if case == "unmapped":
        updated.fetch.return_value = []
    elif case == "ambiguous":
        updated.fetch.return_value = [{"tier_code": "one"}, {"tier_code": "two"}]
    elif case == "multiple_items":
        updated.latest["items"]["data"].append({"price": {"id": "price_extra"}})
    elif case == "paginated":
        updated.latest["items"]["has_more"] = True
    else:
        updated.latest["items"]["data"][0]["price"] = {}
    response = await send(updated)
    assert response.status_code == 409, response.text
    updated.provision.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["provider", "database", "partial", "provision_exception"])
async def test_updated_retries_failures_on_same_pinned_org(updated, case):
    if case == "provider":
        updated.retrieve.side_effect = RuntimeError("fixture provider failure")
    elif case == "database":
        updated.fetch.side_effect = RuntimeError("fixture database failure")
    elif case == "partial":
        updated.provision.return_value = {"tier_set": True, "lago_sub": False}
    else:
        updated.provision.side_effect = RuntimeError("fixture provisioning failure")
    first = await send(updated)
    assert first.status_code == 503, first.text
    updated.retrieve.side_effect = None
    updated.fetch.side_effect = None
    updated.provision.side_effect = None
    updated.provision.return_value = {"tier_set": True, "lago_sub": True}
    retry = await send(updated)
    assert retry.status_code == 200, retry.text
    assert updated.provision.await_args.args == (ORG_A, "professional")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["incomplete", "incomplete_expired", "past_due", "paused", "trialing"])
async def test_updated_nonactive_subscription_never_grants(updated, status):
    updated.latest["status"] = status
    response = await send(updated)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ignored"
    updated.provision.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["canceled", "unpaid"])
async def test_updated_terminal_subscription_downgrades_pinned_org(updated, status):
    updated.latest["status"] = status
    response = await send(updated)
    assert response.status_code == 200, response.text
    updated.provision.assert_not_awaited()
    assert updated.downgrade.await_args.args == (ORG_A,)


@pytest.mark.asyncio
async def test_updated_foreign_suite_is_ignored_without_provider_access(updated):
    updated.event["data"]["object"]["metadata"]["suite"] = "other"
    response = await send(updated)
    assert response.status_code == 200
    updated.retrieve.assert_not_called()
    updated.customer_retrieve.assert_not_called()
    updated.provision.assert_not_awaited()


@pytest.mark.asyncio
async def test_updated_accepts_stripe_objects_and_yearly_price(updated):
    import stripe
    updated.latest["items"]["data"][0]["price"]["id"] = "price_pro_year"
    updated.retrieve.return_value = stripe.StripeObject.construct_from(updated.latest, None)
    updated.customers["cus_a"] = stripe.StripeObject.construct_from(updated.customers["cus_a"], None)
    response = await send(updated)
    assert response.status_code == 200, response.text
    sql, price = updated.fetch.await_args.args
    assert price == "price_pro_year"
    assert "is_active = TRUE" in sql
    assert "stripe_price_monthly = $1 OR stripe_price_yearly = $1" in sql
    assert updated.provision.await_args.args == (ORG_A, "professional")


@pytest.mark.asyncio
async def test_updated_customer_metadata_resolves_legacy_subscription_without_email(updated):
    updated.event["data"]["object"]["metadata"].pop("org_id")
    updated.latest["metadata"].pop("org_id")
    response = await send(updated)
    assert response.status_code == 200, response.text
    assert updated.provision.await_args.args == (ORG_A, "professional")
    updated.keycloak.get_user_by_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_updated_downgrade_partial_failure_retries(updated):
    updated.latest["status"] = "canceled"
    updated.downgrade.return_value = {"tier_set": True, "lago_sub": False}
    first = await send(updated)
    assert first.status_code == 503, first.text
    updated.downgrade.return_value = {"tier_set": True, "lago_sub": True}
    retry = await send(updated)
    assert retry.status_code == 200, retry.text
    assert [call.args for call in updated.downgrade.await_args_list] == [(ORG_A,), (ORG_A,)]
    updated.provision.assert_not_awaited()
