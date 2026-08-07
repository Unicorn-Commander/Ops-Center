"""
Trial / Signup Codes API  (Ops-Center)
======================================

Individual, single-use (by default) codes handed out ONE PER PERSON. A code can:
  - grant an app entitlement to the redeemer's ORG (feature_keys -> org_features,
    with an optional expiry so trials auto-lapse), and/or
  - put the org on a plan TIER (grant_tier, e.g. 'founder_friend' -> comp access
    where LOCAL inference is free and CLOUD inference is metered/paid), applied
    via the suite's own provision_paid_org.

Modes:
  - free : applies immediately, no payment (a $0 trial or a comp).
  - paid : routes to a small Stripe charge ($1 default); the grant lands on
           payment success via /api/v1/webhooks/stripe (handle_trial_code_checkout).

Redemption writes org_features(feature_key, expires_at) -- what
GET /api/v1/entitlements reads (tier_features UNION org_features) -- and/or sets
organizations.plan_tier, so downstream apps (e.g. Project-Ops) honor it.

Auth: session-cookie via auth_dependencies. DB via database.connection.
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

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no O/0/I/1
_SUITE = os.getenv("OPS_CENTER_STRIPE_SUITE", "unicorn-commander")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_code(prefix: str = "PO") -> str:
    return f"{prefix}-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


# =============================================================================
# Models
# =============================================================================
class CreateCode(BaseModel):
    code: Optional[str] = None                 # custom code (only when count == 1)
    count: int = 1                             # generate N individual codes at once
    feature_keys: List[str] = Field(default_factory=list)   # e.g. ['project_ops_access']
    grant_tier: Optional[str] = None           # e.g. 'founder_friend' (comp tier)
    mode: str = "free"                         # 'free' | 'paid'
    price_cents: int = 100                     # used only when mode == 'paid'
    trial_days: int = 14                       # 0 = no expiry (permanent comp)
    max_uses: int = 1                          # 1 = individual, single-use
    note: Optional[str] = None
    campaign: Optional[str] = None


class RedeemRequest(BaseModel):
    code: str


# =============================================================================
# Shared helpers
# =============================================================================
async def _grant_org_features(conn, org_id, feature_keys, granted_by, expires_at, note):
    """Upsert org_features rows WITH an optional expiry (the endpoint filters it)."""
    for key in feature_keys or []:
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


async def _apply_tier(org_id, tier, email, source):
    """Put an org on a plan tier the suite's own way (provision_paid_org handles
    plan_tier + free-tier Lago skip + gateway key cap). Falls back to a plain
    plan_tier update. Never raises."""
    try:
        from paid_org_provisioning import provision_paid_org
        return await provision_paid_org(str(org_id), tier, email=email, source=source)
    except Exception as e:  # noqa: BLE001
        logger.error(f"provision_paid_org('{tier}') failed, falling back to plan_tier update: {e}")
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE organizations SET plan_tier = $1 WHERE id = $2", tier, org_id
                )
            return {"fallback_plan_tier": tier}
        except Exception as e2:  # noqa: BLE001
            logger.error(f"plan_tier fallback also failed for org {org_id}: {e2}")
            return {"error": str(e2)}


async def _resolve_org(conn, user: dict) -> dict:
    """Resolve the redeemer's active org. In this deployment org membership is
    keyed DIRECTLY by the Keycloak sub in organization_members (the `users`
    table is largely unused), so we resolve that way -- and prefer the org the
    session already established at login."""
    # 1) the session already carries the active org (set at login).
    if user.get("org_id"):
        return {"org_id": str(user["org_id"])}

    sub = user.get("user_id") or user.get("sub")
    email = user.get("email")

    # 2) memberships are keyed by the KC sub (uc_uid) directly.
    if sub:
        row = await conn.fetchrow(
            """
            SELECT om.org_id
            FROM organization_members om
            JOIN organizations o ON om.org_id = o.id
            WHERE om.user_id = $1 AND COALESCE(o.status, 'active') = 'active'
            ORDER BY om.is_default DESC NULLS LAST, om.joined_at ASC
            LIMIT 1
            """,
            sub,
        )
        if row and row["org_id"]:
            return {"org_id": str(row["org_id"])}

    # 3) fallback: the users-JOIN resolver (covers internal-id / email cases).
    org = await resolve_org_by_user_identifier(conn, user_id=sub, user_email=email)
    if org and org.get("org_id"):
        return {"org_id": str(org["org_id"])}

    raise HTTPException(
        400,
        "Your account isn't linked to an organization yet. Sign in to the "
        "dashboard once so your workspace is set up, then try the code again.",
    )


def _grant_expiry(trial_days: int):
    return None if not trial_days or trial_days <= 0 else _now() + timedelta(days=trial_days)


# =============================================================================
# Admin endpoints
# =============================================================================
@admin_router.post("")
@admin_router.post("/")
async def create_codes(body: CreateCode, admin: dict = Depends(require_admin_user)):
    """Create one or many INDIVIDUAL codes. Returns {"codes": [...]}. Use count>1
    to mint a batch of unique single-use codes (one per person)."""
    if body.mode not in ("free", "paid"):
        raise HTTPException(400, "mode must be 'free' or 'paid'")
    if not body.feature_keys and not body.grant_tier:
        raise HTTPException(400, "a code must grant at least one feature_key or a grant_tier")
    price_cents = body.price_cents if body.mode == "paid" else 0
    if body.mode == "paid" and price_cents < 50:
        raise HTTPException(400, "paid codes must be at least 50 cents (Stripe minimum)")
    count = max(1, min(int(body.count or 1), 500))
    if body.code and count > 1:
        raise HTTPException(400, "a custom code can only be set when count == 1")

    created = []
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        for _ in range(count):
            code = (body.code or "").strip().upper() or _gen_code()
            for _try in range(6):
                if not await conn.fetchval("SELECT 1 FROM trial_codes WHERE code = $1", code):
                    break
                if body.code:
                    raise HTTPException(409, f"code '{code}' already exists")
                code = _gen_code()
            row = await conn.fetchrow(
                """
                INSERT INTO trial_codes
                    (code, feature_keys, grant_tier, mode, price_cents, trial_days,
                     max_uses, note, campaign, created_by)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                RETURNING *
                """,
                code, body.feature_keys, body.grant_tier, body.mode, price_cents,
                body.trial_days, max(1, body.max_uses), body.note, body.campaign,
                admin.get("email") or admin.get("user_id"),
            )
            created.append(dict(row))
    return {"codes": created, "count": len(created)}


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
        res = await conn.execute("UPDATE trial_codes SET is_active = FALSE WHERE id = $1", code_id)
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
def _describe(c: dict) -> dict:
    return {
        "feature_keys": c["feature_keys"],
        "grant_tier": c["grant_tier"],
        "mode": c["mode"],
        "price_cents": c["price_cents"],
        "trial_days": c["trial_days"],
    }


@user_router.get("/validate/{code}")
async def validate_code(code: str, user: dict = Depends(require_authenticated_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM trial_codes WHERE code = $1", code.strip().upper())
        if not row:
            raise HTTPException(404, "Invalid code")
        c = dict(row)
        if not c["is_active"]:
            raise HTTPException(400, "This code is no longer active")
        if c["expires_at"] and c["expires_at"] <= _now():
            raise HTTPException(400, "This code has expired")
        if c["uses_count"] >= c["max_uses"]:
            raise HTTPException(400, "This code has been fully redeemed")
        return {"valid": True, "code": _describe(c)}


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

        existing = await conn.fetchrow(
            "SELECT * FROM trial_code_redemptions WHERE code_id = $1 AND org_id = $2",
            code["id"], org_id,
        )
        if existing and existing["status"] in ("granted", "active"):
            return {"status": existing["status"], "already_redeemed": True,
                    "feature_keys": existing["feature_keys"],
                    "grant_tier": code["grant_tier"],
                    "grant_expires_at": existing["grant_expires_at"]}

        grant_expires_at = _grant_expiry(code["trial_days"])

        # -------- FREE: apply now ------------------------------------------
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
                    note=f"Code {code['code']} redeemed by {email}",
                )
                await conn.execute(
                    """
                    INSERT INTO trial_code_redemptions
                        (code_id, org_id, user_sub, user_email, feature_keys,
                         grant_expires_at, status, activated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,'granted', CURRENT_TIMESTAMP)
                    ON CONFLICT (code_id, org_id) DO UPDATE SET
                        status='granted', grant_expires_at=EXCLUDED.grant_expires_at,
                        feature_keys=EXCLUDED.feature_keys, activated_at=CURRENT_TIMESTAMP
                    """,
                    code["id"], org_id, sub, email, code["feature_keys"], grant_expires_at,
                )
                await conn.execute(
                    "UPDATE trial_codes SET uses_count = uses_count + 1 WHERE id = $1", code["id"]
                )
            # tier grant (comp) via the suite's own provisioning, outside the txn
            if code["grant_tier"]:
                await _apply_tier(org_id, code["grant_tier"], email, f"trial-code:{code['code']}")
            return {"status": "granted", "already_redeemed": False,
                    "feature_keys": code["feature_keys"], "grant_tier": code["grant_tier"],
                    "grant_expires_at": grant_expires_at}

        # -------- PAID: Stripe checkout; apply on webhook ------------------
        if not os.getenv("STRIPE_SECRET_KEY"):
            raise HTTPException(503, "Billing is not configured; cannot process a paid code.")
        try:
            import stripe
        except Exception:
            raise HTTPException(503, "Stripe library unavailable.")
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

        red = await conn.fetchrow(
            """
            INSERT INTO trial_code_redemptions
                (code_id, org_id, user_sub, user_email, feature_keys, grant_expires_at, status)
            VALUES ($1,$2,$3,$4,$5,$6,'pending')
            ON CONFLICT (code_id, org_id) DO UPDATE SET
                status='pending', grant_expires_at=EXCLUDED.grant_expires_at
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
    """Grant a paid trial code's entitlement on Stripe payment. Returns
    {"handled": True} when it consumed the event. Non-fatal by construction."""
    try:
        if event.get("type") != "checkout.session.completed":
            return {"handled": False}
        session = event["data"]["object"]
        md = session.get("metadata") or {}
        redemption_id = md.get("trial_code_redemption_id")
        if not redemption_id:
            return {"handled": False}
        if session.get("payment_status") not in ("paid", "no_payment_required"):
            return {"handled": True}

        grant_tier = None
        target_org = None
        target_email = None
        async with pool.acquire() as conn:
            red = await conn.fetchrow(
                "SELECT * FROM trial_code_redemptions WHERE id = $1", redemption_id
            )
            if not red:
                return {"handled": True}
            if red["status"] == "active":
                return {"handled": True}
            code = await conn.fetchrow("SELECT * FROM trial_codes WHERE id = $1", red["code_id"])
            grant_tier = code["grant_tier"] if code else None
            target_org = red["org_id"]
            target_email = red["user_email"]
            grant_expires_at = red["grant_expires_at"]
            async with conn.transaction():
                await _grant_org_features(
                    conn, red["org_id"], red["feature_keys"],
                    granted_by=f"trial-code:{md.get('trial_code', '')}",
                    expires_at=grant_expires_at,
                    note=f"Paid code {md.get('trial_code', '')} redeemed by {red['user_email']}",
                )
                await conn.execute(
                    """
                    UPDATE trial_code_redemptions
                    SET status='active', activated_at=CURRENT_TIMESTAMP, stripe_customer_id=$2
                    WHERE id=$1
                    """,
                    redemption_id, session.get("customer"),
                )
                await conn.execute(
                    "UPDATE trial_codes SET uses_count = uses_count + 1 WHERE id = $1",
                    red["code_id"],
                )
        if grant_tier and target_org:
            await _apply_tier(target_org, grant_tier, target_email,
                              f"trial-code:{md.get('trial_code', '')}")
        logger.info(f"trial-code redemption {redemption_id} activated via Stripe")
        return {"handled": True}
    except Exception as e:  # noqa: BLE001
        logger.error(f"handle_trial_code_checkout failed (non-fatal): {e}")
        return {"handled": False}
