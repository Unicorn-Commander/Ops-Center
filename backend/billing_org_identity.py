"""Authorize billing identity against current active organization membership.

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
    """Read the deployed direct-sub schema before considering optional mapping."""
    direct_query = """
        SELECT DISTINCT om.org_id::text AS org_id, om.role
        FROM public.organization_members om
        JOIN public.organizations o ON o.id = om.org_id
        WHERE om.user_id = $1 AND o.status = 'active'
    """

    async def fetch_memberships(conn):
        rows = await conn.fetch(direct_query, subject)
        if rows:
            return rows
        # Some older installations have a local identity map. Introspect its
        # exact capability before parsing any query that references that table.
        # Dogfood/production without public."user" take the direct path safely.
        has_mapping = await conn.fetchval("""
            SELECT COUNT(*) = 2 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'user'
              AND column_name IN ('id', 'oauth_sub')
        """)
        if not has_mapping:
            return []
        return await conn.fetch("""
            SELECT DISTINCT om.org_id::text AS org_id, om.role
            FROM public."user" u
            JOIN public.organization_members om ON om.user_id = u.id::text
            JOIN public.organizations o ON o.id = om.org_id
            WHERE u.oauth_sub::text = $1 AND o.status = 'active'
        """, subject)

    if pool is not None:
        async with pool.acquire() as conn:
            return await fetch_memberships(conn)
    conn = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "unicorn"),
        password=os.getenv("POSTGRES_PASSWORD"),
        database=os.getenv("POSTGRES_DB", "unicorn_db"),
        timeout=5,
    )
    try:
        return await fetch_memberships(conn)
    finally:
        await conn.close()


async def resolve_billing_org(user, session=None, pool=None, *, require_write=False):
    """Authorize the selected org against current active persisted membership.

    Session/Keycloak attributes express selection, never membership or billing
    privilege. A sole membership can supply a missing selection. Mutation roles
    are taken only from that org's membership row, never global/session claims.
    """
    session = session or {}
    selected = [v for v in (user.get("org_id"), session.get("org_id")) if v]
    attr = (user.get("attributes") or {}).get("org_id")
    if attr:
        selected.extend(attr if isinstance(attr, list) else [attr])
    selected_org = None
    if selected:
        orgs = {lago_org_id(value) for value in selected}
        if len(orgs) != 1:
            raise HTTPException(409, "Conflicting organization context; select an organization")
        selected_org = orgs.pop()

    subject = user.get("sub") or user.get("user_id") or user.get("id")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(409, "Authenticated subject required for billing")
    try:
        rows = await _membership_orgs(subject, pool)
    except Exception:
        logger.warning("Billing organization membership lookup failed")
        raise HTTPException(503, "Organization lookup unavailable") from None
    memberships = {}
    for row in rows:
        org = lago_org_id(row["org_id"])
        memberships.setdefault(org, set()).add(str(row.get("role") or "").lower())
    if selected_org is not None:
        if selected_org not in memberships:
            raise HTTPException(403, "No active membership in selected organization")
    elif len(memberships) != 1:
        raise HTTPException(409, "Select an organization before billing")
    else:
        selected_org = next(iter(memberships))
    if require_write:
        roles = memberships[selected_org]
        # Conflicting duplicate rows must not silently grant a higher privilege.
        if len(roles) != 1 or not roles.issubset({"owner", "admin", "billing_admin"}):
            raise HTTPException(403, "Organization billing role required")
    return selected_org
