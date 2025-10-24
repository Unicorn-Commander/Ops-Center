"""
Subscription Management API Endpoints
Integrates with Lago for billing and subscription management
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Dict, Optional
from pydantic import BaseModel
import httpx
import logging
import os

from subscription_manager import (
    subscription_manager,
    SubscriptionPlan,
    ServiceAccessConfig,
    ServiceType,
    PermissionLevel
)

# Import Lago integration functions
from lago_integration import (
    get_customer,
    get_subscription,
    create_subscription,
    terminate_subscription,
    get_or_create_customer,
    get_current_usage,
    get_invoices
)

# Email notification service (Epic 2.3)
from email_notifications import EmailNotificationService
email_service = EmailNotificationService()

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscriptions"])

# Request/Response models
class PlanCreateRequest(BaseModel):
    plan: SubscriptionPlan

class PlanUpdateRequest(BaseModel):
    updates: Dict

class UserAccessResponse(BaseModel):
    services: List[ServiceAccessConfig]
    plan: Optional[SubscriptionPlan]
    usage: Dict

# Helper function to get current user from session
async def get_current_user(request: Request):
    """Get current user data from session"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Get sessions from app state
    sessions = getattr(request.app.state, "sessions", {})
    session_data = sessions.get(session_token)

    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")

    user = session_data.get("user", {})
    if not user:
        raise HTTPException(status_code=401, detail="User not found in session")

    return user

# Helper to get org_id from user session
async def get_user_org_id(request: Request) -> str:
    """Get organization ID from user session for Lago billing"""
    user = await get_current_user(request)

    # Get org_id - this is the customer identifier in Lago
    org_id = user.get("org_id")
    if not org_id:
        # Fallback: create org_id from user email
        email = user.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="User has no org_id or email")

        # Generate org_id from email (for single-user orgs)
        org_id = f"org_{email.split('@')[0]}_{user.get('id', 'unknown')}"
        logger.warning(f"No org_id found for user {email}, using generated: {org_id}")

    return org_id

async def require_admin(request: Request):
    """Require admin role"""
    user = await get_current_user(request)
    if not user.get("is_admin") and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# Public endpoints (anyone can view plans)
@router.get("/plans")
async def get_plans():
    """Get all active subscription plans"""
    plans = subscription_manager.get_all_plans()
    return {"plans": [plan.dict() for plan in plans]}

@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str):
    """Get specific plan details"""
    plan = subscription_manager.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan.dict()

# User endpoints (authenticated users)
@router.get("/my-access")
async def get_my_access(request: Request):
    """Get services accessible to current user"""
    user = await get_current_user(request)

    # Get user's plan and role
    user_plan = user.get("subscription_tier", "trial")
    user_role = user.get("role", "user")

    # Get accessible services
    services = subscription_manager.get_user_accessible_services(user_plan, user_role)

    # Get plan details
    plan = subscription_manager.get_plan(user_plan)

    # TODO: Get usage from Lago
    usage = {
        "api_calls_used": 0,
        "api_calls_limit": plan.api_calls_limit if plan else 0,
        "period_start": None,
        "period_end": None
    }

    return {
        "services": [svc.dict() for svc in services],
        "plan": plan.dict() if plan else None,
        "usage": usage,
        "user": {
            "role": user_role,
            "subscription_tier": user_plan,
            "is_admin": user.get("is_admin", False)
        }
    }

@router.post("/check-access/{service}")
async def check_service_access(service: ServiceType, request: Request):
    """Check if user has access to specific service"""
    user = await get_current_user(request)

    user_plan = user.get("subscription_tier", "trial")
    user_role = user.get("role", "user")

    has_access = subscription_manager.check_service_access(service, user_plan, user_role)

    if not has_access:
        # Get upgrade URL
        plan = subscription_manager.get_plan(user_plan)
        return {
            "has_access": False,
            "current_plan": user_plan,
            "upgrade_required": True,
            "upgrade_url": "/billing/upgrade",
            "message": f"This service requires a higher subscription tier"
        }

    return {
        "has_access": True,
        "current_plan": user_plan
    }

