"""
Stripe API Endpoints for UC-1 Pro Billing
Provides REST API for payment processing and subscription management
"""

from fastapi import APIRouter, HTTPException, Request, Depends, Header
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import logging
from datetime import datetime

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


@router.post("/subscriptions/checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    request: CheckoutSessionRequest,
    user_email: str = Depends(get_current_user_email)
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
        # Validate tier
        plan = subscription_manager.get_plan(request.tier_id)
        if not plan:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {request.tier_id}")

        # Validate billing cycle
        if request.billing_cycle not in ["monthly", "yearly"]:
            raise HTTPException(status_code=400, detail="Invalid billing cycle")

        # Get or create Stripe customer
        customer = await stripe_integration.get_customer_by_email(user_email)

        if not customer:
            # Get user info from Keycloak
            kc_user = await get_user_by_email(user_email)
            name = f"{kc_user.get('firstName', '')} {kc_user.get('lastName', '')}".strip() if kc_user else None

            customer = await stripe_integration.create_customer(
                email=user_email,
                name=name,
                metadata={
                    "keycloak_id": kc_user.get('id') if kc_user else "",
                    "source": "ops_center"
                }
            )

            if not customer:
                raise HTTPException(status_code=500, detail="Failed to create customer")

        # Get the appropriate price ID
        # These should be set by setup_stripe_products.py
        price_id = plan.stripe_price_id

        if not price_id:
            raise HTTPException(
                status_code=500,
                detail=f"Stripe price ID not configured for tier: {request.tier_id}"
            )

        # Create checkout session
        checkout_url = await stripe_integration.create_checkout_session(
            customer_id=customer['id'],
            price_id=price_id,
            customer_email=user_email,
            tier_name=request.tier_id,
            billing_cycle=request.billing_cycle
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


@router.post("/portal/create", response_model=PortalSessionResponse)
async def create_portal_session(
    user_email: str = Depends(get_current_user_email)
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
        customer = await stripe_integration.get_customer_by_email(user_email)

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
    user_email: str = Depends(get_current_user_email)
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
        customer = await stripe_integration.get_customer_by_email(user_email)

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

    except Exception as e:
        logger.error(f"Error fetching payment methods: {e}")
        return []


@router.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    user_email: str = Depends(get_current_user_email)
):
    """
    Get user's current subscription status

    Args:
        user_email: Current user's email (from auth dependency)

    Returns:
        Subscription status information
    """
    try:
        # Get tier info from Keycloak
        tier_info = await get_user_tier_info(user_email)

        # Get Stripe customer
        customer = await stripe_integration.get_customer_by_email(user_email)

        if not customer:
            return SubscriptionStatusResponse(
                has_subscription=False,
                current_tier=tier_info.get('subscription_tier', 'trial'),
                status=tier_info.get('subscription_status', 'active'),
                subscriptions=[]
            )

        # Get subscriptions
        subscriptions = await stripe_integration.get_customer_subscriptions(customer['id'])

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

        return SubscriptionStatusResponse(
            has_subscription=len(subscription_list) > 0,
            current_tier=tier_info.get('subscription_tier', 'trial'),
            status=tier_info.get('subscription_status', 'active'),
            subscriptions=subscription_list
        )

    except Exception as e:
        logger.error(f"Error fetching subscription status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subscription/cancel")
async def cancel_subscription(
    request: CancelSubscriptionRequest,
    user_email: str = Depends(get_current_user_email)
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
        customer = await stripe_integration.get_customer_by_email(user_email)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        subscriptions = await stripe_integration.get_customer_subscriptions(customer['id'])
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
    user_email: str = Depends(get_current_user_email)
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
        customer = await stripe_integration.get_customer_by_email(user_email)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        subscriptions = await stripe_integration.get_customer_subscriptions(customer['id'])
        active_subs = [sub for sub in subscriptions if sub['status'] == 'active']

        if not active_subs:
            raise HTTPException(
                status_code=404,
                detail="No active subscription found. Please create a new subscription."
            )

        # Get new price ID
        new_price_id = plan.stripe_price_id
        if not new_price_id:
            raise HTTPException(
                status_code=500,
                detail=f"Price ID not configured for tier: {request.new_tier_id}"
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


@router.post("/webhooks/stripe", response_model=WebhookResponse)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature")
):
    """
    Handle Stripe webhook events

    This endpoint is called by Stripe to notify about subscription events.
    It's exempt from CSRF protection.

    Args:
        request: FastAPI request with webhook payload
        stripe_signature: Stripe signature header for verification

    Returns:
        Webhook processing result
    """
    try:
        # Get raw body
        payload = await request.body()

        if not stripe_signature:
            raise HTTPException(status_code=400, detail="Missing Stripe signature")

        # Process webhook event
        result = await stripe_integration.process_webhook_event(
            payload=payload,
            signature=stripe_signature
        )

        if result.get('status') == 'error':
            raise HTTPException(status_code=400, detail=result.get('message', 'Webhook processing failed'))

        logger.info(f"Processed webhook: {result}")

        return WebhookResponse(
            status=result.get('status', 'success'),
            message=result.get('message')
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
