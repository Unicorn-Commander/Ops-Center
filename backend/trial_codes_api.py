"""
Trial Codes API  (Ops-Center)
=============================

Hand-out codes that grant an app entitlement to the redeemer's ORG for a trial
window. Two modes:
  - free : grants immediately (a $0 trial code), no payment.
  - paid : routes to a small Stripe charge ($1 default); the grant lands on
           payment success via the existing /api/v1/webhooks/stripe handler
           (see handle_trial_code_checkout below, called from webhooks.py).

The grant is written to org_features(org_id, feature_key, enabled, expires_at),
which is what GET /api/v1/entitlements reads -- so every app gating on that
endpoint (e.g. Project-Ops -> 'project_ops_access') honors a redeemed code.

Auth follows Ops-Center convention: session-cookie via auth_dependencies
(require_admin_user / require_authenticated_user). DB via database.connection.
"""

import os
import sys
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

if '/app' not in sys.path:
    sys.path.insert(0, '/app')

from database.connection import get_db_pool
from auth_dependencies import require_admin_user, require_authenticated_user
from feature_grant_utils import resolve_org_by_user_identifier

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/v1/admin/trial-codes", tags=["trial-codes-admin"])
user_router = APIRouter(prefix="/api/v1/trial-codes", tags=["trial-codes"])

# Unambiguous alphabet (no O/0/I/1) for generated codes.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_SUITE = os.getenv("OPS_CENTER_STRIPE_SUITE", "unicorn-commander")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_code(prefix: str = "PO") -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{prefix}-{body}"


# =============================================================================
# Models
# =============================================================================
class CreateCode(BaseModel):
    code: Optional[str] = None
    feature_keys: List[str] = Field(default_factory=lambda: ["project_ops_access"])
    mode: str = "free"           # 'free' | 'paid'
    price_cents: int = 100       # used only when mode == 'paid'
    trial_days: int = 14
    max_uses: int = 1
    note: Optional[str] = None
    campaign: Optional[str] = None


class RedeemRequest(BaseModel):
    code: str


# =============================================================================
# Shared helpers
# =============================================================================
async def _grant_org_features(conn, org_id, feature_keys, granted_by, expires_at, note):
    """Upsert org_features rows WITH an expiry (the endpoint filters on it)."""
    for key in feature_keys:
        await conn.execute(
            """
            INSERT INTO org_features (org_id, feature_key, enabled, granted_by, notes, expires_at)
            VALUES ($1, $2, TRUE, $3, $4, $5)
            ON CONFLICT (org_id, feature_key) DO UPDATE SET
                enabled = TRUE,
                granted_by = EXCLUDED.granted_by,
                granted_at = CURRENT_TIMESTAMP,
                notes = EXCLUDED.notes,
                expires_at = EXCLUDED.expires_at
            """,
            org_id, key, granted_by, note, expires_at,
        )


async def _resolve_org(conn, user: dict) -> dict:
    sub = user.get("user_id") or user.get("sub")
    email = user.get("email")
    org = await resolve_org_by_user_identifier(conn, user_id=sub, user_email=email)
    if not org or not org.get("org_id"):
        raise HTTPException(400, "Your account is not linked to an organization yet.")
    return org


# =============================================================================
# Admin endpoints
# =============================================================================
@admin_router.post("")
@admin_router.post("/")
async def create_code(body: CreateCode, admin: dict = Depends(require_admin_user)):
    if body.mode not in ("free", "paid"):
        raise HTTPException(400, "mode must be 'free' or 'paid'")
    if not body.feature_keys:
        raise HTTPException(400, "at least one feature_key is required")
    price_cents = body.price_cents if body.mode == "paid" else 0
    if body.mode == "paid" and price_cents < 50:
        raise HTTPException(400, "paid codes must be at least 50 cents (Stripe minimum)")

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        code = (body.code or "").strip().upper() or _gen_code()
        for _ in range(5):
            exists = await conn.fetchval("SELECT 1 FROM trial_codes WHERE code = $1", code)
            if not exists:
                break
            if body.code:
                raise HTTPException(409, f"code '{code}' already exists")
            code = _gen_code()
        row = await conn.fetchrow(
            """
            INSERT INTO trial_codes
                (code, feature_keys, mode, price_cents, trial_days, max_uses,
                 note, campaign, created_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING *
            """,
            code, body.feature_keys, body.mode, price_cents, body.trial_days,
            max(1, body.max_uses), body.note, body.campaign,
            admin.get("email") or admin.get("user_id"),
        )
        return dict(row)