# Admin endpoints (admin only)
@router.post("/plans", dependencies=[Depends(require_admin)])
async def create_plan(plan_request: PlanCreateRequest, request: Request):
    """Create new subscription plan (admin only)"""
    try:
        plan = subscription_manager.create_plan(plan_request.plan)
        return {"success": True, "plan": plan.dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/plans/{plan_id}", dependencies=[Depends(require_admin)])
async def update_plan(plan_id: str, update_request: PlanUpdateRequest, request: Request):
    """Update subscription plan (admin only)"""
    plan = subscription_manager.update_plan(plan_id, update_request.updates)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"success": True, "plan": plan.dict()}

@router.delete("/plans/{plan_id}", dependencies=[Depends(require_admin)])
async def delete_plan(plan_id: str, request: Request):
    """Delete (deactivate) subscription plan (admin only)"""
    success = subscription_manager.delete_plan(plan_id)
    if not success:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"success": True, "message": f"Plan {plan_id} deactivated"}

@router.get("/services")
async def get_all_services():
    """Get all available services (for admin reference)"""
    return {"services": [svc.dict() for svc in subscription_manager.service_access]}

@router.get("/admin/user-access/{user_id}", dependencies=[Depends(require_admin)])
async def get_user_access_admin(user_id: str, request: Request):
    """Get service access for specific user (admin only)"""
    # TODO: Fetch user details from Authentik
    # For now, return example
    return {
        "user_id": user_id,
        "message": "User access lookup - to be implemented with Authentik integration"
    }

# ============================================================================
# NEW ENDPOINTS: Lago-integrated subscription management
# ============================================================================

@router.get("/current")
async def get_current_subscription(request: Request):
    """
    Get current subscription details from Lago.
    Returns subscription status, plan details, and next billing date.
    """
    user = await get_current_user(request)
    org_id = await get_user_org_id(request)

    logger.info(f"Fetching subscription for org_id: {org_id}")

    try:
        # Get subscription from Lago
        subscription = await get_subscription(org_id)

        if not subscription:
            # No active subscription - check user's tier from Keycloak
            user_tier = user.get("subscription_tier", "trial")
            plan = subscription_manager.get_plan(user_tier)

            return {
                "has_subscription": False,
                "tier": user_tier,
                "price": plan.price_monthly if plan else 0,
                "status": "none",
                "message": "No active Lago subscription found"
            }

        # Extract subscription details
        plan_code = subscription.get("plan_code", "")
        status = subscription.get("status", "unknown")

        # Map plan_code to tier (e.g., "professional_monthly" -> "professional")
        tier = plan_code.split("_")[0] if "_" in plan_code else plan_code

        # Get plan details from subscription_manager
        plan = subscription_manager.get_plan(tier)

        return {
            "has_subscription": True,
            "tier": tier,
            "plan_code": plan_code,
            "price": plan.price_monthly if plan else 0,
            "status": status,
            "next_billing_date": subscription.get("subscription_at"),
            "lago_id": subscription.get("lago_id"),
            "external_id": subscription.get("external_id"),
            "billing_time": subscription.get("billing_time"),
            "plan_name": plan.display_name if plan else tier.title()
        }

    except Exception as e:
        logger.error(f"Error fetching subscription: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch subscription: {str(e)}")


@router.post("/upgrade")
async def upgrade_subscription(request: Request):
    """
    Upgrade subscription to a higher tier.
    Creates Stripe checkout session and redirects user to payment.
    """
    user = await get_current_user(request)
    org_id = await get_user_org_id(request)

    # Get request body
    body = await request.json()
    target_tier = body.get("target_tier")

    if not target_tier:
        raise HTTPException(status_code=400, detail="target_tier required")

    logger.info(f"Upgrading org {org_id} to tier: {target_tier}")

    try:
        # Get target plan details
        target_plan = subscription_manager.get_plan(target_tier)
        if not target_plan:
            raise HTTPException(status_code=404, detail=f"Plan {target_tier} not found")

        # Check if user is actually upgrading (not downgrading)
        current_subscription = await get_subscription(org_id)
        if current_subscription:
            current_tier = current_subscription.get("plan_code", "").split("_")[0]
            from subscription_api import getTierLevel
            if getTierLevel(target_tier) <= getTierLevel(current_tier):
                raise HTTPException(status_code=400, detail="Use /change endpoint for downgrades")

        # Create Stripe checkout session
        stripe_key = os.getenv("STRIPE_SECRET_KEY")
        if not stripe_key:
            raise HTTPException(status_code=500, detail="Stripe not configured")

        # TODO: Create Stripe checkout session
        # For now, create subscription directly in Lago
        lago_plan_code = f"{target_tier}_monthly"

        # Ensure customer exists in Lago
        await get_or_create_customer(
            org_id=org_id,
            org_name=user.get("org_name", f"{user.get('email')} Org"),
            email=user.get("email"),
            user_id=user.get("id")
        )

        # Create subscription in Lago
        new_subscription = await create_subscription(org_id, lago_plan_code)

        logger.info(f"Created subscription {new_subscription.get('lago_id')} for org {org_id}")

        # Send tier upgrade email (don't fail if email fails)
        try:
            old_tier = current_subscription.get("plan_code", "").split("_")[0] if current_subscription else "trial"
            await email_service.send_tier_upgrade_notification(
                user_id=user.get("id"),
                old_tier=old_tier,
                new_tier=target_tier
            )
            logger.info(f"Tier upgrade email sent to user {user.get('id')}")
        except Exception as e:
            logger.error(f"Failed to send tier upgrade email: {e}")

        return {
            "success": True,
            "subscription": new_subscription,
            "message": f"Upgraded to {target_tier}",
            # TODO: Add checkout_url when Stripe is integrated
        }

    except Exception as e:
        logger.error(f"Error upgrading subscription: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upgrade: {str(e)}")


