"""
Campaigns / Promos admin API.

Central campaign layer for suite-wide promos, comp grants, and campaign-scoped invite
codes. Reuses org feature grant plumbing so entitlement authority stays in one place.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, root_validator, validator

from auth_dependencies import require_admin_user
from database.connection import get_db_pool
from feature_grant_utils import (
    grant_feature_keys_to_org,
    normalize_feature_keys,
    resolve_org_by_user_identifier,
    revoke_feature_keys_from_org,
    verify_org_exists,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/campaigns", tags=["campaigns"])


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:120] or "campaign"


class CampaignBase(BaseModel):
    slug: Optional[str] = Field(None, max_length=120)
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    app_feature_keys: List[str] = Field(default_factory=list)
    comp_tier_code: Optional[str] = Field(None, max_length=50)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    status: str = Field("draft")
    notes: Optional[str] = None

    @validator("status")
    def validate_status(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"draft", "active", "paused", "ended"}:
            raise ValueError("status must be draft, active, paused, or ended")
        return value


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    slug: Optional[str] = Field(None, max_length=120)
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    app_feature_keys: Optional[List[str]] = None
    comp_tier_code: Optional[str] = Field(None, max_length=50)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    status: Optional[str] = None
    notes: Optional[str] = None

    @validator("status")
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.lower().strip()
        if value not in {"draft", "active", "paused", "ended"}:
            raise ValueError("status must be draft, active, paused, or ended")
        return value


class CampaignResponse(CampaignBase):
    id: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    app_names: List[str] = Field(default_factory=list)
    minted_codes: int = 0
    redeemed_codes: int = 0
    active_grants: int = 0
    revoked_grants: int = 0
    expired_grants: int = 0


class CampaignGrantRequest(BaseModel):
    org_id: Optional[str] = None
    user_email: Optional[str] = None
    expires_at: Optional[datetime] = None

    @root_validator
    def validate_org_or_email(cls, values):
        if not values.get("org_id") and not values.get("user_email"):
            raise ValueError("Provide org_id or user_email")
        return values


class CampaignGrantResponse(BaseModel):
    id: str
    campaign_id: str
    campaign_name: Optional[str] = None
    org_id: str
    org_name: Optional[str] = None
    org_display_name: Optional[str] = None
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    granted_feature_keys: List[str] = Field(default_factory=list)
    comp_tier_code: Optional[str] = None
    source: str
    status: str
    expires_at: Optional[datetime] = None
    created_at: datetime
    created_by: Optional[str] = None


class CampaignSummaryResponse(BaseModel):
    id: str
    slug: str
    name: str
    status: str
    starts_at: datetime
    ends_at: Optional[datetime] = None
    app_feature_keys: List[str] = Field(default_factory=list)
    app_names: List[str] = Field(default_factory=list)
    minted_codes: int = 0
    redeemed_codes: int = 0
    active_grants: int = 0
    revoked_grants: int = 0
    expired_grants: int = 0


def _campaign_row_to_response(row: asyncpg.Record, app_names: List[str], counts: Dict[str, int]) -> CampaignResponse:
    return CampaignResponse(
        id=str(row["id"]),
        slug=row["slug"],
        name=row["name"],
        description=row["description"],
        app_feature_keys=list(row["app_feature_keys"] or []),
        comp_tier_code=row["comp_tier_code"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        status=row["status"],
        notes=row["notes"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        app_names=app_names,
        minted_codes=int(counts["minted_codes"] or 0),
        redeemed_codes=int(counts["redeemed_codes"] or 0),
        active_grants=int(counts["active_grants"] or 0),
        revoked_grants=int(counts["revoked_grants"] or 0),
        expired_grants=int(counts["expired_grants"] or 0),
    )


async def _feature_names(conn: asyncpg.Connection, feature_keys: List[str]) -> List[str]:
    normalized = normalize_feature_keys(feature_keys)
    if not normalized:
        return []
    rows = await conn.fetch(
        """
        SELECT name
        FROM add_ons
        WHERE feature_key = ANY($1::text[])
        ORDER BY sort_order, name
        """,
        normalized,
    )
    return [row["name"] for row in rows]


async def _get_campaign(conn: asyncpg.Connection, campaign_id: str) -> asyncpg.Record:
    row = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Campaign not found: {campaign_id}")
    return row


async def _campaign_counts(conn: asyncpg.Connection, campaign_id: str) -> Dict[str, int]:
    counts = await conn.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM invite_codes WHERE campaign_id = $1) AS minted_codes,
            (SELECT COUNT(*)
             FROM invite_code_redemptions icr
             JOIN invite_codes ic ON icr.invite_code_id = ic.id
             WHERE ic.campaign_id = $1) AS redeemed_codes,
            (SELECT COUNT(*) FROM campaign_grants WHERE campaign_id = $1 AND status = 'active') AS active_grants,
            (SELECT COUNT(*) FROM campaign_grants WHERE campaign_id = $1 AND status = 'revoked') AS revoked_grants,
            (SELECT COUNT(*) FROM campaign_grants WHERE campaign_id = $1 AND (status = 'expired' OR (status = 'active' AND expires_at IS NOT NULL AND expires_at < NOW()))) AS expired_grants
        """,
        campaign_id,
    )
    return dict(counts)