@admin_router.get("")
@admin_router.get("/")
async def list_codes(admin: dict = Depends(require_admin_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.*,
                   (SELECT count(*) FROM trial_code_redemptions r
                    WHERE r.code_id = c.id AND r.status IN ('granted','active')) AS redemption_count
            FROM trial_codes c
            ORDER BY c.created_at DESC
            """
        )
        return [dict(r) for r in rows]


@admin_router.post("/{code_id}/deactivate")
async def deactivate_code(code_id: str, admin: dict = Depends(require_admin_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE trial_codes SET is_active = FALSE WHERE id = $1", code_id
        )
        if res.endswith("0"):
            raise HTTPException(404, "code not found")
        return {"deactivated": True, "code_id": code_id}


@admin_router.get("/{code_id}/redemptions")
async def list_redemptions(code_id: str, admin: dict = Depends(require_admin_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.*, o.name AS org_name
            FROM trial_code_redemptions r
            LEFT JOIN organizations o ON o.id = r.org_id
            WHERE r.code_id = $1
            ORDER BY r.redeemed_at DESC
            """,
            code_id,
        )
        return [dict(r) for r in rows]


# =============================================================================
# User endpoints
# =============================================================================
@user_router.get("/validate/{code}")
async def validate_code(code: str, user: dict = Depends(require_authenticated_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM trial_codes WHERE code = $1", code.strip().upper()
        )
        if not row:
            raise HTTPException(404, "Invalid code")
        c = dict(row)
        if not c["is_active"]:
            raise HTTPException(400, "This code is no longer active")
        if c["expires_at"] and c["expires_at"] <= _now():
            raise HTTPException(400, "This code has expired")
        if c["uses_count"] >= c["max_uses"]:
            raise HTTPException(400, "This code has been fully redeemed")
        return {
            "valid": True,
            "code": {
                "feature_keys": c["feature_keys"],
                "mode": c["mode"],
                "price_cents": c["price_cents"],
                "trial_days": c["trial_days"],
            },
        }


@user_router.post("/redeem")
async def redeem_code(body: RedeemRequest, request: Request,
                      user: dict = Depends(require_authenticated_user)):
    norm = body.code.strip().upper()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        org = await _resolve_org(conn, user)
        org_id = org["org_id"]
        sub = user.get("user_id") or user.get("sub")
        email = user.get("email")

        code = await conn.fetchrow("SELECT * FROM trial_codes WHERE code = $1", norm)
        if not code:
            raise HTTPException(400, "Invalid code")
        code = dict(code)
        if not code["is_active"]:
            raise HTTPException(400, "This code is no longer active")
        if code["expires_at"] and code["expires_at"] <= _now():
            raise HTTPException(400, "This code has expired")

        # Idempotency: one redemption per (code, org).
        existing = await conn.fetchrow(
            "SELECT * FROM trial_code_redemptions WHERE code_id = $1 AND org_id = $2",
            code["id"], org_id,
        )
        if existing and existing["status"] in ("granted", "active"):
            return {"status": existing["status"], "already_redeemed": True,
                    "feature_keys": existing["feature_keys"],
                    "grant_expires_at": existing["grant_expires_at"]}

        grant_expires_at = _now() + timedelta(days=code["trial_days"])

        # -------- FREE: grant now ------------------------------------------
        if code["mode"] == "free":
            async with conn.transaction():
                locked = await conn.fetchrow(
                    "SELECT uses_count, max_uses, is_active FROM trial_codes WHERE id = $1 FOR UPDATE",
                    code["id"],
                )
                if not locked["is_active"]:
                    raise HTTPException(400, "This code is no longer active")
                if locked["uses_count"] >= locked["max_uses"]:
                    raise HTTPException(400, "This code has been fully redeemed")
                await _grant_org_features(
                    conn, org_id, code["feature_keys"],
                    granted_by=f"trial-code:{code['code']}",
                    expires_at=grant_expires_at,
                    note=f"Free trial via code {code['code']} (redeemed by {email})",
                )
                await conn.execute(
                    """
                    INSERT INTO trial_code_redemptions
                        (code_id, org_id, user_sub, user_email, feature_keys,
                         grant_expires_at, status, activated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,'granted', CURRENT_TIMESTAMP)
                    ON CONFLICT (code_id, org_id) DO UPDATE SET
                        status = 'granted', grant_expires_at = EXCLUDED.grant_expires_at,
                        feature_keys = EXCLUDED.feature_keys, activated_at = CURRENT_TIMESTAMP
                    """,
                    code["id"], org_id, sub, email, code["feature_keys"], grant_expires_at,
                )
                await conn.execute(
                    "UPDATE trial_codes SET uses_count = uses_count + 1 WHERE id = $1",
                    code["id"],
                )
            return {"status": "granted", "already_redeemed": False,
                    "feature_keys": code["feature_keys"],
                    "grant_expires_at": grant_expires_at}

        # -------- PAID: Stripe checkout; grant on webhook ------------------
        if not os.getenv("STRIPE_SECRET_KEY"):
            raise HTTPException(503, "Billing is not configured; cannot process a paid code.")
        try:
            import stripe
        except Exception:
            raise HTTPException(503, "Stripe library unavailable.")
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

        # Record/refresh a pending redemption first (idempotent per org).
        red = await conn.fetchrow(
            """
            INSERT INTO trial_code_redemptions
                (code_id, org_id, user_sub, user_email, feature_keys, grant_expires_at, status)
            VALUES ($1,$2,$3,$4,$5,$6,'pending')
            ON CONFLICT (code_id, org_id) DO UPDATE SET
                status = 'pending', grant_expires_at = EXCLUDED.grant_expires_at
            RETURNING id
            """,
            code["id"], org_id, sub, email, code["feature_keys"], grant_expires_at,
        )
        redemption_id = str(red["id"])

        base = (os.getenv("STRIPE_SUCCESS_URL") or "https://unicorncommander.ai").rstrip("/")
        cancel = os.getenv("STRIPE_CANCEL_URL") or base
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": f"Project-Ops trial ({code['trial_days']} days)"},
                        "unit_amount": code["price_cents"],
                    },
                    "quantity": 1,
                }],
                customer_email=email,
                success_url=f"{base}?trial=success",
                cancel_url=f"{cancel}?trial=cancelled",
                metadata={
                    "suite": _SUITE,
                    "trial_code_redemption_id": redemption_id,
                    "trial_code": code["code"],
                    "org_id": str(org_id),
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"trial-code stripe checkout failed: {e}")
            raise HTTPException(502, "Could not start checkout; please try again.")

        await conn.execute(
            "UPDATE trial_code_redemptions SET stripe_session_id = $1 WHERE id = $2",
            session.get("id"), redemption_id,
        )
        return {"status": "checkout", "already_redeemed": False,
                "checkout_url": session.get("url")}


