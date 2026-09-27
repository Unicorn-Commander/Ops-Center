"""
Stripe API Endpoints for UC-1 Pro Billing
Provides REST API for payment processing and subscription management
"""

from fastapi import APIRouter, HTTPException, Request, Depends, Header
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import logging
from datetime import datetime
import os
import stripe
import asyncpg

from billing_org_identity import resolve_billing_org
from stripe_org_identity import validate_subscription_org
from stripe_integration import stripe_integration
from keycloak_integration import get_user_by_email, get_user_tier_info
from subscription_manager import subscription_manager
from redis_session import redis_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


# Request/Response Models
class CheckoutSessionRequest(BaseModel):
    tier_id: str  # trial, starter, professional, enterprise
    billing_cycle: str = "monthly"  # monthly or yearly


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: Optional[str] = None


class PortalSessionResponse(BaseModel):
    portal_url: str


class PaymentMethod(BaseModel):
    id: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int


class SubscriptionInfo(BaseModel):
    id: str
    status: str
    current_period_end: str
    cancel_at_period_end: bool
    tier_name: str
    billing_cycle: str
    amount: float


class SubscriptionStatusResponse(BaseModel):
    has_subscription: bool
    current_tier: str
    status: str
    subscriptions: List[SubscriptionInfo]


class CancelSubscriptionRequest(BaseModel):
    subscription_id: str
    at_period_end: bool = True


class UpgradeSubscriptionRequest(BaseModel):
    new_tier_id: str
    billing_cycle: str = "monthly"


class WebhookResponse(BaseModel):
    status: str
    message: Optional[str] = None


# Dependency to get current user from session/token
async def get_current_user_email(request: Request) -> str:
    """
    Extract user email from Redis-backed session
    Used by billing endpoints to identify the authenticated user
    """
    # Get session token from cookie
    session_token = request.cookies.get("session_token")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Get session data from Redis
    session_data = redis_session_manager.get(session_token)

    if not session_data:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    # Get user info from session (session structure has "user" object)
    user = session_data.get("user", {})

    if not user:
        raise HTTPException(status_code=401, detail="User not found in session")

    # Get user email from user object
    user_email = user.get("email") or user.get("preferred_username")

    if not user_email:
        raise HTTPException(status_code=401, detail="User email not found in session")

    return user_email


async def _resolve_request_billing_org(request: Request, *, require_write: bool) -> str:
    token = request.cookies.get("session_token")
    session = redis_session_manager.get(token) if token else None
    if not session or not session.get("user"):
        raise HTTPException(status_code=401, detail="Invalid session")
    return await resolve_billing_org(
        session["user"], session, getattr(request.app.state, "db_pool", None),
        require_write=require_write
    )


async def get_current_billing_org(request: Request) -> str:
    return await _resolve_request_billing_org(request, require_write=False)


async def get_writable_billing_org(request: Request) -> str:
    """Require billing authority within the selected active organization."""
    return await _resolve_request_billing_org(request, require_write=True)


