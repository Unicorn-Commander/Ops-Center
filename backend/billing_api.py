"""
Billing API Endpoints
Provides invoice history, billing cycle info, and payment management
"""

from fastapi import APIRouter, HTTPException, Request
from typing import List, Dict, Optional
from datetime import datetime
import logging
import os
import sys

# Import Lago integration
from lago_integration import (
    get_invoices,
    get_invoices_by_email,
    get_subscription,
    get_subscription_by_email,
    get_customer
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["billing-lago"])

# Hardcoded subscription plans (from Lago configuration)
SUBSCRIPTION_PLANS = [
    {
        "plan_id": "bbbba413-45de-468d-b03e-f23713684354",
        "plan_code": "trial",
        "name": "Trial",
        "description": "7-day trial with basic features",
        "price_monthly": 1.00,
        "price_yearly": None,
        "interval": "weekly",
        "features": ["100 API calls/day", "Open-WebUI access", "Basic AI models", "Community support"],
        "api_calls_limit": 700,
        "is_trial": True
    },
    {
        "plan_id": "02a9058d-e0f6-4e09-9c39-a775d57676d1",
        "plan_code": "starter",
        "name": "Starter",
        "description": "Perfect for individuals and small projects",
        "price_monthly": 19.00,
        "price_yearly": 190.00,
        "interval": "monthly",
        "features": ["1,000 API calls/month", "All AI models", "BYOK support", "Email support"],
        "api_calls_limit": 1000,
        "is_trial": False
    },
    {
        "plan_id": "0eefed2d-cdf8-4d0a-b5d0-852dacf9909d",
        "plan_code": "professional",
        "name": "Professional",
        "description": "Most popular - for growing teams",
        "price_monthly": 49.00,
        "price_yearly": 490.00,
        "interval": "monthly",
        "features": ["10,000 API calls/month", "All services", "Priority support", "Billing dashboard"],
        "api_calls_limit": 10000,
        "is_trial": False,
        "is_popular": True
    },
    {
        "plan_id": "ee2d9d3d-e985-4166-97ba-2fd6e8cd5b0b",
        "plan_code": "enterprise",
        "name": "Enterprise",
        "description": "For organizations with advanced needs",
        "price_monthly": 99.00,
        "price_yearly": 990.00,
        "interval": "monthly",
        "features": ["Unlimited API calls", "Team management (5 seats)", "Custom integrations", "24/7 support", "White-label"],
        "api_calls_limit": -1,  # -1 = unlimited
        "is_trial": False
    }
]


