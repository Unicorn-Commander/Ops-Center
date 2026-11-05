"""
Webhook Handlers for Stripe and Lago Events
Handles subscription lifecycle events from payment providers
"""

from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional
import logging
import os
import stripe
from stripe_org_identity import resolve_event_org, require_provisioning_complete

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
        event = stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid Stripe signature: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Invalid Stripe payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")

    etype = event.get("type")
    obj = event.get("data", {}).get("object", {})
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
            org_id = resolve_event_org(obj)
            r = await provision_paid_org(org_id, tier, email=email, source="stripe")
            require_provisioning_complete(r)
            return {"status": "provisioned", "org_id": org_id, "result": r}

        if etype == "customer.subscription.updated":
            from stripe_subscription_entitlements import sync_subscription_entitlements
            return await sync_subscription_entitlements(obj, OPS_CENTER_SUITE)

        if etype == "customer.subscription.deleted":
            # Suite guard: only downgrade our own subscriptions (shared account).
            if ((obj.get("metadata", {}) or {}).get("suite") or "") != OPS_CENTER_SUITE:
                return {"status": "ignored", "reason": "other suite (cancel)"}
            org_id = resolve_event_org(obj)
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
