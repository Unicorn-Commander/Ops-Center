"""
Stripe Client for Billing Operations
Provides high-level interface to Stripe API for subscription and payment management
"""
import os
from typing import Dict, List, Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class StripeClient:
    """
    Stripe integration client for UC-1 Pro billing

    Features:
    - Subscription management
    - Invoice retrieval
    - Payment method management
    - Customer statistics
    - Revenue reporting

    Usage:
        stripe_client = StripeClient()

        # Get customer subscription
        subscription = await stripe_client.get_customer_subscription(customer_id)

        # Get customer invoices
        invoices = await stripe_client.get_customer_invoices(customer_id, limit=10)

        # Admin: Get revenue stats
        stats = await stripe_client.get_revenue_stats()
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Stripe client

        Args:
            api_key: Stripe secret key (or from env STRIPE_SECRET_KEY)
        """
        self.api_key = api_key or os.environ.get("STRIPE_SECRET_KEY")

        # Initialize Stripe SDK
        try:
            import stripe
            self.stripe = stripe
            if self.api_key:
                self.stripe.api_key = self.api_key
                self.enabled = True
            else:
                self.enabled = False
                logger.warning("Stripe API key not configured - billing features disabled")
        except ImportError:
            self.stripe = None
            self.enabled = False
            logger.error("Stripe module not installed - run: pip install stripe")

    async def get_customer_by_email(self, email: str) -> Optional[Dict]:
        """
        Find Stripe customer by email

        Args:
            email: Customer email address

        Returns:
            Customer object or None if not found
        """
        if not self.enabled:
            return None

        try:
            customers = self.stripe.Customer.list(email=email, limit=1)
            if customers.data:
                return customers.data[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching customer by email {email}: {e}")
            return None

    async def get_customer_subscription(self, customer_id: str) -> Optional[Dict]:
        """
        Get active subscription for a customer

        Args:
            customer_id: Stripe customer ID

        Returns:
            Subscription data or None if no active subscription
        """
        if not self.enabled:
            return None

        try:
            subscriptions = self.stripe.Subscription.list(
                customer=customer_id,
                status="active",
                limit=1
            )

            if subscriptions.data:
                sub = subscriptions.data[0]

                # Get tier from metadata
                tier = sub.metadata.get("tier", "trial")

                # Get price info
                price_item = sub["items"].data[0] if sub.get("items") else None
                amount = price_item.plan.amount / 100 if price_item else 0  # Convert cents to dollars
                interval = price_item.plan.interval if price_item else "month"

                return {
                    "id": sub.id,
                    "tier": tier,
                    "status": sub.status,
                    "current_period_start": datetime.fromtimestamp(sub.current_period_start, tz=timezone.utc).isoformat(),
                    "current_period_end": datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc).isoformat(),
                    "cancel_at_period_end": sub.cancel_at_period_end,
                    "amount": amount,
                    "interval": interval,
                    "currency": price_item.plan.currency if price_item else "usd"
                }

            return None
        except Exception as e:
            logger.error(f"Error fetching subscription for customer {customer_id}: {e}")
            return None

    async def get_customer_invoices(
        self,
        customer_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get invoices for a customer

        Args:
            customer_id: Stripe customer ID
            limit: Maximum number of invoices to return

        Returns:
            List of invoice objects
        """
        if not self.enabled:
            return []

        try:
            invoices = self.stripe.Invoice.list(
                customer=customer_id,
                limit=limit
            )

            result = []
            for invoice in invoices.data:
                result.append({
                    "id": invoice.id,
                    "number": invoice.number,
                    "amount_due": invoice.amount_due / 100,  # Convert cents to dollars
                    "amount_paid": invoice.amount_paid / 100,
                    "currency": invoice.currency,
                    "status": invoice.status,
                    "created": datetime.fromtimestamp(invoice.created, tz=timezone.utc).isoformat(),
                    "due_date": datetime.fromtimestamp(invoice.due_date, tz=timezone.utc).isoformat() if invoice.due_date else None,
                    "paid": invoice.paid,
                    "invoice_pdf": invoice.invoice_pdf,
                    "hosted_invoice_url": invoice.hosted_invoice_url
                })

            return result
        except Exception as e:
            logger.error(f"Error fetching invoices for customer {customer_id}: {e}")
            return []

    async def get_customer_payment_methods(self, customer_id: str) -> List[Dict]:
        """
        Get payment methods for a customer

        Args:
            customer_id: Stripe customer ID

        Returns:
            List of payment method objects
        """
        if not self.enabled:
            return []

        try:
            payment_methods = self.stripe.PaymentMethod.list(
                customer=customer_id,
                type="card"
            )

            result = []
            for pm in payment_methods.data:
                result.append({
                    "id": pm.id,
                    "type": pm.type,
                    "card": {
                        "brand": pm.card.brand,
                        "last4": pm.card.last4,
                        "exp_month": pm.card.exp_month,
                        "exp_year": pm.card.exp_year
                    } if pm.card else None,
                    "created": datetime.fromtimestamp(pm.created, tz=timezone.utc).isoformat()
                })

            return result
        except Exception as e:
            logger.error(f"Error fetching payment methods for customer {customer_id}: {e}")
            return []

    async def get_all_customers(self, limit: int = 100) -> List[Dict]:
        """
        Get all customers (admin only)

        Args:
            limit: Maximum number of customers to return

        Returns:
            List of customer objects
        """
        if not self.enabled:
            return []

        try:
            customers = self.stripe.Customer.list(limit=limit)

            result = []
            for customer in customers.data:
                result.append({
                    "id": customer.id,
                    "email": customer.email,
                    "name": customer.name,
                    "created": datetime.fromtimestamp(customer.created, tz=timezone.utc).isoformat(),
                    "metadata": customer.metadata
                })

            return result
        except Exception as e:
            logger.error(f"Error fetching all customers: {e}")
            return []

    async def get_all_subscriptions(
        self,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get all subscriptions (admin only)

        Args:
            status: Filter by status (active, canceled, etc.)
            limit: Maximum number of subscriptions to return

        Returns:
            List of subscription objects
        """
        if not self.enabled:
            return []

        try:
            params = {"limit": limit}
            if status:
                params["status"] = status

            subscriptions = self.stripe.Subscription.list(**params)

            result = []
            for sub in subscriptions.data:
                price_item = sub["items"].data[0] if sub.get("items") else None
                amount = price_item.plan.amount / 100 if price_item else 0

                result.append({
                    "id": sub.id,
                    "customer": sub.customer,
                    "tier": sub.metadata.get("tier", "unknown"),
                    "status": sub.status,
                    "amount": amount,
                    "currency": price_item.plan.currency if price_item else "usd",
                    "interval": price_item.plan.interval if price_item else "month",
                    "current_period_end": datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc).isoformat(),
                    "cancel_at_period_end": sub.cancel_at_period_end
                })

            return result
        except Exception as e:
            logger.error(f"Error fetching all subscriptions: {e}")
            return []

    async def get_revenue_stats(self) -> Dict:
        """
        Get revenue statistics (admin only)

        Returns:
            Revenue statistics including:
            - Total customers
            - Active subscriptions
            - Monthly recurring revenue
            - Subscription breakdown by tier
        """
        if not self.enabled:
            return {
                "total_customers": 0,
                "active_subscriptions": 0,
                "trial_subscriptions": 0,
                "monthly_revenue": 0,
                "tier_breakdown": {}
            }

        try:
            # Get all active subscriptions
            subscriptions = await self.get_all_subscriptions(status="active")

            # Calculate statistics
            total_customers = len(await self.get_all_customers())
            active_subs = len(subscriptions)
            trial_subs = len([s for s in subscriptions if s.get("tier") == "trial"])

            # Calculate MRR (Monthly Recurring Revenue)
            monthly_revenue = 0
            tier_breakdown = {}

            for sub in subscriptions:
                amount = sub.get("amount", 0)
                interval = sub.get("interval", "month")
                tier = sub.get("tier", "unknown")

                # Convert to monthly amount
                if interval == "year":
                    monthly_amount = amount / 12
                elif interval == "week":
                    monthly_amount = amount * 4.33  # Average weeks per month
                else:  # month
                    monthly_amount = amount

                monthly_revenue += monthly_amount

                # Track by tier
                if tier not in tier_breakdown:
                    tier_breakdown[tier] = {"count": 0, "revenue": 0}
                tier_breakdown[tier]["count"] += 1
                tier_breakdown[tier]["revenue"] += monthly_amount

            return {
                "total_customers": total_customers,
                "active_subscriptions": active_subs,
                "trial_subscriptions": trial_subs,
                "monthly_revenue": round(monthly_revenue, 2),
                "tier_breakdown": tier_breakdown
            }
        except Exception as e:
            logger.error(f"Error calculating revenue stats: {e}")
            return {
                "total_customers": 0,
                "active_subscriptions": 0,
                "trial_subscriptions": 0,
                "monthly_revenue": 0,
                "tier_breakdown": {},
                "error": str(e)
            }

    async def get_recent_charges(self, limit: int = 20) -> List[Dict]:
        """
        Get recent charges (admin only)

        Args:
            limit: Maximum number of charges to return

        Returns:
            List of charge objects
        """
        if not self.enabled:
            return []

        try:
            charges = self.stripe.Charge.list(limit=limit)

            result = []
            for charge in charges.data:
                result.append({
                    "id": charge.id,
                    "amount": charge.amount / 100,
                    "currency": charge.currency,
                    "status": charge.status,
                    "customer": charge.customer,
                    "description": charge.description,
                    "created": datetime.fromtimestamp(charge.created, tz=timezone.utc).isoformat(),
                    "paid": charge.paid,
                    "refunded": charge.refunded
                })

            return result
        except Exception as e:
            logger.error(f"Error fetching recent charges: {e}")
            return []
