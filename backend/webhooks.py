"""
Webhook Handlers for Stripe and Lago Events
Handles subscription lifecycle events from payment providers
"""

from fastapi import APIRouter, Request, HTTPException, Header
from typing import Any, Optional
import logging
import os
import stripe
from billing_org_identity import lago_org_id
from stripe_org_identity import require_provisioning_complete

from lago_integration import (
    create_subscription,
    terminate_subscription,
    get_subscription,
    update_subscription_plan
)
from keycloak_integration import update_user_attributes, get_user_by_email
from email_notifications import EmailNotificationService

# Import universal credential helper
from get_credential import get_credential

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Initialize Stripe - read credentials from database first, then environment
STRIPE_WEBHOOK_SECRET = get_credential("STRIPE_WEBHOOK_SECRET")
stripe.api_key = get_credential("STRIPE_SECRET_KEY")

# Suite marker — the Stripe account is SHARED across suites (unicorn-commander,
# magicunicorn, majiks, ...) and Stripe fans every event out to all webhooks.
# The ops-center webhook ONLY acts on events carrying this marker, so another
# suite's purchase can never trigger ops-center paid-org provisioning.
OPS_CENTER_SUITE = os.getenv("OPS_CENTER_STRIPE_SUITE", "unicorn-commander")

# Email service
email_service = EmailNotificationService()


def _stripe_value(value: Any, key: str, default: Any = None) -> Any:
    """Read a Stripe mapping or StripeObject without assuming one SDK shape."""
    if isinstance(value, dict):
        return value.get(key, default)
    try:
        return value.get(key, default)
    except (AttributeError, TypeError):
        return getattr(value, key, default)


def _stripe_mapping(value: Any) -> Any:
    """Convert a StripeObject recursively when a helper needs mapping methods."""
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None) or getattr(value, "_to_dict_recursive", None)
    if callable(to_dict):
        return to_dict()
    return value


