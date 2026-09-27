"""
Shared helpers for entitlement-bearing feature grants.

This module centralizes the org-feature insert/delete SQL used by org feature admin
actions, campaign grants, and campaign-scoped invite redemptions.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import asyncpg


def normalize_feature_keys(feature_keys: Iterable[str]) -> List[str]:
    """Return a stable list of unique, non-empty feature keys."""
    seen = set()
    normalized: List[str] = []
    for key in feature_keys:
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


async def verify_org_exists(conn: asyncpg.Connection, org_id: str) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM organizations WHERE id = $1)",
            org_id,
        )
    )


async def resolve_org_by_user_email(
    conn: asyncpg.Connection,
    user_email: str,
) -> Optional[dict]:
    """Resolve the primary org for a user email."""
    if not user_email:
        return None

    row = await conn.fetchrow(
        """
        SELECT
            o.id AS org_id,
            o.name AS org_name,
            o.display_name AS org_display_name,
            o.plan_tier,
            u.id::text AS user_id,
            u.email AS user_email
        FROM users u
        JOIN organization_members om ON u.id::text = om.user_id
        JOIN organizations o ON om.org_id = o.id
        WHERE lower(u.email) = lower($1)
        ORDER BY om.is_default DESC, om.joined_at ASC
        LIMIT 1
        """,
        user_email,
    )
    return dict(row) if row else None


async def resolve_org_by_user_identifier(
    conn: asyncpg.Connection,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> Optional[dict]:
    """Resolve the primary org for a user id or email."""
    if user_id:
        row = await conn.fetchrow(
            """
            SELECT
                o.id AS org_id,
                o.name AS org_name,
                o.display_name AS org_display_name,
                o.plan_tier,
                u.id::text AS user_id,
                u.email AS user_email
            FROM users u
            JOIN organization_members om ON u.id::text = om.user_id
            JOIN organizations o ON om.org_id = o.id
            WHERE u.id::text = $1 OR u.zitadel_id = $1
            ORDER BY om.is_default DESC, om.joined_at ASC
            LIMIT 1
            """,
            user_id,
        )
        if row:
            return dict(row)

    if user_email:
        return await resolve_org_by_user_email(conn, user_email)

    return None


async def grant_feature_keys_to_org(
    conn: asyncpg.Connection,
    org_id: str,
    feature_keys: Sequence[str],
    granted_by: str,
    notes: Optional[str] = None,
) -> List[dict]:
    """Upsert the given feature keys into org_features for an org."""
    normalized = normalize_feature_keys(feature_keys)
    if not normalized:
        return []

    rows: List[dict] = []
    for feature_key in normalized:
        row = await conn.fetchrow(
            """
            INSERT INTO org_features (org_id, feature_key, enabled, granted_by, notes)
            VALUES ($1, $2, TRUE, $3, $4)
            ON CONFLICT (org_id, feature_key)
            DO UPDATE SET
                enabled = TRUE,
                granted_by = EXCLUDED.granted_by,
                granted_at = CURRENT_TIMESTAMP,
                notes = EXCLUDED.notes
            RETURNING id, org_id, feature_key, enabled, granted_by, granted_at, notes
            """,
            org_id,
            feature_key,
            granted_by,
            notes,
        )
        rows.append(dict(row))
    return rows


async def revoke_feature_keys_from_org(
    conn: asyncpg.Connection,
    org_id: str,
    feature_keys: Sequence[str],
) -> int:
    """Delete the given feature keys from org_features for an org."""
    normalized = normalize_feature_keys(feature_keys)
    if not normalized:
        return 0

    result = await conn.execute(
        """
        DELETE FROM org_features
        WHERE org_id = $1 AND feature_key = ANY($2::text[])
        """,
        org_id,
        list(normalized),
    )
    return int(result.split()[-1])