def _effective_grant_status(row: asyncpg.Record) -> str:
    if row["status"] == "active" and row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
        return "expired"
    return row["status"]


async def _resolve_target_org(conn: asyncpg.Connection, payload: CampaignGrantRequest) -> Dict[str, Any]:
    if payload.org_id:
        if not await verify_org_exists(conn, payload.org_id):
            raise HTTPException(status_code=404, detail=f"Organization not found: {payload.org_id}")
        org_row = await conn.fetchrow(
            """
            SELECT id AS org_id, name AS org_name, display_name AS org_display_name, plan_tier
            FROM organizations
            WHERE id = $1
            """,
            payload.org_id,
        )
        return dict(org_row)

    resolved = await resolve_org_by_user_identifier(conn, user_email=payload.user_email)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"No organization found for user_email={payload.user_email}")
    return resolved


async def _campaign_to_response(conn: asyncpg.Connection, row: asyncpg.Record) -> CampaignResponse:
    counts = await _campaign_counts(conn, str(row["id"]))
    app_names = await _feature_names(conn, list(row["app_feature_keys"] or []))
    return _campaign_row_to_response(row, app_names, counts)


@router.get("", response_model=List[CampaignResponse])
async def list_campaigns(admin_user: dict = Depends(require_admin_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM campaigns
            ORDER BY created_at DESC
            """
        )
        return [await _campaign_to_response(conn, row) for row in rows]


@router.post("", response_model=CampaignResponse)
async def create_campaign(
    campaign: CampaignCreate,
    admin_user: dict = Depends(require_admin_user),
):
    pool = await get_db_pool()
    admin_email = admin_user.get("email") or admin_user.get("user_id") or "unknown"
    slug = campaign.slug or _slugify(campaign.name)
    app_feature_keys = normalize_feature_keys(campaign.app_feature_keys)

    async with pool.acquire() as conn:
        duplicate = await conn.fetchval("SELECT 1 FROM campaigns WHERE slug = $1", slug)
        if duplicate:
            raise HTTPException(status_code=409, detail=f"Campaign slug already exists: {slug}")

        row = await conn.fetchrow(
            """
            INSERT INTO campaigns (
                slug, name, description, app_feature_keys, comp_tier_code,
                starts_at, ends_at, status, notes, created_by
            )
            VALUES ($1, $2, $3, $4, $5, COALESCE($6, CURRENT_TIMESTAMP), $7, $8, $9, $10)
            RETURNING *
            """,
            slug,
            campaign.name,
            campaign.description,
            app_feature_keys,
            campaign.comp_tier_code,
            campaign.starts_at,
            campaign.ends_at,
            campaign.status,
            campaign.notes,
            admin_email,
        )
        return await _campaign_to_response(conn, row)


@router.get("/summary", response_model=List[CampaignSummaryResponse])
async def campaigns_summary(admin_user: dict = Depends(require_admin_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM campaigns ORDER BY created_at DESC")
        results: List[CampaignSummaryResponse] = []
        for row in rows:
            counts = await _campaign_counts(conn, str(row["id"]))
            results.append(
                CampaignSummaryResponse(
                    id=str(row["id"]),
                    slug=row["slug"],
                    name=row["name"],
                    status=row["status"],
                    starts_at=row["starts_at"],
                    ends_at=row["ends_at"],
                    app_feature_keys=list(row["app_feature_keys"] or []),
                    app_names=await _feature_names(conn, list(row["app_feature_keys"] or [])),
                    minted_codes=int(counts["minted_codes"] or 0),
                    redeemed_codes=int(counts["redeemed_codes"] or 0),
                    active_grants=int(counts["active_grants"] or 0),
                    revoked_grants=int(counts["revoked_grants"] or 0),
                    expired_grants=int(counts["expired_grants"] or 0),
                )
            )
        return results


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: str, admin_user: dict = Depends(require_admin_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await _get_campaign(conn, campaign_id)
        return await _campaign_to_response(conn, row)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: str,
    campaign: CampaignUpdate,
    admin_user: dict = Depends(require_admin_user),
):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        existing = await _get_campaign(conn, campaign_id)

        slug = campaign.slug or existing["slug"]
        if campaign.name and not campaign.slug:
            slug = existing["slug"]

        if campaign.slug and campaign.slug != existing["slug"]:
            duplicate = await conn.fetchval(
                "SELECT 1 FROM campaigns WHERE slug = $1 AND id <> $2",
                campaign.slug,
                campaign_id,
            )
            if duplicate:
                raise HTTPException(status_code=409, detail=f"Campaign slug already exists: {campaign.slug}")

        app_feature_keys = list(existing["app_feature_keys"] or [])
        if campaign.app_feature_keys is not None:
            app_feature_keys = normalize_feature_keys(campaign.app_feature_keys)

        row = await conn.fetchrow(
            """
            UPDATE campaigns
            SET
                slug = $1,
                name = COALESCE($2, name),
                description = COALESCE($3, description),
                app_feature_keys = $4,
                comp_tier_code = COALESCE($5, comp_tier_code),
                starts_at = COALESCE($6, starts_at),
                ends_at = COALESCE($7, ends_at),
                status = COALESCE($8, status),
                notes = COALESCE($9, notes)
            WHERE id = $10
            RETURNING *
            """,
            slug,
            campaign.name,
            campaign.description,
            app_feature_keys,
            campaign.comp_tier_code,
            campaign.starts_at,
            campaign.ends_at,
            campaign.status,
            campaign.notes,
            campaign_id,
        )
        return await _campaign_to_response(conn, row)


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str, admin_user: dict = Depends(require_admin_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await _get_campaign(conn, campaign_id)
        await conn.execute(
            """
            UPDATE campaigns
            SET status = 'ended', ends_at = COALESCE(ends_at, CURRENT_TIMESTAMP)
            WHERE id = $1
            """,
            campaign_id,
        )
        logger.info("Campaign %s marked ended by %s", row["slug"], admin_user.get("email"))
        return {"success": True, "message": f"Campaign '{row['name']}' ended"}


@router.post("/{campaign_id}/grant", response_model=CampaignGrantResponse)
async def grant_campaign(
    campaign_id: str,
    payload: CampaignGrantRequest,
    admin_user: dict = Depends(require_admin_user),
):
    pool = await get_db_pool()
    admin_email = admin_user.get("email") or admin_user.get("user_id") or "unknown"
    async with pool.acquire() as conn:
        campaign = await _get_campaign(conn, campaign_id)
        target = await _resolve_target_org(conn, payload)
        org_id = str(target["org_id"])

        existing = await conn.fetchrow(
            """
            SELECT *
            FROM campaign_grants
            WHERE campaign_id = $1 AND org_id = $2 AND source = 'admin' AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            campaign_id,
            org_id,
        )

        if existing:
            await grant_feature_keys_to_org(
                conn,
                org_id,
                campaign["app_feature_keys"] or [],
                admin_email,
                campaign["notes"] or campaign["name"],
            )
            return CampaignGrantResponse(
                id=str(existing["id"]),
                campaign_id=str(existing["campaign_id"]),
                campaign_name=campaign["name"],
                org_id=str(existing["org_id"]),
                org_name=target.get("org_name"),
                org_display_name=target.get("org_display_name"),
                user_id=existing["user_id"],
                user_email=target.get("user_email") or payload.user_email,
                granted_feature_keys=list(existing["granted_feature_keys"] or []),
                comp_tier_code=existing["comp_tier_code"],
                source=existing["source"],
                status=existing["status"],
                expires_at=existing["expires_at"],
                created_at=existing["created_at"],
                created_by=existing["created_by"],
            )

        await grant_feature_keys_to_org(
            conn,
            org_id,
            campaign["app_feature_keys"] or [],
            admin_email,
            campaign["notes"] or campaign["name"],
        )

        if campaign["comp_tier_code"]:
            await conn.execute(
                "UPDATE organizations SET plan_tier = $1 WHERE id = $2",
                campaign["comp_tier_code"],
                org_id,
            )

        row = await conn.fetchrow(
            """
            INSERT INTO campaign_grants (
                campaign_id, org_id, user_id, granted_feature_keys,
                comp_tier_code, source, status, expires_at, created_by
            )
            VALUES ($1, $2, $3, $4, $5, 'admin', 'active', $6, $7)
            RETURNING *
            """,
            campaign_id,
            org_id,
            target.get("user_id"),
            campaign["app_feature_keys"] or [],
            campaign["comp_tier_code"],
            payload.expires_at,
            admin_email,
        )
        return CampaignGrantResponse(
            id=str(row["id"]),
            campaign_id=str(row["campaign_id"]),
            campaign_name=campaign["name"],
            org_id=str(row["org_id"]),
            org_name=target.get("org_name"),
            org_display_name=target.get("org_display_name"),
            user_id=row["user_id"],
            user_email=target.get("user_email") or payload.user_email,
            granted_feature_keys=list(row["granted_feature_keys"] or []),
            comp_tier_code=row["comp_tier_code"],
            source=row["source"],
            status=row["status"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )


@router.post("/{campaign_id}/revoke", response_model=CampaignGrantResponse)
async def revoke_campaign(
    campaign_id: str,
    payload: CampaignGrantRequest,
    admin_user: dict = Depends(require_admin_user),
):
    pool = await get_db_pool()
    admin_email = admin_user.get("email") or admin_user.get("user_id") or "unknown"
    async with pool.acquire() as conn:
        campaign = await _get_campaign(conn, campaign_id)
        target = await _resolve_target_org(conn, payload)
        org_id = str(target["org_id"])

        row = await conn.fetchrow(
            """
            SELECT *
            FROM campaign_grants
            WHERE campaign_id = $1 AND org_id = $2 AND source = 'admin' AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            campaign_id,
            org_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Active campaign grant not found")

        await conn.execute(
            "UPDATE campaign_grants SET status = 'revoked' WHERE id = $1",
            row["id"],
        )

        remaining = await conn.fetch(
            """
            SELECT granted_feature_keys
            FROM campaign_grants
            WHERE org_id = $1 AND status = 'active' AND id <> $2
            """,
            org_id,
            row["id"],
        )
        remaining_features = set()
        for item in remaining:
            remaining_features.update(item["granted_feature_keys"] or [])

        # NOTE(known-limitation): org_features has no provenance column, so this cannot
        # tell a feature that was ALSO granted manually (via the org_features admin path)
        # from one this campaign added. If the same feature_key was manually granted, revoke
        # removes it. Acceptable for launch; add a source_campaign_id column if this collides.
        revoke_keys = [key for key in (campaign["app_feature_keys"] or []) if key not in remaining_features]
        if revoke_keys:
            await revoke_feature_keys_from_org(conn, org_id, revoke_keys)

        logger.info("Campaign %s revoked for org %s by %s", campaign["slug"], org_id, admin_email)

        return CampaignGrantResponse(
            id=str(row["id"]),
            campaign_id=str(row["campaign_id"]),
            campaign_name=campaign["name"],
            org_id=str(row["org_id"]),
            org_name=target.get("org_name"),
            org_display_name=target.get("org_display_name"),
            user_id=row["user_id"],
            user_email=target.get("user_email") or payload.user_email,
            granted_feature_keys=list(row["granted_feature_keys"] or []),
            comp_tier_code=row["comp_tier_code"],
            source=row["source"],
            status="revoked",
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )


@router.get("/{campaign_id}/grants", response_model=List[CampaignGrantResponse])
async def list_campaign_grants(campaign_id: str, admin_user: dict = Depends(require_admin_user)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        campaign = await _get_campaign(conn, campaign_id)
        rows = await conn.fetch(
            """
            SELECT
                cg.*,
                o.name AS org_name,
                o.display_name AS org_display_name,
                u.email AS user_email
            FROM campaign_grants cg
            JOIN organizations o ON cg.org_id = o.id
            LEFT JOIN users u ON cg.user_id IS NOT NULL AND (u.id::text = cg.user_id OR u.zitadel_id = cg.user_id)
            WHERE cg.campaign_id = $1
            ORDER BY cg.created_at DESC
            """,
            campaign_id,
        )
        return [
            CampaignGrantResponse(
                id=str(row["id"]),
                campaign_id=str(row["campaign_id"]),
                campaign_name=campaign["name"],
                org_id=str(row["org_id"]),
                org_name=row["org_name"],
                org_display_name=row["org_display_name"],
                user_id=row["user_id"],
                user_email=row["user_email"],
                granted_feature_keys=list(row["granted_feature_keys"] or []),
                comp_tier_code=row["comp_tier_code"],
                source=row["source"],
                status=_effective_grant_status(row),
                expires_at=row["expires_at"],
                created_at=row["created_at"],
                created_by=row["created_by"],
            )
            for row in rows
        ]


__all__ = ["router"]
