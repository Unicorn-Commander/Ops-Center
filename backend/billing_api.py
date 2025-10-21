"""
Billing API Endpoints
Provides invoice history, billing cycle info, and payment management
"""

from fastapi import APIRouter, HTTPException, Request
from typing import List, Dict, Optional
from datetime import datetime
import logging

# Import Lago integration
from lago_integration import (
    get_invoices,
    get_subscription,
    get_customer
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["billing-lago"])


async def get_user_org_id(request: Request) -> str:
    """Get organization ID from user session"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    sessions = getattr(request.app.state, "sessions", {})
    session_data = sessions.get(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")

    user = session_data.get("user", {})
    org_id = user.get("org_id")

    if not org_id:
        # Fallback: generate org_id from email
        email = user.get("email")
        if email:
            org_id = f"org_{email.split('@')[0]}_{user.get('id', 'unknown')}"
            logger.warning(f"No org_id found, using generated: {org_id}")
        else:
            raise HTTPException(status_code=400, detail="Cannot determine org_id")

    return org_id


@router.get("/invoices")
async def get_invoices_list(request: Request, limit: int = 50):
    """
    Get invoice history from Lago.

    Args:
        limit: Maximum number of invoices to return (default: 50)

    Returns:
        List of invoices with status, amount, and dates
    """
    org_id = await get_user_org_id(request)

    logger.info(f"Fetching invoices for org {org_id}, limit={limit}")

    try:
        # Get invoices from Lago
        invoices = await get_invoices(org_id, limit=limit)

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
        # Return empty list instead of error to avoid breaking the UI
        return []


@router.get("/cycle")
async def get_billing_cycle(request: Request):
    """
    Get current billing cycle information.

    Returns:
        Billing cycle dates and status
    """
    org_id = await get_user_org_id(request)

    logger.info(f"Fetching billing cycle for org {org_id}")

    try:
        # Get subscription from Lago
        subscription = await get_subscription(org_id)

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


@router.get("/payment-methods")
async def get_payment_methods(request: Request):
    """
    Get stored payment methods (Stripe).

    Returns:
        List of payment methods
    """
    org_id = await get_user_org_id(request)

    logger.info(f"Fetching payment methods for org {org_id}")

    # TODO: Integrate with Stripe to get actual payment methods
    # For now, return placeholder
    return {
        "payment_methods": [],
        "default_method": None,
        "message": "Stripe payment methods integration coming soon"
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
    org_id = await get_user_org_id(request)

    logger.info(f"Requesting download for invoice {invoice_id}, org {org_id}")

    try:
        # Get invoices to find the specific one
        invoices = await get_invoices(org_id, limit=100)

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
    org_id = await get_user_org_id(request)

    logger.info(f"Fetching billing summary for org {org_id}")

    try:
        # Get recent invoices
        invoices = await get_invoices(org_id, limit=12)

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