def _load_session(request: Request) -> dict:
    """Load the Redis-backed session for the request (raises 401 if missing)."""
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')

    from redis_session import RedisSessionManager

    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    redis_host = os.getenv("REDIS_HOST", "unicorn-redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))

    sessions = RedisSessionManager(host=redis_host, port=redis_port, password=os.getenv("REDIS_PASSWORD"))
    session_data = sessions.get(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")

    return session_data


async def get_user_org_id(request: Request) -> str:
    """Get organization ID from user session (Redis-backed)"""
    session_data = _load_session(request)

    # org_id is at the top level of the session data
    org_id = session_data.get("org_id")

    if not org_id:
        raise HTTPException(status_code=400, detail="User not assigned to organization. Please contact support.")

    return org_id


async def get_user_email(request: Request) -> str:
    """
    Get the user's email from the session for Lago billing lookups.

    The Lago billing customer (invoices, subscription, billing cycle) is keyed by
    EMAIL (external_id == email), not org_id, so billing-UI lookups resolve by email.
    """
    session_data = _load_session(request)
    user = session_data.get("user", {}) or {}
    email = user.get("email") or session_data.get("email")

    if not email:
        raise HTTPException(status_code=400, detail="User has no email on file for billing lookup.")

    return email


@router.get("/plans")
async def get_subscription_plans():
    """
    Get available subscription plans.

    Returns:
        List of subscription plans with pricing and features
    """
    logger.info("Fetching subscription plans")

    # Single source of truth: query the real subscription_tiers table (purchasable
    # tiers only). Shared with /api/v1/subscriptions/plans via _fetch_purchasable_tiers.
    try:
        from subscription_api import _fetch_purchasable_tiers

        plans = await _fetch_purchasable_tiers()
        if plans:
            logger.info(f"Fetched {len(plans)} plans from subscription_tiers")
            return {"plans": plans, "currency": "USD", "source": "database"}
    except Exception as e:
        logger.warning(f"Failed to fetch plans from subscription_tiers: {e}")

    # Fallback to hardcoded plans only if the database query fails entirely.
    logger.info("Using hardcoded plans as fallback")
    return {
        "plans": SUBSCRIPTION_PLANS,
        "currency": "USD",
        "source": "fallback"
    }


@router.get("/invoices")
async def get_invoices_list(request: Request, limit: int = 50):
    """
    Get invoice history from Lago.

    Args:
        limit: Maximum number of invoices to return (default: 50)

    Returns:
        List of invoices with status, amount, and dates
    """
    email = await get_user_email(request)

    logger.info(f"Fetching invoices for {email}, limit={limit}")

    try:
        # Get invoices from Lago (customer is email-keyed)
        invoices = await get_invoices_by_email(email, limit=limit)

        # Format invoice data for frontend
        formatted_invoices = []
        for invoice in invoices:
            formatted_invoices.append({
                "id": invoice.get("lago_id"),
                "invoice_number": invoice.get("number"),
                "amount": invoice.get("total_amount_cents", 0) / 100,  # Convert cents to dollars
                "currency": invoice.get("currency", "USD"),
                "status": invoice.get("status", "draft"),
                "issued_date": invoice.get("issuing_date"),
                "due_date": invoice.get("payment_due_date"),
                "paid_date": invoice.get("payment_at") if invoice.get("status") == "paid" else None,
                "pdf_url": invoice.get("file_url"),
                "period_start": invoice.get("from_date"),
                "period_end": invoice.get("to_date"),
                "description": f"Invoice for {invoice.get('from_date', '')} - {invoice.get('to_date', '')}"
            })

        logger.info(f"Retrieved {len(formatted_invoices)} invoices for org {org_id}")

        return formatted_invoices

    except Exception as e:
        logger.error(f"Error fetching invoices: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Billing service temporarily unavailable. Please try again later."
        )


@router.get("/cycle")
async def get_billing_cycle(request: Request):
    """
    Get current billing cycle information.

    Returns:
        Billing cycle dates and status
    """
    email = await get_user_email(request)

    logger.info(f"Fetching billing cycle for {email}")

    try:
        # Get subscription from Lago (customer is email-keyed)
        subscription = await get_subscription_by_email(email)

        if not subscription:
            return {
                "has_cycle": False,
                "message": "No active subscription"
            }

        # Extract billing cycle info
        cycle_start = subscription.get("started_at")
        billing_time = subscription.get("billing_time", "anniversary")

        # Calculate next billing date based on billing time
        # TODO: Calculate actual next billing date
        from datetime import timedelta
        if cycle_start:
            start_date = datetime.fromisoformat(cycle_start.replace('Z', '+00:00'))
            next_billing = start_date + timedelta(days=30)  # Approximate
        else:
            next_billing = datetime.utcnow() + timedelta(days=30)

        return {
            "has_cycle": True,
            "period_start": cycle_start,
            "period_end": next_billing.isoformat(),
            "next_billing_date": next_billing.isoformat(),
            "billing_time": billing_time,
            "status": subscription.get("status", "active")
        }

    except Exception as e:
        logger.error(f"Error fetching billing cycle: {e}", exc_info=True)
        return {
            "has_cycle": False,
            "message": f"Error: {str(e)}"
        }



@router.post("/download-invoice/{invoice_id}")
async def download_invoice(invoice_id: str, request: Request):
    """
    Generate download URL for invoice PDF.

    Args:
        invoice_id: Lago invoice ID

    Returns:
        PDF download URL
    """
    email = await get_user_email(request)

    logger.info(f"Requesting download for invoice {invoice_id}, user {email}")

    try:
        # Get invoices to find the specific one (customer is email-keyed)
        invoices = await get_invoices_by_email(email, limit=100)

        target_invoice = None
        for invoice in invoices:
            if invoice.get("lago_id") == invoice_id:
                target_invoice = invoice
                break

        if not target_invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        pdf_url = target_invoice.get("file_url")
        if not pdf_url:
            raise HTTPException(status_code=404, detail="Invoice PDF not available")

        return {
            "download_url": pdf_url,
            "invoice_number": target_invoice.get("number"),
            "expires_in": 3600  # URL typically expires in 1 hour
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting invoice download URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate download URL: {str(e)}")


@router.get("/summary")
async def get_billing_summary(request: Request):
    """
    Get billing summary with total spend, upcoming charges, etc.

    Returns:
        Billing summary statistics
    """
    email = await get_user_email(request)

    logger.info(f"Fetching billing summary for {email}")

    try:
        # Get recent invoices (customer is email-keyed)
        invoices = await get_invoices_by_email(email, limit=12)

        # Calculate statistics
        total_paid = 0
        total_pending = 0
        failed_count = 0

        for invoice in invoices:
            status = invoice.get("status")
            amount = invoice.get("total_amount_cents", 0) / 100

            if status == "paid":
                total_paid += amount
            elif status == "pending":
                total_pending += amount
            elif status == "failed":
                failed_count += 1

        return {
            "total_paid": total_paid,
            "total_pending": total_pending,
            "failed_payments": failed_count,
            "invoice_count": len(invoices),
            "currency": "USD"
        }

    except Exception as e:
        logger.error(f"Error fetching billing summary: {e}", exc_info=True)
        return {
            "total_paid": 0,
            "total_pending": 0,
            "failed_payments": 0,
            "invoice_count": 0,
            "currency": "USD"
        }
