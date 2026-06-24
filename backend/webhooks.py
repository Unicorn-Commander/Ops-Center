"""Unified Stripe and Lago webhook handlers."""

import logging
import os
from typing import Optional

import stripe
from fastapi import APIRouter, Header, HTTPException, Request

from get_credential import get_credential
from keycloak_integration import get_user_by_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

STRIPE_WEBHOOK_SECRET = get_credential("STRIPE_WEBHOOK_SECRET")
stripe.api_key = get_credential("STRIPE_SECRET_KEY")
OPS_CENTER_SUITE = os.getenv("OPS_CENTER_STRIPE_SUITE", "unicorn-commander")


async def _resolve_org_by_email(email: str) -> Optional[str]:
    """Map a Stripe customer email to the org identifier used by provisioning."""
    if not email:
        return None
    try:
        user = await get_user_by_email(email)
        if not user:
            return None
        user_id = user.get("id")
        return user.get("attributes", {}).get("org_id", [f"org_{user_id}"])[0]
    except Exception as exc:
        logger.error("Org resolution failed for %s: %s", email, exc)
        return None


def _customer_email(obj: dict) -> Optional[str]:
    return (
        obj.get("customer_email")
        or (obj.get("customer_details", {}) or {}).get("email")
        or (obj.get("billing_details", {}) or {}).get("email")
    )


def _metadata(obj: dict) -> dict:
    return obj.get("metadata", {}) or {}


async def _email_from_customer(obj: dict) -> Optional[str]:
    email = _customer_email(obj)
    if email:
        return email
    customer_id = obj.get("customer")
    if not customer_id:
        return None
    try:
        customer = stripe.Customer.retrieve(customer_id)
        return customer.get("email")
    except Exception as exc:
        logger.error("Could not retrieve Stripe customer %s: %s", customer_id, exc)
        return None


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """Verify once and dispatch every Ops-Center Stripe event from one endpoint."""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(
            await request.body(), stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError as exc:
        logger.error("Invalid Stripe signature: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as exc:
        logger.error("Invalid Stripe payload: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {})
    metadata = _metadata(obj)
    if event_type == "charge.refunded" and not metadata.get("suite") and obj.get("payment_intent"):
        try:
            payment_intent = stripe.PaymentIntent.retrieve(obj["payment_intent"])
            metadata = payment_intent.get("metadata", {}) or {}
            obj["metadata"] = metadata
        except Exception as exc:
            logger.error("Could not retrieve refunded payment intent metadata: %s", exc)

    if metadata.get("suite") != OPS_CENTER_SUITE:
        return {"status": "ignored", "reason": f"other suite ({metadata.get('suite')})"}

    try:
        if metadata.get("purchase_type") == "addon":
            from stripe_webhook_handler import webhook_handler

            return await webhook_handler.handle_event(event)

        from paid_org_provisioning import downgrade_org, provision_paid_org

        if event_type == "checkout.session.completed":
            if obj.get("payment_status") != "paid":
                return {"status": "ignored", "reason": f"payment_status={obj.get('payment_status')}"}
            tier = metadata.get("tier_name") or metadata.get("tier_id") or metadata.get("plan_code")
            email = await _email_from_customer(obj)
            if not tier or not email:
                return {"status": "ignored", "reason": "missing tier/email metadata"}
            org_id = await _resolve_org_by_email(email)
            if not org_id:
                return {"status": "error", "reason": f"org not found for {email}"}
            result = await provision_paid_org(org_id, tier, email=email, source="stripe")
            return {"status": "provisioned", "org_id": org_id, "result": result}

        if event_type == "customer.subscription.deleted":
            email = await _email_from_customer(obj)
            org_id = await _resolve_org_by_email(email)
            if not org_id:
                return {"status": "ignored", "reason": "org not found (cancel)"}
            result = await downgrade_org(org_id, source="stripe-canceled")
            return {"status": "downgraded", "org_id": org_id, "result": result}

        if event_type == "invoice.payment_failed":
            logger.warning(
                "Stripe payment failed: customer=%s subscription=%s",
                obj.get("customer"),
                obj.get("subscription"),
            )
            return {"status": "noted"}

        return {"status": "ignored", "event_type": event_type}
    except Exception as exc:
        logger.exception("Stripe webhook dispatch failed for %s", event_type)
        return {"status": "error", "detail": str(exc)}


@router.post("/lago/subscription-updated")
async def handle_lago_subscription_updated(request: Request):
    """Record Lago subscription updates; Stripe remains the provisioning authority."""
    payload = await request.json()
    subscription = payload.get("subscription", {})
    logger.info(
        "Lago subscription updated: org=%s plan=%s status=%s",
        subscription.get("external_customer_id"),
        subscription.get("plan_code"),
        subscription.get("status"),
    )
    return {
        "status": "success",
        "org_id": subscription.get("external_customer_id"),
        "plan_code": subscription.get("plan_code"),
    }
