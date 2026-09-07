"""Validate organization ownership at Stripe event and resource boundaries."""
from fastapi import HTTPException
import stripe

from billing_org_identity import lago_org_id


def customer_org(customer):
    if not customer or customer.get("deleted") or not customer.get("id"):
        raise HTTPException(409, "Stripe customer identity unavailable")
    return lago_org_id((customer.get("metadata") or {}).get("org_id"))


def resolve_event_org(obj):
    """Pin an event to its customer org and reject inconsistent event metadata.

    Only call with signature-verified events or Stripe-retrieved objects. Never
    consult a user's current selected org or email. Legacy events can use a
    uniquely org-tagged customer; untagged customers require reconciliation.
    """
    reference = obj.get("customer")
    customer_id = reference.get("id") if isinstance(reference, dict) else reference
    if not isinstance(customer_id, str) or not customer_id:
        raise HTTPException(409, "Stripe customer identity unavailable")
    customer = stripe.Customer.retrieve(customer_id)
    if customer.get("id") != customer_id:
        raise HTTPException(409, "Stripe customer identity mismatch")
    org = customer_org(customer)
    event_org = (obj.get("metadata") or {}).get("org_id")
    if event_org is not None and lago_org_id(event_org) != org:
        raise HTTPException(409, "Stripe event and customer organization mismatch")
    return org


def validate_subscription_org(subscription, org_id, customer_id):
    """Do not accept legacy/foreign subscriptions on an org-scoped customer."""
    reference = subscription.get("customer")
    actual_customer = reference.get("id") if isinstance(reference, dict) else reference
    if actual_customer != customer_id:
        raise HTTPException(409, "Subscription customer mismatch")
    if lago_org_id((subscription.get("metadata") or {}).get("org_id")) != lago_org_id(org_id):
        raise HTTPException(409, "Subscription organization mismatch")
    return subscription


def require_provisioning_complete(result):
    """Do not acknowledge partially failed provisioning as a successful event."""
    errors = ("error", "tier_error", "lago_error", "key_error")
    failed = any(result.get(key) for key in errors)
    failed = failed or any(result.get(key) is False for key in ("tier_set", "lago_sub"))
    if result.get("cloud_cap") is not None and result.get("key_capped") is False:
        failed = True
    if failed:
        raise HTTPException(503, "Organization provisioning incomplete")