def _subscription_customer_id(subscription: Any) -> Optional[str]:
    customer = _stripe_value(subscription, "customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    else:
        customer = _stripe_value(customer, "id", customer)
    return str(customer) if customer else None


def _resolve_subscription_org(subscription: Any) -> str:
    """Resolve and validate org identity without assuming Stripe dict objects."""
    customer_id = _subscription_customer_id(subscription)
    if not customer_id:
        raise HTTPException(409, "Stripe customer identity unavailable")
    customer = _stripe_mapping(stripe.Customer.retrieve(customer_id))
    if _stripe_value(customer, "id") != customer_id:
        raise HTTPException(409, "Stripe customer identity mismatch")
    customer_metadata = _stripe_mapping(_stripe_value(customer, "metadata", {}) or {})
    customer_org = lago_org_id(customer_metadata.get("org_id"))
    event_metadata = _stripe_mapping(_stripe_value(subscription, "metadata", {}) or {})
    event_org = event_metadata.get("org_id")
    if event_org is not None and lago_org_id(event_org) != customer_org:
        raise HTTPException(409, "Stripe event and customer organization mismatch")
    return customer_org


async def _sync_single_subscription_entitlements(event_subscription):
    """Mapping-safe equivalent of the existing one-item update contract."""
    metadata = _stripe_mapping(_stripe_value(event_subscription, "metadata", {}) or {})
    if metadata.get("suite") != OPS_CENTER_SUITE:
        return {"status": "ignored", "reason": "other suite (subscription update)"}
    org_id = _resolve_subscription_org(event_subscription)
    subscription_id = _stripe_value(event_subscription, "id")
    if not isinstance(subscription_id, str) or not subscription_id:
        raise HTTPException(409, "Subscription identity unavailable")

    latest = stripe.Subscription.retrieve(subscription_id)
    latest_metadata = _stripe_mapping(_stripe_value(latest, "metadata", {}) or {})
    if (
        _stripe_value(latest, "id") != subscription_id
        or _subscription_customer_id(latest) != _subscription_customer_id(event_subscription)
        or latest_metadata.get("suite") != OPS_CENTER_SUITE
        or _resolve_subscription_org(latest) != org_id
    ):
        raise HTTPException(409, "Subscription event and current identity mismatch")

    status = _stripe_value(latest, "status")
    from paid_org_provisioning import downgrade_org, provision_paid_org
    if status in {"canceled", "unpaid"}:
        result = await downgrade_org(org_id, source="stripe-subscription-updated")
        require_provisioning_complete(result)
        return {"status": "downgraded", "org_id": org_id, "result": result}
    if status in {"incomplete", "incomplete_expired", "past_due", "paused", "trialing"}:
        return {"status": "ignored", "reason": "subscription not active"}
    if status != "active":
        raise HTTPException(409, "Subscription status unavailable")

    items_container = _stripe_value(latest, "items", {}) or {}
    items = _stripe_value(items_container, "data", []) or []
    if _stripe_value(items_container, "has_more", False) or len(items) != 1:
        raise HTTPException(409, "Subscription requires one unambiguous tier price")
    price_id = _subscription_price_id(items[0])
    if not price_id:
        raise HTTPException(409, "Subscription price identity unavailable")

    from database import get_db_connection
    async with await get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT tier_code FROM subscription_tiers
            WHERE is_active = TRUE
              AND (stripe_price_monthly = $1 OR stripe_price_yearly = $1)
            """,
            price_id,
        )
    tier_row = _stripe_mapping(rows[0]) if len(rows) == 1 else None
    if not tier_row or not tier_row.get("tier_code"):
        raise HTTPException(409, "Subscription price has no unique active tier mapping")

    result = await provision_paid_org(
        org_id, tier_row["tier_code"], source="stripe-subscription-updated"
    )
    require_provisioning_complete(result)
    return {"status": "provisioned", "org_id": org_id, "result": result}


def _subscription_price_id(item: Any) -> Optional[str]:
    price = _stripe_value(item, "price", {})
    if isinstance(price, str):
        return price
    price_id = _stripe_value(price, "id")
    return str(price_id) if price_id else None


async def _fetch_one(conn, query: str, *params):
    """Use the asyncpg row API, with a tiny fixture-friendly fallback."""
    fetchrow = getattr(conn, "fetchrow", None)
    if fetchrow is not None:
        return await fetchrow(query, *params)
    rows = await conn.fetch(query, *params)
    return rows[0] if rows else None


async def _sync_subscription_with_extra_seats(event_subscription):
    """Provision a Team subscription and persist included plus extra seats."""
    metadata = _stripe_mapping(_stripe_value(event_subscription, "metadata", {}) or {})
    if metadata.get("suite") != OPS_CENTER_SUITE:
        return {"status": "ignored", "reason": "other suite (subscription update)"}

    org_id = _resolve_subscription_org(event_subscription)
    subscription_id = _stripe_value(event_subscription, "id")
    if not isinstance(subscription_id, str) or not subscription_id:
        raise HTTPException(409, "Subscription identity unavailable")

    latest = stripe.Subscription.retrieve(subscription_id)
    latest_metadata = _stripe_mapping(_stripe_value(latest, "metadata", {}) or {})
    event_customer = _subscription_customer_id(event_subscription)
    latest_customer = _subscription_customer_id(latest)
    if (
        _stripe_value(latest, "id") != subscription_id
        or latest_customer != event_customer
        or latest_metadata.get("suite") != OPS_CENTER_SUITE
        or _resolve_subscription_org(latest) != org_id
    ):
        raise HTTPException(409, "Subscription event and current identity mismatch")

    status = _stripe_value(latest, "status")
    if status in {"canceled", "unpaid"}:
        from paid_org_provisioning import downgrade_org
        result = await downgrade_org(org_id, source="stripe-subscription-updated")
        require_provisioning_complete(result)
        return {"status": "downgraded", "org_id": org_id, "result": result}
    if status in {"incomplete", "incomplete_expired", "past_due", "paused", "trialing"}:
        return {"status": "ignored", "reason": "subscription not active"}
    if status != "active":
        raise HTTPException(409, "Subscription status unavailable")

    items_container = _stripe_value(latest, "items", {}) or {}
    if _stripe_value(items_container, "has_more", False):
        raise HTTPException(409, "Subscription items require reconciliation")
    items = _stripe_value(items_container, "data", []) or []
    if len(items) < 2:
        raise HTTPException(409, "Extra-seat item is missing from subscription")

    from database import get_db_connection
    async with await get_db_connection() as conn:
        seat_row = await _fetch_one(
            conn,
            """
            SELECT tf.feature_value AS extra_seat_stripe_price
            FROM subscription_tiers st
            JOIN tier_features tf ON tf.tier_id = st.id
            WHERE st.tier_code = 'founder_workspace'
              AND tf.feature_key = 'extra_seat_stripe_price'
              AND tf.enabled = TRUE
            """,
        )
        seat_row = _stripe_mapping(seat_row) if seat_row else None
        if not seat_row or not seat_row.get("extra_seat_stripe_price"):
            raise HTTPException(409, "Extra-seat pricing is not configured")
        seat_price_id = str(seat_row["extra_seat_stripe_price"])

        seat_items = [item for item in items if _subscription_price_id(item) == seat_price_id]
        if len(seat_items) != 1:
            raise HTTPException(409, "Subscription extra-seat item is ambiguous")
        base_items = [item for item in items if _subscription_price_id(item) != seat_price_id]
        if len(base_items) != 1:
            raise HTTPException(409, "Subscription tier item is ambiguous")

        base_price_id = _subscription_price_id(base_items[0])
        tier_row = await _fetch_one(
            conn,
            """
            SELECT tier_code, team_seats
            FROM subscription_tiers
            WHERE is_active = TRUE
              AND (stripe_price_monthly = $1 OR stripe_price_yearly = $1)
            """,
            base_price_id,
        )
        tier_row = _stripe_mapping(tier_row) if tier_row else None
        if not tier_row or not tier_row.get("tier_code"):
            raise HTTPException(409, "Subscription tier price is not mapped")

        try:
            extra_quantity = int(_stripe_value(seat_items[0], "quantity", 0) or 0)
            included_seats = int(tier_row.get("team_seats") or 1)
        except (TypeError, ValueError):
            raise HTTPException(409, "Subscription seat quantity is invalid") from None
        if extra_quantity < 0:
            raise HTTPException(409, "Subscription seat quantity is invalid")

        from paid_org_provisioning import provision_paid_org
        result = await provision_paid_org(
            org_id,
            tier_row["tier_code"],
            source="stripe-subscription-updated",
        )
        require_provisioning_complete(result)

        max_seats = included_seats + extra_quantity
        bare_org_id = str(org_id)[4:] if str(org_id).startswith("org_") else str(org_id)
        update_status = await conn.execute(
            "UPDATE organizations SET max_seats = $1 WHERE id::text = $2",
            max_seats,
            bare_org_id,
        )
        if str(update_status).startswith("UPDATE") and str(update_status).endswith(" 0"):
            raise HTTPException(503, "Organization seat cap could not be updated")

    result["max_seats"] = max_seats
    result["extra_seats"] = extra_quantity
    return {"status": "provisioned", "org_id": org_id, "result": result}


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """UNIFIED Stripe webhook — verify signature once, dispatch by event type.
    Point ONE Stripe endpoint at https://<host>/api/v1/webhooks/stripe with the
    events below. checkout.session.completed -> provision_paid_org (full paid-org
    provisioning incl the cloud hard cap); customer.subscription.deleted ->
    downgrade_org (re-cap the key, stop cloud spend); invoice.payment_failed ->
    log (Stripe retries; we downgrade only on final subscription.deleted).
    Identity failures and provisioning errors return non-2xx for reconciliation/retry.
    """
    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET not configured")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    payload = await request.body()
    try:
        event = _stripe_mapping(
            stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
        )
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid Stripe signature: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Invalid Stripe payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")

    etype = _stripe_value(event, "type")
    event_data = _stripe_mapping(_stripe_value(event, "data", {}) or {})
    obj = _stripe_mapping(_stripe_value(event_data, "object", {}) or {})
    from paid_org_provisioning import provision_paid_org, downgrade_org
    try:
        # Trial-code checkouts grant org_features and return early; all other
        # events continue through the canonical Stripe org-identity path below.
        try:
            from trial_codes_api import handle_trial_code_checkout
            from database.connection import get_db_pool
            trial_result = await handle_trial_code_checkout(event, await get_db_pool())
            if trial_result.get("handled"):
                return {"status": "trial_code", "result": trial_result}
        except Exception as trial_error:
            logger.error("Trial-code webhook hook failed (non-fatal): %s", trial_error)

        if etype == "checkout.session.completed":
            md = obj.get("metadata", {}) or {}
            # Suite guard: ignore checkouts that aren't ops-center's (shared account).
            if (md.get("suite") or "") != OPS_CENTER_SUITE:
                return {"status": "ignored", "reason": f"other suite ({md.get('suite')})"}
            tier = md.get("tier_name") or md.get("tier_id") or md.get("plan_code")
            email = obj.get("customer_email") or (obj.get("customer_details", {}) or {}).get("email")
            if obj.get("payment_status") != "paid":
                return {"status": "ignored", "reason": f"payment_status={obj.get('payment_status')}"}
            if not tier or not email:
                return {"status": "ignored", "reason": "missing tier/email metadata"}
            org_id = _resolve_subscription_org(obj)
            r = await provision_paid_org(org_id, tier, email=email, source="stripe")
            require_provisioning_complete(r)
            return {"status": "provisioned", "org_id": org_id, "result": r}

        if etype == "customer.subscription.updated":
            # A Team subscription has the base tier item plus an optional
            # extra-seat item.  The shared entitlement helper intentionally
            # rejects multi-item subscriptions, so handle that shape here and
            # keep its stricter single-item path for ordinary tier changes.
            subscription_items = (obj.get("items", {}) or {}).get("data", []) or []
            if len(subscription_items) > 1:
                return await _sync_subscription_with_extra_seats(obj)
            return await _sync_single_subscription_entitlements(obj)

        if etype == "customer.subscription.deleted":
            # Suite guard: only downgrade our own subscriptions (shared account).
            if ((obj.get("metadata", {}) or {}).get("suite") or "") != OPS_CENTER_SUITE:
                return {"status": "ignored", "reason": "other suite (cancel)"}
            org_id = _resolve_subscription_org(obj)
            r = await downgrade_org(org_id, source="stripe-canceled")
            require_provisioning_complete(r)
            return {"status": "downgraded", "org_id": org_id, "result": r}

        if etype == "invoice.payment_failed":
            logger.warning("Stripe payment_failed: customer=%s sub=%s (Stripe retries; downgrade on subscription.deleted)",
                           obj.get("customer"), obj.get("subscription"))
            return {"status": "noted"}

        return {"status": "ignored", "event_type": etype}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Stripe webhook dispatch failed (%s)", etype)
        raise HTTPException(503, "Stripe webhook processing failed") from None


@router.post("/stripe/checkout-completed")
async def handle_stripe_checkout_completed(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """Compatibility alias using the same verified org-pinned dispatcher."""
    return await handle_stripe_webhook(request, stripe_signature)


@router.post("/stripe/subscription-updated")
async def handle_stripe_subscription_updated(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """Compatibility alias for the same org-pinned entitlement dispatcher."""
    return await handle_stripe_webhook(request, stripe_signature)


@router.post("/lago/subscription-updated")
async def handle_lago_subscription_updated(request: Request):
    """
    Handle Lago subscription.updated webhook.
    Triggered when subscription changes in Lago.

    Note: Lago webhook signature verification would go here.
    """
    try:
        payload = await request.json()

        logger.info(f"Received Lago webhook: {payload.get('webhook_type')}")

        # Extract subscription data
        subscription_data = payload.get('subscription', {})
        external_customer_id = subscription_data.get('external_customer_id')
        plan_code = subscription_data.get('plan_code')
        status = subscription_data.get('status')

        if not external_customer_id:
            logger.warning("No external_customer_id in Lago webhook")
            return {"status": "ignored"}

        # Log the change
        logger.info(f"Lago subscription updated: org={external_customer_id}, plan={plan_code}, status={status}")

        # In production, you might sync this back to Keycloak or trigger other actions

        return {
            "status": "success",
            "org_id": external_customer_id,
            "plan_code": plan_code
        }

    except Exception as e:
        logger.error(f"Error processing Lago webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