@router.post("/change")
async def change_subscription(request: Request):
    """
    Change subscription to a different tier (usually downgrade).
    Takes effect at end of current billing period.
    """
    user = await get_current_user(request)
    org_id = await get_user_org_id(request)

    body = await request.json()
    target_tier = body.get("target_tier")

    if not target_tier:
        raise HTTPException(status_code=400, detail="target_tier required")

    logger.info(f"Changing subscription for org {org_id} to tier: {target_tier}")

    try:
        # Get current subscription
        current_subscription = await get_subscription(org_id)
        if not current_subscription:
            raise HTTPException(status_code=404, detail="No active subscription found")

        # Get target plan
        target_plan = subscription_manager.get_plan(target_tier)
        if not target_plan:
            raise HTTPException(status_code=404, detail=f"Plan {target_tier} not found")

        # For downgrades, schedule change at end of period
        # For upgrades, apply immediately
        lago_plan_code = f"{target_tier}_monthly"

        # TODO: Use Lago's subscription update API instead of terminate+create
        # For now, terminate old and create new
        current_id = current_subscription.get("lago_id")
        success = await terminate_subscription(org_id, current_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to terminate old subscription")

        # Create new subscription
        new_subscription = await create_subscription(org_id, lago_plan_code)

        # Send tier change email (don't fail if email fails)
        try:
            old_tier = current_subscription.get("plan_code", "").split("_")[0]
            await email_service.send_tier_upgrade_notification(
                user_id=user.get("id"),
                old_tier=old_tier,
                new_tier=target_tier
            )
            logger.info(f"Tier change email sent to user {user.get('id')}")
        except Exception as e:
            logger.error(f"Failed to send tier change email: {e}")

        return {
            "success": True,
            "subscription": new_subscription,
            "message": f"Changed subscription to {target_tier}",
            "effective_date": "immediately"  # TODO: Support end-of-period changes
        }

    except Exception as e:
        logger.error(f"Error changing subscription: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to change subscription: {str(e)}")


@router.post("/cancel")
async def cancel_subscription(request: Request):
    """
    Cancel current subscription.
    Access continues until end of billing period.
    """
    user = await get_current_user(request)
    org_id = await get_user_org_id(request)

    logger.info(f"Canceling subscription for org {org_id}")

    try:
        # Get current subscription
        current_subscription = await get_subscription(org_id)
        if not current_subscription:
            raise HTTPException(status_code=404, detail="No active subscription to cancel")

        # Terminate subscription in Lago
        subscription_id = current_subscription.get("lago_id")
        success = await terminate_subscription(org_id, subscription_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to cancel subscription")

        return {
            "success": True,
            "message": "Subscription canceled successfully",
            "access_until": current_subscription.get("subscription_at"),
            "tier": current_subscription.get("plan_code", "").split("_")[0]
        }

    except Exception as e:
        logger.error(f"Error canceling subscription: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cancel subscription: {str(e)}")


# Helper function for tier comparison
def getTierLevel(tier: str) -> int:
    """Get numeric level for tier comparison"""
    levels = {"trial": 1, "starter": 2, "professional": 3, "enterprise": 4}
    return levels.get(tier, 0)