@router.post("/subscriptions/checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    request: CheckoutSessionRequest,
    user_email: str = Depends(get_current_user_email),
    org_id: str = Depends(get_writable_billing_org)
):
    """
    Create a Stripe Checkout session for subscription purchase

    Args:
        request: Checkout session request with tier and billing cycle
        user_email: Current user's email (from auth dependency)

    Returns:
        Checkout session URL
    """
    try:
        # Validate billing cycle
        if request.billing_cycle not in ["monthly", "yearly"]:
            raise HTTPException(status_code=400, detail="Invalid billing cycle")

        conn = await asyncpg.connect(
            host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "unicorn"),
            password=os.getenv("POSTGRES_PASSWORD", "unicorn"),
            database=os.getenv("POSTGRES_DB", "unicorn_db"),
        )
        try:
            plan = await conn.fetchrow(
                """
                SELECT tier_code, tier_name, price_monthly, price_yearly,
                       stripe_price_monthly, stripe_price_yearly
                FROM subscription_tiers
                WHERE tier_code = $1 AND is_active = TRUE
                """,
                request.tier_id,
            )
        finally:
            await conn.close()

        if not plan:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {request.tier_id}")
        if plan["price_monthly"] == 0:
            raise HTTPException(status_code=400, detail="The free tier does not require checkout")

        # Get or create Stripe customer
        customer = await stripe_integration.get_customer_for_org(org_id, allow_create=True)

        if not customer:
            # Get user info from Keycloak
            kc_user = await get_user_by_email(user_email)
            name = f"{kc_user.get('firstName', '')} {kc_user.get('lastName', '')}".strip() if kc_user else None

            customer = await stripe_integration.create_customer(
                email=user_email,
                name=name,
                metadata={
                    "keycloak_id": kc_user.get('id') if kc_user else "",
                    "source": "ops_center",
                    "org_id": org_id
                }
            )

            if not customer:
                raise HTTPException(status_code=500, detail="Failed to create customer")

        # Get the appropriate price ID based on billing cycle
        if request.billing_cycle == "yearly":
            price_id = plan["stripe_price_yearly"]
            if not price_id:
                raise HTTPException(status_code=409, detail="Annual billing is not available for this tier")
        else:
            price_id = plan["stripe_price_monthly"]
            if not price_id:
                raise HTTPException(status_code=409, detail="Checkout is not available for this tier yet")

        # Create checkout session
        checkout_url = await stripe_integration.create_checkout_session(
            customer_id=customer['id'],
            price_id=price_id,
            customer_email=user_email,
            tier_name=request.tier_id,
            billing_cycle=request.billing_cycle,
            org_id=org_id
        )

        if not checkout_url:
            raise HTTPException(status_code=500, detail="Failed to create checkout session")

        logger.info(f"Created checkout session for {user_email}, tier: {request.tier_id}")

        return CheckoutSessionResponse(checkout_url=checkout_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscriptions/checkout/{session_id}")
async def get_checkout_session_status(
    session_id: str,
    user_email: str = Depends(get_current_user_email)
):
    """What did this checkout session actually buy?

    Backs the /checkout/success page. Stripe's redirect is NOT proof of payment and
    provisioning is driven by the webhook, so the page needs a server-side read of
    the real session plus the org's CURRENT tier — that pair is what lets the page
    say "you're on Suite - BYOK now" instead of guessing, and lets it keep polling
    honestly while the webhook is still in flight.

    Scoped to the caller: a session that belongs to a different customer is a 404,
    so a guessed cs_live_ id leaks nothing.
    """
    try:
        session = stripe.checkout.Session.retrieve(session_id, expand=["line_items"])
    except Exception as e:
        logger.warning(f"checkout session lookup failed ({session_id}): {e}")
        raise HTTPException(status_code=404, detail="Checkout session not found")

    md = session.get("metadata") or {}
    session_email = (
        session.get("customer_email")
        or (session.get("customer_details") or {}).get("email")
        or md.get("user_email")
    )
    if not session_email or session_email.lower() != user_email.lower():
        raise HTTPException(status_code=404, detail="Checkout session not found")

    tier_code = md.get("tier_id") or md.get("tier_name")
    tier_name = tier_code
    current_tier = None
    try:
        conn = await asyncpg.connect(
            host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "unicorn"),
            password=os.getenv("POSTGRES_PASSWORD", "unicorn"),
            database=os.getenv("POSTGRES_DB", "unicorn_db"),
        )
        try:
            if tier_code:
                row = await conn.fetchrow(
                    "SELECT tier_name FROM subscription_tiers WHERE tier_code = $1", tier_code
                )
                if row:
                    tier_name = row["tier_name"]
            # Same resolver the Stripe webhook provisions through, so this page can
            # never disagree with what provisioning actually targeted.
            from webhooks import _resolve_org_by_email
            org_id = await _resolve_org_by_email(user_email)
            if org_id:
                bare = org_id[4:] if str(org_id).startswith("org_") else str(org_id)
                org_row = await conn.fetchrow(
                    "SELECT plan_tier FROM organizations WHERE id::text = $1", bare
                )
                if org_row:
                    current_tier = org_row["plan_tier"]
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"checkout status tier lookup failed: {e}")

    return {
        "session_id": session.get("id"),
        "payment_status": session.get("payment_status"),
        "status": session.get("status"),
        "tier_code": tier_code,
        "tier_name": tier_name,
        "billing_cycle": md.get("billing_cycle") or "monthly",
        "amount_total": session.get("amount_total"),
        "currency": session.get("currency"),
        # The org's tier right now. Equal to tier_code once the webhook has landed;
        # the page polls on this rather than assuming the redirect means provisioned.
        "current_tier": current_tier,
        "provisioned": bool(tier_code and current_tier == tier_code),
    }