# =============================================================================
# Webhook grant hook -- called from webhooks.py on checkout.session.completed
# =============================================================================
async def handle_trial_code_checkout(event: dict, pool) -> dict:
    """If this Stripe event is a trial-code checkout, grant org_features.

    Returns {"handled": True} when it consumed the event, else {"handled": False}
    so the caller's existing suite logic can run. Non-fatal by construction.
    """
    try:
        if event.get("type") != "checkout.session.completed":
            return {"handled": False}
        session = event["data"]["object"]
        md = session.get("metadata") or {}
        redemption_id = md.get("trial_code_redemption_id")
        if not redemption_id:
            return {"handled": False}
        if session.get("payment_status") not in ("paid", "no_payment_required"):
            return {"handled": True}  # ours, but not paid yet

        async with pool.acquire() as conn:
            red = await conn.fetchrow(
                "SELECT * FROM trial_code_redemptions WHERE id = $1", redemption_id
            )
            if not red:
                return {"handled": True}
            if red["status"] == "active":
                return {"handled": True}
            grant_expires_at = red["grant_expires_at"] or (_now() + timedelta(days=14))
            async with conn.transaction():
                await _grant_org_features(
                    conn, red["org_id"], red["feature_keys"],
                    granted_by=f"trial-code:{md.get('trial_code', '')}",
                    expires_at=grant_expires_at,
                    note=f"Paid trial via code {md.get('trial_code', '')} "
                         f"(redeemed by {red['user_email']})",
                )
                await conn.execute(
                    """
                    UPDATE trial_code_redemptions
                    SET status = 'active', activated_at = CURRENT_TIMESTAMP,
                        stripe_customer_id = $2
                    WHERE id = $1
                    """,
                    redemption_id, session.get("customer"),
                )
                await conn.execute(
                    "UPDATE trial_codes SET uses_count = uses_count + 1 WHERE id = $1",
                    red["code_id"],
                )
        logger.info(f"trial-code redemption {redemption_id} activated via Stripe")
        return {"handled": True}
    except Exception as e:  # noqa: BLE001
        logger.error(f"handle_trial_code_checkout failed (non-fatal): {e}")
        return {"handled": False}
