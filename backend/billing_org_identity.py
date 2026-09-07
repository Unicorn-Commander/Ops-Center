"""Resolve billing identity from trusted session context or persisted membership.

The uchub organization UUID is the identity; ``org_`` is only Lago's namespace.
Never derive an organization from an email, Stripe customer, or a new UUID.
"""
import logging
import os
from uuid import UUID

import asyncpg
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def lago_org_id(value):
    """Validate and normalize an existing organization UUID for Lago."""
    if not isinstance(value, str) or not value:
        raise HTTPException(409, "A canonical organization ID is required")
    raw = value[4:] if value.startswith("org_") else value
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError):
        raise HTTPException(409, "Invalid organization ID") from None
    if parsed.int == 0:
        raise HTTPException(409, "Invalid organization ID")
    return f"org_{parsed}"


async def _membership_orgs(subject, pool=None):
    # Memberships can use the uchub sub directly or the local user's primary key.
    # user_org_access is a view over these same membership rows. Do not join the
    # nonexistent `users` table, nor resolve identity through mutable email.
    query = '''
        WITH identities AS (
            SELECT $1::text AS id
            UNION
            SELECT id::text FROM "user" WHERE oauth_sub = $1 OR id::text = $1
        )
        SELECT DISTINCT om.org_id::text AS org_id
        FROM organization_members om
        JOIN organizations o ON o.id = om.org_id
        WHERE om.user_id::text IN (SELECT id FROM identities)
          AND COALESCE(o.status, 'active') = 'active'
    '''
    if pool is not None:
        async with pool.acquire() as conn:
            return await conn.fetch(query, subject)
    conn = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "unicorn"),
        password=os.getenv("POSTGRES_PASSWORD"),
        database=os.getenv("POSTGRES_DB", "unicorn_db"),
        timeout=5,
    )
    try:
        return await conn.fetch(query, subject)
    finally:
        await conn.close()


async def resolve_billing_org(user, session=None, pool=None):
    """Return one trusted selected org, or the sole persisted membership.

    Inputs must come from the authenticated server-side session, never request
    parameters. Missing/ambiguous identity fails closed before any billing call.
    """
    session = session or {}
    selected = [v for v in (user.get("org_id"), session.get("org_id")) if v]
    attr = user.get("attributes", {}).get("org_id")
    if attr:
        selected.extend(attr if isinstance(attr, list) else [attr])
    if selected:
        orgs = {lago_org_id(value) for value in selected}
        if len(orgs) != 1:
            raise HTTPException(409, "Conflicting organization context; select an organization")
        return orgs.pop()

    subject = user.get("sub") or user.get("user_id") or user.get("id")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(409, "Select an organization before billing")
    try:
        rows = await _membership_orgs(subject, pool)
    except Exception:
        logger.warning("Billing organization membership lookup failed")
        raise HTTPException(503, "Organization lookup unavailable") from None
    orgs = {lago_org_id(row["org_id"]) for row in rows}
    if len(orgs) != 1:
        raise HTTPException(409, "Select an organization before billing")
    return orgs.pop()