@router.post("/portal/create", response_model=PortalSessionResponse)
async def create_portal_session(
    user_email: str = Depends(get_current_user_email),
    org_id: str = Depends(get_writable_billing_org)
):
    """
    Create a Stripe Customer Portal session for subscription management

    Args:
        user_email: Current user's email (from auth dependency)

    Returns:
        Customer portal URL
    """
    try:
        # Get Stripe customer
        customer = await stripe_integration.get_customer_for_org(org_id)

        if not customer:
            raise HTTPException(
                status_code=404,
                detail="No Stripe customer found. Please subscribe first."
            )

        # Create portal session
        portal_url = await stripe_integration.create_customer_portal_session(customer['id'])

        if not portal_url:
            raise HTTPException(status_code=500, detail="Failed to create portal session")

        logger.info(f"Created portal session for {user_email}")

        return PortalSessionResponse(portal_url=portal_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating portal session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/payment-methods", response_model=List[PaymentMethod])
async def get_payment_methods(
    user_email: str = Depends(get_current_user_email),
    org_id: str = Depends(get_current_billing_org)
):
    """
    Get user's saved payment methods

    Args:
        user_email: Current user's email (from auth dependency)

    Returns:
        List of payment methods
    """
    try:
        # Get Stripe customer
        customer = await stripe_integration.get_customer_for_org(org_id)

        if not customer:
            return []

        # Get payment methods
        methods = await stripe_integration.get_customer_payment_methods(customer['id'])

        return [
            PaymentMethod(
                id=pm['id'],
                brand=pm['card']['brand'],
                last4=pm['card']['last4'],
                exp_month=pm['card']['exp_month'],
                exp_year=pm['card']['exp_year']
            )
            for pm in methods
        ]

    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching payment methods")
        raise HTTPException(503, "Payment methods unavailable") from None


@router.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    user_email: str = Depends(get_current_user_email),
    org_id: str = Depends(get_current_billing_org)
):
    """
    Get user's current subscription status

    Args:
        user_email: Current user's email (from auth dependency)

    Returns:
        Subscription status information
    """
    try:
        # Status belongs to the selected org, not an email-wide Keycloak tier.

        # Get Stripe customer
        customer = await stripe_integration.get_customer_for_org(org_id)

        if not customer:
            return SubscriptionStatusResponse(
                has_subscription=False,
                current_tier='trial',
                status='none',
                subscriptions=[]
            )

        # Get subscriptions
        subscriptions = await stripe_integration.get_customer_subscriptions(customer['id'])
        for subscription in subscriptions:
            validate_subscription_org(subscription, org_id, customer['id'])

        subscription_list = []
        for sub in subscriptions:
            tier_name = sub.get('metadata', {}).get('tier_name', 'unknown')
            billing_cycle = sub.get('metadata', {}).get('billing_cycle', 'monthly')

            subscription_list.append(SubscriptionInfo(
                id=sub['id'],
                status=sub['status'],
                current_period_end=datetime.fromtimestamp(sub['current_period_end']).isoformat(),
                cancel_at_period_end=sub.get('cancel_at_period_end', False),
                tier_name=tier_name,
                billing_cycle=billing_cycle,
                amount=sub['items']['data'][0]['price']['unit_amount'] / 100  # Convert cents to dollars
            ))

        active = [sub for sub in subscription_list if sub.status in {"active", "trialing"}]
        if len(active) > 1:
            raise HTTPException(409, "Multiple active subscriptions; reconciliation required")
        return SubscriptionStatusResponse(
            has_subscription=len(subscription_list) > 0,
            current_tier=active[0].tier_name if active else 'trial',
            status=active[0].status if active else 'none',
            subscriptions=subscription_list
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching subscription status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subscription/cancel")
async def cancel_subscription(
    request: CancelSubscriptionRequest,
    user_email: str = Depends(get_current_user_email),
    org_id: str = Depends(get_writable_billing_org)
):
    """
    Cancel a subscription

    Args:
        request: Cancellation request
        user_email: Current user's email (from auth dependency)

    Returns:
        Success message
    """
    try:
        # Verify subscription belongs to user
        customer = await stripe_integration.get_customer_for_org(org_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        subscriptions = await stripe_integration.get_customer_subscriptions(customer['id'])
        for subscription in subscriptions:
            validate_subscription_org(subscription, org_id, customer['id'])
        subscription_ids = [sub['id'] for sub in subscriptions]

        if request.subscription_id not in subscription_ids:
            raise HTTPException(
                status_code=403,
                detail="Subscription does not belong to this user"
            )

        # Cancel subscription
        success = await stripe_integration.cancel_subscription(
            subscription_id=request.subscription_id,
            at_period_end=request.at_period_end
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to cancel subscription")

        logger.info(f"Canceled subscription {request.subscription_id} for {user_email}")

        return {
            "status": "success",
            "message": "Subscription canceled" if not request.at_period_end else "Subscription will cancel at period end"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error canceling subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subscription/upgrade")
async def upgrade_subscription(
    request: UpgradeSubscriptionRequest,
    user_email: str = Depends(get_current_user_email),
    org_id: str = Depends(get_writable_billing_org)
):
    """
    Upgrade or downgrade subscription tier

    Args:
        request: Upgrade request with new tier
        user_email: Current user's email (from auth dependency)

    Returns:
        Success message
    """
    try:
        # Validate new tier
        plan = subscription_manager.get_plan(request.new_tier_id)
        if not plan:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {request.new_tier_id}")

        # Get customer and current subscription
        customer = await stripe_integration.get_customer_for_org(org_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        subscriptions = await stripe_integration.get_customer_subscriptions(customer['id'])
        for subscription in subscriptions:
            validate_subscription_org(subscription, org_id, customer['id'])
        active_subs = [sub for sub in subscriptions if sub['status'] == 'active']

        if not active_subs:
            raise HTTPException(
                status_code=404,
                detail="No active subscription found. Please create a new subscription."
            )

        if len(active_subs) != 1:
            raise HTTPException(409, "Multiple active subscriptions; reconciliation required")

        # Get new price ID based on billing cycle
        if request.billing_cycle == "yearly":
            new_price_id = plan.stripe_annual_price_id
            if not new_price_id:
                raise HTTPException(
                    status_code=500,
                    detail=f"Annual price ID not configured for tier: {request.new_tier_id}"
                )
        else:
            new_price_id = plan.stripe_price_id
            if not new_price_id:
                raise HTTPException(
                    status_code=500,
                    detail=f"Monthly price ID not configured for tier: {request.new_tier_id}"
                )

        # Update subscription
        subscription_id = active_subs[0]['id']
        success = await stripe_integration.update_subscription(
            subscription_id=subscription_id,
            new_price_id=new_price_id
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update subscription")

        logger.info(f"Updated subscription for {user_email} to tier: {request.new_tier_id}")

        return {
            "status": "success",
            "message": f"Subscription upgraded to {plan.display_name}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error upgrading subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """Legacy callable shares the canonical signature-verified dispatcher."""
    from webhooks import handle_stripe_webhook
    result = await handle_stripe_webhook(request, stripe_signature)
    return WebhookResponse(status=result["status"])


async def stripe_checkout_webhook(request: Request):
    """Legacy callable delegates to the canonical signature-verified route."""
    from webhooks import handle_stripe_webhook
    return await handle_stripe_webhook(request, request.headers.get("stripe-signature"))


async def create_lago_customer_if_not_exists(user_email: str, user_id: str):
    """Create Lago customer if it doesn't exist"""
    import httpx

    lago_api_url = os.environ.get("LAGO_API_URL", "http://unicorn-lago-api:3000")
    lago_api_key = os.environ.get("LAGO_API_KEY")

    if not lago_api_key:
        raise Exception("LAGO_API_KEY not configured")

    # Check if customer exists
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{lago_api_url}/api/v1/customers/{user_email}",
                headers={"Authorization": f"Bearer {lago_api_key}"},
                timeout=10.0
            )
            if response.status_code == 200:
                logger.info(f"Lago customer already exists: {user_email}")
                return response.json()['customer']
    except Exception as e:
        logger.debug(f"Customer lookup failed (expected if new): {e}")

    # Create customer
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{lago_api_url}/api/v1/customers",
            headers={
                "Authorization": f"Bearer {lago_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "customer": {
                    "external_id": user_email,
                    "name": user_email,
                    "email": user_email,
                    "metadata": {
                        "keycloak_id": user_id
                    }
                }
            },
            timeout=10.0
        )

        if response.status_code in [200, 201]:
            logger.info(f"Created Lago customer: {user_email}")
            return response.json()['customer']
        else:
            logger.error(f"Failed to create Lago customer: {response.status_code} - {response.text}")
            raise Exception(f"Failed to create customer: {response.text}")


async def create_lago_subscription(customer_id: str, plan_code: str, billing_cycle: str):
    """Create Lago subscription"""
    import httpx

    lago_api_url = os.environ.get("LAGO_API_URL", "http://unicorn-lago-api:3000")
    lago_api_key = os.environ.get("LAGO_API_KEY")

    if not lago_api_key:
        raise Exception("LAGO_API_KEY not configured")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{lago_api_url}/api/v1/subscriptions",
            headers={
                "Authorization": f"Bearer {lago_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "subscription": {
                    "external_customer_id": customer_id,
                    "plan_code": plan_code,
                    "billing_time": "calendar"
                }
            },
            timeout=10.0
        )

        if response.status_code in [200, 201]:
            logger.info(f"Created Lago subscription for {customer_id}: {plan_code}")
            return response.json()['subscription']
        else:
            logger.error(f"Failed to create Lago subscription: {response.status_code} - {response.text}")
            raise Exception(f"Failed to create subscription: {response.text}")
