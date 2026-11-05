"""Org-scoped subscription entitlements from authoritative Stripe price IDs."""
from fastapi import HTTPException
import stripe

from stripe_org_identity import resolve_event_org, require_provisioning_complete


def _customer_id(subscription):
    reference = subscription.get("customer")
    return reference.get("id") if isinstance(reference, dict) else reference


async def _tier_for_subscription(subscription):
    """Require exactly one fully expanded price and one active tier mapping."""
    items = subscription.get("items") or {}
    data = items.get("data") or []
    if items.get("has_more") or len(data) != 1:
        raise HTTPException(409, "Subscription requires one unambiguous tier price")
    price = data[0].get("price") or {}
    price_id = price.get("id") if isinstance(price, dict) else None
    if not isinstance(price_id, str) or not price_id:
        raise HTTPException(409, "Subscription price identity unavailable")
    from database import get_db_connection
    async with await get_db_connection() as conn:
        tiers = await conn.fetch(
            """
            SELECT tier_code FROM subscription_tiers
            WHERE is_active = TRUE
              AND (stripe_price_monthly = $1 OR stripe_price_yearly = $1)
            """,
            price_id,
        )
    if len(tiers) != 1 or not tiers[0]["tier_code"]:
        raise HTTPException(409, "Subscription price has no unique active tier mapping")
    return tiers[0]["tier_code"]


async def sync_subscription_entitlements(event_subscription, suite):
    """Synchronize latest state; delayed events cannot replay an obsolete price.

    Identity comes exclusively from signed event / retrieved customer metadata.
    Tier metadata is deliberately ignored: plan changes can leave it stale.
    Non-active states never grant new paid entitlements. Stripe's past-due grace
    period remains unchanged; terminal canceled/unpaid subscriptions are recapped.
    """
    if ((event_subscription.get("metadata") or {}).get("suite") or "") != suite:
        return {"status": "ignored", "reason": "other suite (subscription update)"}
    org_id = resolve_event_org(event_subscription)
    subscription_id = event_subscription.get("id")
    if not isinstance(subscription_id, str) or not subscription_id:
        raise HTTPException(409, "Subscription identity unavailable")

    # Stripe events can arrive out of order. Fetch the current state, while
    # retaining the signed event's pinned identity and shared-account suite.
    latest = stripe.Subscription.retrieve(subscription_id)
    if (latest.get("id") != subscription_id
            or _customer_id(latest) != _customer_id(event_subscription)
            or (latest.get("metadata") or {}).get("suite") != suite):
        raise HTTPException(409, "Subscription event and current identity mismatch")
    if resolve_event_org(latest) != org_id:
        raise HTTPException(409, "Subscription event and current organization mismatch")

    from paid_org_provisioning import provision_paid_org, downgrade_org
    status = latest.get("status")
    if status in {"canceled", "unpaid"}:
        result = await downgrade_org(org_id, source="stripe-subscription-updated")
        require_provisioning_complete(result)
        return {"status": "downgraded", "org_id": org_id, "result": result}
    if status in {"incomplete", "incomplete_expired", "past_due", "paused", "trialing"}:
        return {"status": "ignored", "reason": "subscription not active"}
    if status != "active":
        raise HTTPException(409, "Subscription status unavailable")

    tier = await _tier_for_subscription(latest)
    result = await provision_paid_org(org_id, tier, source="stripe-subscription-updated")
    require_provisioning_complete(result)
    return {"status": "provisioned", "org_id": org_id, "result": result}
