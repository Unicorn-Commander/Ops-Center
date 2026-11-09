"""
Organization Management API Endpoints
Provides organization CRUD operations, member management, and settings
"""

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.responses import JSONResponse
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
import logging
from datetime import datetime, timedelta, timezone
import sys
import os
import asyncpg

# Add parent directory to path to import from server.py
if '/app' not in sys.path:
    sys.path.insert(0, '/app')

# NOTE: org listing/detail/members/create now read & write the Postgres
# organizations / organization_members tables (the real source of truth) rather
# than the orphaned org_manager JSON store. org_manager.py is intentionally left
# in place (other modules may import it) but is no longer used here.

# Import Keycloak user operations.  Invited users are keyed by their Keycloak
# subject, which is the same identity stored in organization_members.
from keycloak_integration import (
    create_user as keycloak_create_user,
    get_user_by_email,
    get_user_by_id,
    send_account_action_email,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/org", tags=["organizations"])

# Only the paid self-serve tiers enforce a seat cap on the invite path. Free and
# internally assigned tiers keep production's uncapped behavior.
SEAT_CAPPED_PLAN_TIERS = frozenset({"founder_workspace", "byok"})
VALID_ORG_ROLES = frozenset({"owner", "admin", "member", "billing_admin"})
DASHBOARD_CURSOR_ACTION = "dashboard_last_seen"
DASHBOARD_CURSOR_FUTURE_SKEW = timedelta(minutes=5)
# GET /my-orgs names the organization the backend serves this request as, so
# the page can show the same one. The body stays a plain list for every
# existing consumer.
CURRENT_ORG_HEADER = "X-Current-Org-Id"
# Session role names for a platform operator. An organization admin is a
# membership role, not one of these, and a bare is_admin flag is not enough:
# power users are marked is_admin and must not take the immediate-membership path.
_PLATFORM_ADMIN_ROLES = frozenset({
    "admin",
    "super_admin",
    "platform_admin",
    "system_admin",
})


# ==================== Database Connection ====================

async def get_db_connection():
    """
    Create a connection to the Postgres database that holds the real
    organizations / organization_members tables. Mirrors org_access_api.py.
    """
    return await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "unicorn"),
        password=os.getenv("POSTGRES_PASSWORD", "unicorn"),
        database=os.getenv("POSTGRES_DB", "unicorn_db")
    )


async def _get_org_row(conn, org_id: str) -> Optional[asyncpg.Record]:
    """Fetch a single organization row by id (bare UUID) from Postgres."""
    return await conn.fetchrow(
        """
        SELECT
            o.id::text AS id,
            o.name,
            o.display_name,
            o.plan_tier,
            o.status,
            o.max_seats,
            o.created_at,
            o.lago_customer_id,
            o.stripe_customer_id,
            COALESCE(st.tier_name, INITCAP(REPLACE(o.plan_tier, '_', ' '))) AS tier_name,
            o.max_seats AS seat_cap,
            COALESCE(st.team_seats, 1) AS included_seats
        FROM organizations o
        LEFT JOIN subscription_tiers st ON o.plan_tier = st.tier_code
        WHERE o.id::text = $1
        """,
        org_id,
    )


async def _get_org_members(conn, org_id: str) -> List[asyncpg.Record]:
    """Fetch organization_members rows for an org from Postgres."""
    return await conn.fetch(
        """
        SELECT user_id, role, joined_at
        FROM organization_members
        WHERE org_id::text = $1
        ORDER BY joined_at
        """,
        org_id,
    )


async def _get_user_role_in_org(conn, org_id: str, user_id: str) -> Optional[str]:
    """Return a user's role in an org (Postgres), or None if not a member."""
    row = await conn.fetchrow(
        """
        SELECT role FROM organization_members
        WHERE org_id::text = $1 AND user_id = $2
        """,
        org_id,
        user_id,
    )
    return row["role"] if row else None


# ==================== Request/Response Models ====================

class OrganizationMemberAdd(BaseModel):
    """Request model for adding a member to organization"""
    # ``user_id`` remains optional for the legacy caller.  The console uses
    # email-based invitations and resolves the Keycloak subject below.
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: str = "member"
    firstName: Optional[str] = None
    lastName: Optional[str] = None


class DashboardCursorUpdate(BaseModel):
    """A rendered dashboard activity timestamp for the active user/org."""

    last_seen_at: datetime
    rendered: bool = False


class OrganizationMemberRoleUpdate(BaseModel):
    """Request model for updating member role"""
    role: str


class OrganizationSettingsUpdate(BaseModel):
    """Request model for updating organization settings"""
    settings: Dict[str, Any]


class OrganizationCreate(BaseModel):
    """Request model for creating a new organization"""
    name: str
    plan_tier: str = "free"


class OrganizationStatusUpdate(BaseModel):
    """Request model for suspending/activating an organization"""
    status: str  # 'active' | 'suspended'


# ==================== Helper Functions ====================

async def get_current_user(request: Request) -> Dict:
    """Get current user data from session (uses Redis session manager)"""
    from auth_dependencies import get_service_key_user

    service_key_user = await get_service_key_user(request)
    if service_key_user is not None:
        return service_key_user

    from redis_session import redis_session_manager

    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Get Redis connection info
    redis_host = os.getenv("REDIS_HOST", "unicorn-redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))

    # Reuse the startup-configured session manager.
    sessions = redis_session_manager

    # Get session data
    if session_token not in sessions:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    session_data = sessions[session_token]
    user = session_data.get("user", {})

    if not user:
        raise HTTPException(status_code=401, detail="User not found in session")

    # Ensure user_id field exists (map from Keycloak 'sub' field if needed)
    if "user_id" not in user:
        user["user_id"] = user.get("sub") or user.get("id", "unknown")

    # Ensure id field exists
    if "id" not in user:
        user["id"] = user.get("sub") or user.get("user_id", "unknown")

    return user


async def require_admin(request: Request) -> Dict:
    """Require admin role for endpoint access"""
    user = await get_current_user(request)

    # Check if user has admin role
    if not user.get("is_admin") and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return user


async def get_user_org_id(request: Request) -> str:
    """Get organization ID from user session"""
    user = await get_current_user(request)

    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    return org_id


async def verify_org_access(request: Request, org_id: str, required_role: Optional[str] = None):
    """
    Verify user has access to organization

    Args:
        request: FastAPI request object
        org_id: Organization ID to check access for
        required_role: Optional role requirement (owner, billing_admin, member)

    Raises:
        HTTPException: If user lacks access
    """
    user = await get_current_user(request)
    user_id = user.get("id") or user.get("sub") or user.get("user_id") or user.get("email")

    # Admins have access to all organizations
    if user.get("is_admin") or user.get("role") == "admin":
        return user

    # Check if user is member of organization (Postgres source of truth)
    conn = await get_db_connection()
    try:
        user_role = await _get_user_role_in_org(conn, org_id, user_id)
    finally:
        await conn.close()

    if not user_role:
        raise HTTPException(status_code=403, detail="You are not a member of this organization")

    # Check required role if specified
    if required_role:
        role_hierarchy = ["member", "billing_admin", "admin", "owner"]
        user_role_level = role_hierarchy.index(user_role) if user_role in role_hierarchy else -1
        required_role_level = role_hierarchy.index(required_role) if required_role in role_hierarchy else 99

        if user_role_level < required_role_level:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{required_role}' or higher required"
            )

    return user


def _platform_admin_ids() -> set:
    """User ids from UUDA_PLATFORM_ADMINS. The value is server config, not a token claim."""

    raw = os.getenv("UUDA_PLATFORM_ADMINS") or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def _session_role_names(user: Dict[str, Any]) -> set:
    names = set()
    role = user.get("role")
    if isinstance(role, str) and role.strip():
        names.add(role.strip())
    for key in ("roles",):
        roles = user.get(key)
        if isinstance(roles, (list, tuple, set)):
            names.update(str(item).strip() for item in roles if str(item).strip())
    realm = user.get("realm_access")
    if isinstance(realm, dict):
        realm_roles = realm.get("roles")
        if isinstance(realm_roles, (list, tuple, set)):
            names.update(str(item).strip() for item in realm_roles if str(item).strip())
    return names


def _is_platform_admin(user: Dict[str, Any]) -> bool:
    """Return whether this authenticated session is a platform operator.

    A boolean is_admin or platform_admin claim does not qualify, because power
    users are stored with is_admin and must not create a Keycloak user from
    this route.
    """

    user_ids = {
        str(user.get(key)).strip()
        for key in ("id", "sub", "user_id")
        if user.get(key)
    }
    if user_ids & _platform_admin_ids():
        return True
    return bool(_session_role_names(user) & _PLATFORM_ADMIN_ROLES)


def _pending_invites_enabled() -> bool:
    """Return whether the opt-in first-sign-in invitation flow is enabled."""

    return (os.getenv("ORG_INVITES_PENDING") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _is_missing_relation(exc: BaseException) -> bool:
    """True when invitation or cursor storage has not been migrated yet."""

    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate in {"42P01", "42703"}:
        return True
    undefined = tuple(
        err
        for err in (
            getattr(asyncpg, "UndefinedTableError", None),
            getattr(asyncpg, "UndefinedColumnError", None),
        )
        if isinstance(err, type)
    )
    return bool(undefined) and isinstance(exc, undefined)


def _session_user_id(user: Dict[str, Any]) -> Optional[str]:
    return user.get("id") or user.get("sub") or user.get("user_id") or user.get("email")


def _session_email(user: Dict[str, Any]) -> Optional[str]:
    email = user.get("email") or user.get("preferred_username")
    return email.strip().lower() if isinstance(email, str) and email.strip() else None


def _as_utc(value: datetime) -> datetime:
    """Normalize naive fixture timestamps and DB timestamps to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _seat_cap_from_org(org: Dict[str, Any]) -> Optional[int]:
    """Return the seat cap for a capped plan, or None when the plan is uncapped."""

    if org.get("plan_tier") not in SEAT_CAPPED_PLAN_TIERS:
        return None
    try:
        persisted_max_seats = int(org["max_seats"] or 1)
    except (KeyError, TypeError, ValueError):
        persisted_max_seats = int(org.get("seat_cap") or 1)
    try:
        included_seats = int(org["included_seats"] or 1)
    except (KeyError, TypeError, ValueError):
        included_seats = 1
    return max(persisted_max_seats, included_seats, 1)


async def _org_has_seat_room(conn, org_id: str) -> bool:
    """True when one more member fits. Pending invites are not counted here.

    A pending invite already reserved a seat at creation. Accepting it swaps
    that reservation for a membership. If members already fill the cap, another
    member was added in the meantime and this invite stays pending.
    """

    org = await _get_org_row(conn, org_id)
    if not org:
        return False
    seat_cap = _seat_cap_from_org(org)
    if seat_cap is None:
        return True
    member_count = await conn.fetchval(
        "SELECT COUNT(*) FROM organization_members WHERE org_id::text = $1",
        org_id,
    )
    return int(member_count or 0) < seat_cap


async def _pending_invitation_count(conn, org_id: str) -> int:
    """Count unexpired pending invitations that reserve organization seats."""

    if not _pending_invites_enabled():
        return 0

    count = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM organization_invitations
        WHERE org_id::text = $1
          AND accepted = FALSE
          AND expires_at > CURRENT_TIMESTAMP
        """,
        org_id,
    )
    return int(count or 0)


async def _accept_pending_invitations(conn, user: Dict[str, Any]) -> int:
    """Accept active invitations matching the signed-in user's email.

    The organization list is the first authenticated org request made by the
    home context, so accepting here binds the pending invite to the real
    Keycloak subject without creating an identity in the invite endpoint.
    """

    if not _pending_invites_enabled():
        return 0

    user_id = _session_user_id(user)
    email = _session_email(user)
    if not user_id or not email:
        return 0

    accepted_count = 0
    async with conn.transaction():
        invitations = await conn.fetch(
            """
            SELECT id, org_id::text AS org_id, role
            FROM organization_invitations
            WHERE LOWER(email) = LOWER($1)
              AND accepted = FALSE
              AND expires_at > CURRENT_TIMESTAMP
            ORDER BY created_at
            """,
            email,
        )
        for invitation in invitations:
            existing = await conn.fetchrow(
                """
                SELECT 1
                FROM organization_members
                WHERE org_id::text = $1 AND user_id = $2
                """,
                invitation["org_id"],
                str(user_id),
            )
            if not existing:
                # Leave the invite pending when the cap is already full so
                # accept cannot add a member the invite endpoint would refuse.
                if not await _org_has_seat_room(conn, invitation["org_id"]):
                    continue
                await conn.execute(
                    """
                    INSERT INTO organization_members (org_id, user_id, role)
                    VALUES ($1::uuid, $2, $3)
                    ON CONFLICT (org_id, user_id) DO NOTHING
                    """,
                    invitation["org_id"],
                    str(user_id),
                    invitation["role"],
                )

            await conn.execute(
                """
                UPDATE organization_invitations
                SET accepted = TRUE, accepted_at = CURRENT_TIMESTAMP
                WHERE id = $1 AND accepted = FALSE
                """,
                invitation["id"],
            )
            accepted_count += 1

    if accepted_count:
        logger.info("Accepted %d pending organization invitation(s)", accepted_count)
    return accepted_count


# ==================== API Endpoints ====================

@router.get("/my-orgs")
async def get_my_organizations(request: Request, response: Response = None):
    """
    Get list of organizations the current user is a member of

    Returns:
        List of organizations with user's role in each

    Headers:
        X-Current-Org-Id: the organization this request is served as, by the
        rule GET /api/v1/my-apps/authorized uses (the current_org_id cookie
        when it names an active membership, else the session org or the
        default membership). Absent when there is none, or when the cookie
        names an organization this user does not belong to.

    Example:
        GET /api/v1/org/my-orgs
        Response: [
            {
                "id": "org_12345",
                "name": "Magic Unicorn",
                "role": "owner",
                "plan_tier": "professional",
                "status": "active",
                "member_count": 5,
                "joined_at": "2025-01-15T10:30:00Z"
            },
            ...
        ]
    """
    user = await get_current_user(request)
    user_id = user.get("id") or user.get("sub") or user.get("user_id")

    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found in session")

    # Query Postgres for organizations the user is a member of, with per-org
    # member counts and the user's role in each.
    conn = await get_db_connection()
    try:
        if _pending_invites_enabled():
            # The org list is loaded immediately after authentication by the
            # home context. Accepting here makes a pending invitation take
            # effect on first sign-in without putting membership creation in
            # the invite path.
            try:
                await _accept_pending_invitations(conn, user)
            except Exception as exc:
                # Existing members can still load their organizations when the
                # invitations table or one of its columns is not there yet.
                if not _is_missing_relation(exc):
                    raise
                logger.warning(
                    "Pending invitation storage is unavailable; organization list continues without it"
                )
        rows = await conn.fetch(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (o.id)
                    o.id::text AS id,
                    o.name,
                    om.role,
                    o.plan_tier,
                    o.status,
                    om.joined_at,
                    (SELECT COUNT(*) FROM organization_members m WHERE m.org_id = o.id) AS member_count
                FROM organization_members om
                JOIN organizations o ON om.org_id = o.id
                LEFT JOIN users u ON u.id::text = om.user_id
                -- Keycloak subject directly, or a legacy users.id mapped via zitadel_id
                WHERE (om.user_id = $1 OR u.zitadel_id = $1)
                ORDER BY o.id, COALESCE(om.is_default, FALSE) DESC, om.joined_at ASC
            ) mine
            ORDER BY name
            """,
            user_id,
        )
    finally:
        await conn.close()

    user_orgs = [
        {
            "id": row["id"],
            "name": row["name"],
            "role": row["role"],
            "plan_tier": row["plan_tier"],
            "status": row["status"],
            "member_count": row["member_count"],
            "joined_at": row["joined_at"].isoformat() if row["joined_at"] else None,
        }
        for row in rows
    ]

    logger.info(f"Found {len(user_orgs)} organizations for user {user_id}")

    # FastAPI always passes the response for an HTTP request. Direct callers
    # (unit tests, the Postgres regression script) pass only the request.
    if response is not None:
        # Resolved after the list so an invitation accepted above counts.
        from my_apps_api import get_user_org_from_session

        current_org_id = await get_user_org_from_session(request)
        if current_org_id:
            response.headers[CURRENT_ORG_HEADER] = str(current_org_id)

    return user_orgs


@router.get("/organizations")
async def list_all_organizations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    tier: Optional[str] = None,
    search: Optional[str] = None
):
    """
    Get list of all organizations (admin only)

    Args:
        request: FastAPI request object
        limit: Maximum number of organizations to return (default: 50)
        offset: Number of organizations to skip for pagination (default: 0)
        status: Filter by status (active, suspended, deleted)
        tier: Filter by subscription tier
        search: Search by organization name

    Returns:
        List of organizations with member counts and metadata

    Example:
        GET /api/v1/org/organizations?limit=10&status=active
        Response: {
            "organizations": [
                {
                    "id": "org_12345",
                    "name": "Acme Corp",
                    "owner": "owner@example.com",
                    "member_count": 5,
                    "created_at": "2025-01-15T10:30:00Z",
                    "subscription_tier": "professional",
                    "status": "active",
                    "lago_customer_id": "lago_cust_abc",
                    "stripe_customer_id": "cus_xyz"
                },
                ...
            ],
            "total": 100,
            "limit": 10,
            "offset": 0
        }
    """
    # Require admin access
    await require_admin(request)

    conn = await get_db_connection()
    try:
        # Build a filtered query against the real Postgres organizations table.
        # member_count is computed per-org; the owner's user_id is resolved here
        # and turned into an email/username via Keycloak below.
        where_clauses = []
        params: List[Any] = []
        param_num = 1

        if status:
            where_clauses.append(f"o.status = ${param_num}")
            params.append(status)
            param_num += 1

        if tier:
            where_clauses.append(f"o.plan_tier = ${param_num}")
            params.append(tier)
            param_num += 1

        if search:
            where_clauses.append(f"o.name ILIKE ${param_num}")
            params.append(f"%{search}%")
            param_num += 1

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Total count (pre-pagination)
        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS total FROM organizations o {where_sql}",
            *params,
        )
        total = total_row["total"] if total_row else 0

        # Page of organizations with member count + owner user_id
        list_params = list(params)
        list_sql = f"""
            SELECT
                o.id::text AS id,
                o.name,
                o.plan_tier,
            o.status,
            o.max_seats,
            o.created_at,
                o.lago_customer_id,
                o.stripe_customer_id,
                (SELECT COUNT(*) FROM organization_members m WHERE m.org_id = o.id) AS member_count,
                (SELECT m.user_id FROM organization_members m
                   WHERE m.org_id = o.id AND m.role = 'owner'
                   ORDER BY m.joined_at LIMIT 1) AS owner_user_id
            FROM organizations o
            {where_sql}
            ORDER BY o.name
            LIMIT ${param_num} OFFSET ${param_num + 1}
        """
        list_params.extend([limit, offset])
        org_rows = await conn.fetch(list_sql, *list_params)

        # Enrich owner user_id -> email/username via Keycloak
        enriched_orgs = []
        for row in org_rows:
            owner_display = "Unknown"
            owner_user_id = row["owner_user_id"]
            if owner_user_id:
                try:
                    user_data = await get_user_by_id(owner_user_id)
                    if user_data:
                        owner_display = user_data.get("email") or user_data.get("username") or owner_user_id
                    else:
                        owner_display = owner_user_id
                except Exception as e:
                    logger.warning(f"Failed to fetch user info for owner {owner_user_id}: {e}")
                    owner_display = owner_user_id  # Fallback to user_id

            created_at = row["created_at"]
            enriched_orgs.append({
                "id": row["id"],
                "name": row["name"],
                "owner": owner_display,
                "member_count": row["member_count"],
                "created_at": created_at.isoformat() if created_at else None,
                "subscription_tier": row["plan_tier"],
                "status": row["status"],
                "lago_customer_id": row["lago_customer_id"],
                "stripe_customer_id": row["stripe_customer_id"]
            })

        logger.info(f"Listed {len(enriched_orgs)} organizations (total: {total}, filters: status={status}, tier={tier}, search={search})")

        return {
            "organizations": enriched_orgs,
            "total": total,
            "limit": limit,
            "offset": offset
        }

    except asyncpg.PostgresError as e:
        logger.error(f"Database error listing organizations: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list organizations: {str(e)}")
    except Exception as e:
        logger.error(f"Error listing organizations: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list organizations: {str(e)}")
    finally:
        await conn.close()


@router.post("")
async def create_organization(
    org_data: OrganizationCreate,
    request: Request
):
    """
    Create a new organization

    Args:
        org_data: Organization name and plan tier
        request: FastAPI request object

    Returns:
        Created organization details including ID and owner info

    Example:
        POST /api/v1/org
        Body: {"name": "Acme Corp", "plan_tier": "free"}
        Response: {
            "success": true,
            "organization": {
                "id": "org_12345",
                "name": "Acme Corp",
                "plan_tier": "free",
                "status": "active",
                "created_at": "2025-10-28T10:30:00Z",
                "owner": "admin@example.com",
                "member_count": 1
            }
        }
    """
    requested_tier = org_data.plan_tier.strip()

    # Self-serve organization creation is always free. Any paid, managed, or
    # invite-only tier must go through the existing platform-admin guard so a
    # client bug cannot silently turn into an entitlement grant.
    if requested_tier == "free":
        user = await get_current_user(request)
    else:
        try:
            user = await require_admin(request)
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            raise HTTPException(
                status_code=403,
                detail="Only platform admins may create organizations with a non-free plan_tier",
            ) from exc

    # Get current user. Prefer the Keycloak subject UUID (matches how
    # organization_members.user_id is stored elsewhere) and fall back to email.
    user_id = user.get("id") or user.get("sub") or user.get("user_id") or user.get("email")

    if not user_id:
        raise HTTPException(status_code=400, detail="Could not identify user")

    conn = await get_db_connection()
    try:
        if requested_tier != "free":
            tier_row = await conn.fetchrow(
                "SELECT tier_code FROM subscription_tiers WHERE tier_code = $1",
                requested_tier,
            )
            if not tier_row:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown organization plan_tier '{requested_tier}'",
                )

        # Reject duplicate org name (organizations.name has a UNIQUE constraint)
        existing = await conn.fetchrow(
            "SELECT 1 FROM organizations WHERE LOWER(name) = LOWER($1)",
            org_data.name.strip(),
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Organization with name '{org_data.name}' already exists"
            )

        # Insert the organization and add the creator as owner in one transaction.
        async with conn.transaction():
            org_row = await conn.fetchrow(
                """
                INSERT INTO organizations (name, plan_tier, status)
                VALUES ($1, $2, 'active')
                RETURNING id::text AS id, name, plan_tier, status, created_at,
                          lago_customer_id, stripe_customer_id
                """,
                org_data.name.strip(),
                requested_tier,
            )

            await conn.execute(
                """
                INSERT INTO organization_members (org_id, user_id, role, is_default)
                VALUES ($1::uuid, $2, 'owner', TRUE)
                """,
                org_row["id"],
                user_id,
            )

        logger.info(f"Created organization {org_row['id']} ({org_data.name}) with owner {user_id}")

        created_at = org_row["created_at"]
        return {
            "success": True,
            "organization": {
                "id": org_row["id"],
                "name": org_row["name"],
                "plan_tier": org_row["plan_tier"],
                "status": org_row["status"],
                "created_at": created_at.isoformat() if created_at else None,
                "owner": user_id,
                "member_count": 1,
                "lago_customer_id": org_row["lago_customer_id"],
                "stripe_customer_id": org_row["stripe_customer_id"]
            }
        }

    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"Database error creating organization: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create organization: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating organization: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create organization: {str(e)}")
    finally:
        await conn.close()


@router.put("/{org_id}/status")
async def update_organization_status(
    org_id: str,
    status_data: OrganizationStatusUpdate,
    request: Request
):
    """
    Suspend or activate an organization (admin only).

    Args:
        org_id: Organization ID
        status_data: {"status": "active" | "suspended"}

    Returns:
        Updated organization status

    Example:
        PUT /api/v1/org/org_12345/status
        Body: {"status": "suspended"}
        Response: {"success": true, "id": "org_12345", "name": "Acme", "status": "suspended"}
    """
    # Require platform admin (same guard as the admin organizations list)
    admin = await require_admin(request)

    new_status = (status_data.status or "").strip().lower()
    # 'deleted' is reserved for the delete flow; the toggle only moves between
    # active and suspended (organizations.status CHECK allows all three).
    if new_status not in ("active", "suspended"):
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Must be 'active' or 'suspended'."
        )

    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            UPDATE organizations
            SET status = $2
            WHERE id::text = $1
            RETURNING id::text AS id, name, status
            """,
            org_id,
            new_status,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Organization not found")

        logger.info(
            f"Org {org_id} ({row['name']}) status set to '{new_status}' "
            f"by admin {admin.get('email') or admin.get('user_id')}"
        )

        return {
            "success": True,
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
        }

    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"Database error updating status for org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update status: {str(e)}")
    except Exception as e:
        logger.error(f"Error updating status for org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update status: {str(e)}")
    finally:
        await conn.close()


@router.delete("/{org_id}")
async def delete_organization(
    org_id: str,
    request: Request,
    confirm: bool = False
):
    """
    Permanently delete an organization (admin only).

    Requires `?confirm=true` (sent by the frontend after its confirmation
    dialog). This is a hard delete: organization_members / quotas /
    invitations / settings / audit rows are removed via ON DELETE CASCADE.

    Example:
        DELETE /api/v1/org/org_12345?confirm=true
        Response: {"success": true, "id": "org_12345", "name": "Acme", "members_removed": 3}
    """
    # Require platform admin (same guard as the admin organizations list)
    admin = await require_admin(request)

    conn = await get_db_connection()
    try:
        org = await _get_org_row(conn, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Organization deletion requires confirm=true. "
                       "This permanently removes the organization and all its memberships."
            )

        member_count_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM organization_members WHERE org_id::text = $1",
            org_id,
        )
        member_count = member_count_row["n"] if member_count_row else 0

        # Hard delete; membership/quota/invitation/settings/audit rows cascade
        # (organization_* tables declare ON DELETE CASCADE on org_id).
        await conn.execute("DELETE FROM organizations WHERE id::text = $1", org_id)

        logger.info(
            f"Org {org_id} ({org['name']}) DELETED by admin "
            f"{admin.get('email') or admin.get('user_id')} "
            f"({member_count} membership rows cascaded)"
        )

        return {
            "success": True,
            "message": f"Organization '{org['name']}' deleted",
            "id": org_id,
            "name": org["name"],
            "members_removed": member_count,
        }

    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"Database error deleting org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete organization: {str(e)}")
    except Exception as e:
        logger.error(f"Error deleting org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete organization: {str(e)}")
    finally:
        await conn.close()


@router.get("/roles")
async def list_available_roles():
    """
    Get list of available organization roles

    Returns:
        List of roles with descriptions and permissions

    Example:
        GET /api/v1/org/roles
        Response: {
            "roles": [
                {
                    "id": "owner",
                    "name": "Owner",
                    "description": "Full organization control",
                    "permissions": ["manage_members", "manage_billing", "manage_settings", "delete_org"]
                },
                ...
            ]
        }
    """
    roles = [
        {
            "id": "owner",
            "name": "Owner",
            "description": "Full organization control including member management and billing",
            "permissions": [
                "manage_members",
                "manage_billing",
                "manage_settings",
                "delete_org",
                "view_all"
            ]
        },
        {
            "id": "billing_admin",
            "name": "Billing Admin",
            "description": "Manage billing and view organization details",
            "permissions": [
                "manage_billing",
                "view_all"
            ]
        },
        {
            "id": "member",
            "name": "Member",
            "description": "Basic organization member with view access",
            "permissions": [
                "view_all"
            ]
        }
    ]

    return {"roles": roles}


@router.get("/{org_id}/members")
async def list_organization_members(
    org_id: str,
    request: Request,
    offset: int = 0,
    limit: int = 100,
    search: str = ""
):
    """
    Get list of all members in an organization with full user details

    Args:
        org_id: Organization ID
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 100, max: 1000)
        search: Search by email, username, or name

    Returns:
        List of organization members with roles, join dates, and user details from Keycloak

    Example:
        GET /api/v1/org/org_12345/members?offset=0&limit=10&search=aaron
        Response: {
            "members": [
                {
                    "id": "7a6bfd31-0120-4a30-9e21-0fc3b8006579",
                    "user_id": "7a6bfd31-0120-4a30-9e21-0fc3b8006579",
                    "email": "aaron@magicunicorn.tech",
                    "username": "aaron",
                    "firstName": "Aaron",
                    "lastName": "User",
                    "org_role": "owner",
                    "enabled": true,
                    "emailVerified": true,
                    "createdAt": "2025-01-15T10:30:00Z"
                },
                ...
            ],
            "total": 5,
            "offset": 0,
            "limit": 10
        }
    """
    # Verify user has access to this organization
    await verify_org_access(request, org_id)

    # Get organization + members from Postgres (real source of truth)
    conn = await get_db_connection()
    try:
        org = await _get_org_row(conn, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        members = await _get_org_members(conn, org_id)
    finally:
        await conn.close()

    # Enrich members with Keycloak user data
    enriched_members = []
    for member in members:
        member_user_id = member["user_id"]
        member_role = member["role"]
        joined_at = member["joined_at"]
        joined_iso = joined_at.isoformat() if joined_at else None
        try:
            # Fetch user details from Keycloak
            user_data = await get_user_by_id(member_user_id)

            if user_data:
                enriched_member = {
                    "id": member_user_id,
                    "user_id": member_user_id,
                    "email": user_data.get("email", ""),
                    "username": user_data.get("username", ""),
                    "firstName": user_data.get("firstName", ""),
                    "lastName": user_data.get("lastName", ""),
                    "org_role": member_role,
                    "enabled": user_data.get("enabled", False),
                    "emailVerified": user_data.get("emailVerified", False),
                    "createdAt": joined_iso
                }
                enriched_members.append(enriched_member)
            else:
                # Fallback if Keycloak lookup fails
                logger.warning(f"Could not fetch Keycloak data for user {member_user_id}")
                enriched_members.append({
                    "id": member_user_id,
                    "user_id": member_user_id,
                    "email": member_user_id,  # Fallback to user_id
                    "username": member_user_id,
                    "firstName": "",
                    "lastName": "",
                    "org_role": member_role,
                    "enabled": True,
                    "emailVerified": False,
                    "createdAt": joined_iso
                })
        except Exception as e:
            logger.error(f"Error enriching member {member_user_id}: {e}")
            # Include basic data even if enrichment fails
            enriched_members.append({
                "id": member_user_id,
                "user_id": member_user_id,
                "email": member_user_id,
                "username": member_user_id,
                "firstName": "",
                "lastName": "",
                "org_role": member_role,
                "enabled": True,
                "emailVerified": False,
                "createdAt": joined_iso
            })

    # Apply search filter if provided
    if search:
        search_lower = search.lower()
        enriched_members = [
            m for m in enriched_members
            if search_lower in m.get("email", "").lower()
            or search_lower in m.get("username", "").lower()
            or search_lower in m.get("firstName", "").lower()
            or search_lower in m.get("lastName", "").lower()
        ]

    # Get total count before pagination
    total = len(enriched_members)

    # Apply pagination
    enriched_members = enriched_members[offset:offset + limit]

    logger.info(f"Listed {len(enriched_members)} members (total: {total}) for org {org_id}")

    return {
        "members": enriched_members,
        "total": total,
        "offset": offset,
        "limit": limit
    }


@router.post("/{org_id}/members")
async def add_organization_member(
    org_id: str,
    member_data: OrganizationMemberAdd,
    request: Request
):
    """
    Add a member to the organization, optionally inviting by email.

    Args:
        org_id: Organization ID
        member_data: Legacy user ID or an email invitation and role

    Returns:
        Success confirmation

    Example:
        POST /api/v1/org/org_12345/members
        Body: {"email": "member@example.com", "role": "member"}
        Response: {
            "success": true,
            "message": "We emailed member@example.com an invitation and added them to org_12345.",
            "email": "member@example.com",
            "role": "member"
        }
    """
    actor = await get_current_user(request)
    platform_admin = _is_platform_admin(actor)
    pending_mode = _pending_invites_enabled() and not platform_admin

    # Owners and organization admins may invite. Billing admins can manage
    # billing, but cannot change membership. Pending invitations are an
    # explicit opt-in; platform admins retain their immediate path.
    if not platform_admin:
        await verify_org_access(request, org_id, required_role="admin")

    if member_data.role not in VALID_ORG_ROLES:
        raise HTTPException(status_code=422, detail="Invitation role is not valid")

    conn = await get_db_connection()
    try:
        # Verify organization exists
        org = await _get_org_row(conn, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        requested_email = (member_data.email or "").strip().lower() or None
        legacy_user_id = (member_data.user_id or "").strip() or None
        if not requested_email and not legacy_user_id:
            raise HTTPException(status_code=422, detail="email or user_id is required")

        if not platform_admin and not requested_email:
            raise HTTPException(
                status_code=422,
                detail="Team invitations require an email address.",
            )

        # Pending invitations reserve seats. A duplicate is reported before
        # the seat check so the person inviting gets an actionable message.
        if requested_email and pending_mode:
            pending = await conn.fetchrow(
                """
                SELECT id
                FROM organization_invitations
                WHERE org_id::text = $1
                  AND LOWER(email) = LOWER($2)
                  AND accepted = FALSE
                  AND expires_at > CURRENT_TIMESTAMP
                LIMIT 1
                """,
                org_id,
                requested_email,
            )
            if pending:
                raise HTTPException(
                    status_code=409,
                    detail="An invitation for that email is already waiting. They join when they sign in.",
                )

        if requested_email:
            email_member_role = await _get_user_role_in_org(conn, org_id, requested_email)
            if email_member_role:
                raise HTTPException(
                    status_code=400,
                    detail="That email is already a member of this organization.",
                )

        # Cap only the paid self-serve tiers.  max_seats is updated by the
        # Stripe webhook when a Team workspace buys extra seats, but a stale
        # persisted value must never reduce the tier's included allowance.
        plan_tier = org.get("plan_tier")
        if plan_tier in SEAT_CAPPED_PLAN_TIERS:
            member_count = await conn.fetchval(
                "SELECT COUNT(*) FROM organization_members WHERE org_id::text = $1",
                org_id,
            )
            pending_count = await _pending_invitation_count(conn, org_id) if pending_mode else 0
            try:
                persisted_max_seats = int(org["max_seats"] or 1)
            except (KeyError, TypeError):
                # ``seat_cap`` keeps old unit fixtures and old records readable;
                # deployed organizations use the max_seats column above.
                persisted_max_seats = int(org.get("seat_cap") or 1)
            try:
                included_seats = int(org["included_seats"] or 1)
            except (KeyError, TypeError):
                included_seats = 1
            seat_cap = max(persisted_max_seats, included_seats, 1)
            seats_used = int(member_count or 0) + pending_count
            if seats_used >= seat_cap:
                content = {
                    "detail": (
                        f"Organization has reached its seat limit ({seats_used}/{seat_cap})."
                    ),
                    "seats_used": seats_used,
                    "max_seats": seat_cap,
                }
                if plan_tier == "founder_workspace":
                    content["add_seat_url"] = "/api/v1/billing/seats"
                else:
                    content["detail"] = (
                        "Solo includes 1 seat; upgrade to the Team workspace "
                        "to invite teammates."
                    )
                return JSONResponse(status_code=402, content=content)

        member_user_id = legacy_user_id
        created_new_user = False
        if requested_email and not legacy_user_id:
            try:
                keycloak_user = await get_user_by_email(requested_email)
            except Exception:
                logger.error("Could not look up an invited email for org %s", org_id)
                raise HTTPException(
                    status_code=503,
                    detail="We could not check that email. Try again.",
                )
            if keycloak_user:
                member_user_id = keycloak_user.get("id") or keycloak_user.get("sub")
                if not member_user_id:
                    raise HTTPException(status_code=502, detail="Invited user identity unavailable")
            elif platform_admin or not pending_mode:
                # Preserve the immediate-membership workflow. The default
                # owner/admin path creates the account when needed and sends
                # the existing Keycloak account-action email.
                attributes = {
                    "org_id": [str(org_id)],
                    "org_name": [str(org["name"])],
                    "org_role": [member_data.role],
                }
                created_user = await keycloak_create_user(
                    email=requested_email,
                    username=requested_email,
                    first_name=member_data.firstName or "",
                    last_name=member_data.lastName or "",
                    attributes=attributes,
                    email_verified=False,
                )
                if isinstance(created_user, dict):
                    member_user_id = created_user.get("id") or created_user.get("sub")
                else:
                    member_user_id = created_user
                if not member_user_id:
                    raise HTTPException(status_code=502, detail="Unable to create invited user")

                action_result = await send_account_action_email(
                    str(member_user_id), ["UPDATE_PASSWORD", "VERIFY_EMAIL"]
                )
                if isinstance(action_result, dict) and action_result.get("success") is False:
                    raise HTTPException(status_code=502, detail="Unable to send invitation email")
                created_new_user = True

        if member_user_id:
            existing_role = await _get_user_role_in_org(conn, org_id, str(member_user_id))
            if existing_role:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "That email is already a member of this organization."
                        if requested_email
                        else f"User {member_user_id} already in organization {org_id}"
                    ),
                )

        if pending_mode:
            invited_by = _session_user_id(actor)
            if not invited_by:
                raise HTTPException(status_code=400, detail="Could not identify inviting user")

            invitation = await conn.fetchrow(
                """
                INSERT INTO organization_invitations
                    (org_id, email, role, invited_by, expires_at, accepted)
                VALUES ($1::uuid, $2, $3, $4, CURRENT_TIMESTAMP + INTERVAL '7 days', FALSE)
                RETURNING id::text AS id, expires_at
                """,
                org_id,
                requested_email,
                member_data.role,
                str(invited_by),
            )

            logger.info(
                "Created pending invitation for org %s with role %s",
                org_id,
                member_data.role,
            )
            return {
                "success": True,
                "message": (
                    "Invitation is pending. They join this organization the first time they sign in."
                ),
                "pending": True,
                "membership_added": False,
                "invitation_id": invitation["id"] if invitation else None,
                "email": requested_email,
                "role": member_data.role,
                "expires_at": (
                    invitation["expires_at"].isoformat()
                    if invitation and invitation["expires_at"]
                    else None
                ),
            }

        if not member_user_id:
            raise HTTPException(status_code=422, detail="Could not identify invited user")

        # Insert membership row
        await conn.execute(
            """
            INSERT INTO organization_members (org_id, user_id, role)
            VALUES ($1::uuid, $2, $3)
            """,
            org_id,
            str(member_user_id),
            member_data.role,
        )

        logger.info(f"Added user {member_user_id} to org {org_id} with role {member_data.role}")

        return {
            "success": True,
            "message": (
                f"We emailed {requested_email} an invitation and added them to {org['name']}."
                if requested_email and not platform_admin
                else "Invitation sent successfully" if requested_email
                else "User added to organization"
            ),
            "user_id": str(member_user_id),
            "email": requested_email,
            "role": member_data.role,
            "created": created_new_user,
            "pending": False,
            "membership_added": True,
        }

    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        if _is_missing_relation(e):
            # Fail closed. Do not fall back to inserting a membership.
            logger.error("Invitation storage is unavailable for org %s", org_id)
            raise HTTPException(
                status_code=503,
                detail="Team invitations are not ready yet.",
            ) from e
        logger.error(f"Database error adding member to org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add member: {str(e)}")
    except Exception as e:
        logger.error(f"Error adding member to org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add member: {str(e)}")
    finally:
        await conn.close()


@router.put("/{org_id}/members/{user_id}/role")
async def update_member_role(
    org_id: str,
    user_id: str,
    role_data: OrganizationMemberRoleUpdate,
    request: Request
):
    """
    Update a member's role in the organization

    Args:
        org_id: Organization ID
        user_id: User ID to update
        role_data: New role to assign

    Returns:
        Success confirmation

    Example:
        PUT /api/v1/org/org_12345/members/user@example.com/role
        Body: {"role": "billing_admin"}
        Response: {
            "success": true,
            "message": "User role updated",
            "user_id": "user@example.com",
            "new_role": "billing_admin"
        }
    """
    # Require owner role to update member roles
    await verify_org_access(request, org_id, required_role="owner")

    conn = await get_db_connection()
    try:
        # Update user role (Postgres source of truth)
        result = await conn.execute(
            """
            UPDATE organization_members
            SET role = $3
            WHERE org_id::text = $1 AND user_id = $2
            """,
            org_id,
            user_id,
            role_data.role,
        )

        # asyncpg returns e.g. "UPDATE 1" — 0 rows means user not a member
        if result.endswith(" 0"):
            raise HTTPException(status_code=404, detail="User not found in organization")

        logger.info(f"Updated role for user {user_id} in org {org_id} to {role_data.role}")

        return {
            "success": True,
            "message": "User role updated",
            "user_id": user_id,
            "new_role": role_data.role
        }

    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"Database error updating member role in org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update role: {str(e)}")
    except Exception as e:
        logger.error(f"Error updating member role in org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update role: {str(e)}")
    finally:
        await conn.close()


@router.delete("/{org_id}/members/{user_id}")
async def remove_organization_member(
    org_id: str,
    user_id: str,
    request: Request
):
    """
    Remove a member from the organization

    Args:
        org_id: Organization ID
        user_id: User ID to remove

    Returns:
        Success confirmation

    Example:
        DELETE /api/v1/org/org_12345/members/user@example.com
        Response: {
            "success": true,
            "message": "User removed from organization",
            "user_id": "user@example.com"
        }
    """
    # Require owner role to remove members
    await verify_org_access(request, org_id, required_role="owner")

    conn = await get_db_connection()
    try:
        # Prevent removing the last owner (Postgres source of truth)
        members = await _get_org_members(conn, org_id)
        owners = [m for m in members if m["role"] == "owner"]

        if len(owners) == 1 and owners[0]["user_id"] == user_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last owner. Transfer ownership first."
            )

        # Remove user from organization
        result = await conn.execute(
            """
            DELETE FROM organization_members
            WHERE org_id::text = $1 AND user_id = $2
            """,
            org_id,
            user_id,
        )

        # asyncpg returns e.g. "DELETE 1" — 0 rows means user not a member
        if result.endswith(" 0"):
            raise HTTPException(status_code=404, detail="User not found in organization")

        logger.info(f"Removed user {user_id} from org {org_id}")

        return {
            "success": True,
            "message": "User removed from organization",
            "user_id": user_id
        }

    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"Database error removing member from org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove member: {str(e)}")
    except Exception as e:
        logger.error(f"Error removing member from org {org_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove member: {str(e)}")
    finally:
        await conn.close()


@router.get("/{org_id}/dashboard-cursor")
async def get_dashboard_cursor(org_id: str, request: Request):
    """Read the active user's last rendered activity timestamp for an org."""

    actor = await verify_org_access(request, org_id)
    if not actor:
        actor = await get_current_user(request)
    user_id = _session_user_id(actor)
    if not user_id:
        raise HTTPException(status_code=400, detail="Could not identify user")

    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT details->>'last_seen_at' AS last_seen_at
            FROM organization_audit_log
            WHERE org_id::text = $1
              AND user_id = $2
              AND action = $3
            ORDER BY created_at DESC
            LIMIT 1
            """,
            org_id,
            str(user_id),
            DASHBOARD_CURSOR_ACTION,
        )
        return {
            "org_id": org_id,
            "last_seen_at": row["last_seen_at"] if row else None,
            "server_now": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        if not _is_missing_relation(exc):
            raise
        logger.error("Dashboard cursor storage is unavailable")
        raise HTTPException(
            status_code=503,
            detail="Dashboard activity tracking is not ready yet.",
        ) from exc
    finally:
        await conn.close()


@router.put("/{org_id}/dashboard-cursor")
async def update_dashboard_cursor(
    org_id: str,
    cursor: DashboardCursorUpdate,
    request: Request,
):
    """Advance the cursor only to a newer timestamp after the home renders."""

    actor = await verify_org_access(request, org_id)
    if not actor:
        actor = await get_current_user(request)
    user_id = _session_user_id(actor)
    if not user_id:
        raise HTTPException(status_code=400, detail="Could not identify user")

    if cursor.rendered is not True:
        raise HTTPException(
            status_code=400,
            detail="The activity marker advances only after the home has rendered.",
        )

    incoming = _as_utc(cursor.last_seen_at)
    if incoming > datetime.now(timezone.utc) + DASHBOARD_CURSOR_FUTURE_SKEW:
        raise HTTPException(
            status_code=400,
            detail="The activity marker cannot be set in the future.",
        )

    conn = await get_db_connection()
    try:
        current = await conn.fetchrow(
            """
            SELECT details->>'last_seen_at' AS last_seen_at
            FROM organization_audit_log
            WHERE org_id::text = $1
              AND user_id = $2
              AND action = $3
            ORDER BY created_at DESC
            LIMIT 1
            """,
            org_id,
            str(user_id),
            DASHBOARD_CURSOR_ACTION,
        )
        current_value = current["last_seen_at"] if current else None
        if current_value:
            current_time = _as_utc(datetime.fromisoformat(str(current_value).replace("Z", "+00:00")))
            if incoming <= current_time:
                return {
                    "org_id": org_id,
                    "last_seen_at": current_time.isoformat(),
                    "advanced": False,
                }

        await conn.execute(
            """
            INSERT INTO organization_audit_log
                (org_id, user_id, action, resource_type, details)
            VALUES ($1::uuid, $2, $3, 'dashboard', jsonb_build_object('last_seen_at', $4))
            """,
            org_id,
            str(user_id),
            DASHBOARD_CURSOR_ACTION,
            incoming.isoformat(),
        )
        return {
            "org_id": org_id,
            "last_seen_at": incoming.isoformat(),
            "advanced": True,
        }
    except Exception as exc:
        if not _is_missing_relation(exc):
            raise
        logger.error("Dashboard cursor storage is unavailable")
        raise HTTPException(
            status_code=503,
            detail="Dashboard activity tracking is not ready yet.",
        ) from exc
    finally:
        await conn.close()


@router.get("/{org_id}/stats")
async def get_organization_stats(org_id: str, request: Request):
    """
    Get organization statistics and metrics

    Args:
        org_id: Organization ID

    Returns:
        Organization statistics including member counts, activity, etc.

    Example:
        GET /api/v1/org/org_12345/stats
        Response: {
            "totalMembers": 5,
            "activeMembers": 5,
            "admins": 2,
            "pendingInvites": 0,
            "members_by_role": {"owner": 1, "admin": 1, "member": 3},
            "created_at": "2025-01-01T00:00:00Z",
            "plan_tier": "professional",
            "status": "active"
        }
    """
    # Verify user has access to this organization
    await verify_org_access(request, org_id)

    # Get organization + members from Postgres
    conn = await get_db_connection()
    try:
        org = await _get_org_row(conn, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        members = await _get_org_members(conn, org_id)
        try:
            pending_invites = await _pending_invitation_count(conn, org_id)
        except Exception as exc:
            if not _is_missing_relation(exc):
                raise
            logger.warning("Pending invitation count is unavailable for org %s", org_id)
            pending_invites = 0
    finally:
        await conn.close()

    # Count members by role
    members_by_role = {}
    active_members = 0
    admins = 0

    for member in members:
        role = member["role"]
        members_by_role[role] = members_by_role.get(role, 0) + 1

        # Count admins and owners
        if role in ["owner", "admin"]:
            admins += 1

        # Check if user is enabled in Keycloak
        try:
            user_data = await get_user_by_id(member["user_id"])
            if user_data and user_data.get("enabled", False):
                active_members += 1
        except Exception as e:
            logger.warning(f"Could not check user status for {member['user_id']}: {e}")
            # Assume active if we can't check
            active_members += 1

    created_at = org["created_at"]
    stats = {
        # Frontend expected fields
        "totalMembers": len(members),
        "activeMembers": active_members,
        "admins": admins,
        "pendingInvites": pending_invites,

        # Additional legacy fields
        "total_members": len(members),
        "members_by_role": members_by_role,
        "created_at": created_at.isoformat() if created_at else None,
        "plan_tier": org["plan_tier"],
        "status": org["status"],
        "organization_name": org["name"]
    }

    logger.info(f"Retrieved stats for org {org_id}: {stats['totalMembers']} total, {stats['activeMembers']} active, {stats['admins']} admins")

    return stats


@router.get("/{org_id}/billing")
async def get_organization_billing(org_id: str, request: Request):
    """
    Get organization billing information

    Args:
        org_id: Organization ID

    Returns:
        Billing information including Lago and Stripe customer IDs

    Example:
        GET /api/v1/org/org_12345/billing
        Response: {
            "plan_tier": "professional",
            "lago_customer_id": "lago_cust_abc123",
            "stripe_customer_id": "cus_xyz789",
            "status": "active"
        }
    """
    # Require billing_admin or owner role to view billing
    await verify_org_access(request, org_id, required_role="billing_admin")

    # Get organization from Postgres
    conn = await get_db_connection()
    try:
        org = await _get_org_row(conn, org_id)
    finally:
        await conn.close()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    created_at = org["created_at"]
    billing_info = {
        "plan_tier": org["plan_tier"],
        "lago_customer_id": org["lago_customer_id"],
        "stripe_customer_id": org["stripe_customer_id"],
        "status": org["status"],
        "created_at": created_at.isoformat() if created_at else None
    }

    logger.info(f"Retrieved billing info for org {org_id}")

    return billing_info


@router.get("/{org_id}/settings")
async def get_organization_settings(org_id: str, request: Request):
    """
    Get organization settings

    Args:
        org_id: Organization ID

    Returns:
        Organization settings and configuration

    Example:
        GET /api/v1/org/org_12345/settings
        Response: {
            "id": "org_12345",
            "name": "Acme Corp",
            "plan_tier": "professional",
            "status": "active",
            "created_at": "2025-01-01T00:00:00Z",
            "settings": {}
        }
    """
    # Verify user has access to this organization
    await verify_org_access(request, org_id)

    # Get organization from Postgres
    conn = await get_db_connection()
    try:
        org = await _get_org_row(conn, org_id)
    finally:
        await conn.close()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    created_at = org["created_at"]
    settings = {
        "id": org["id"],
        "name": org["name"],
        "plan_tier": org["plan_tier"],
        "status": org["status"],
        "created_at": created_at.isoformat() if created_at else None,
        "settings": {}  # Placeholder for future settings
    }

    logger.info(f"Retrieved settings for org {org_id}")

    return settings


@router.put("/{org_id}/settings")
async def update_organization_settings(
    org_id: str,
    settings_data: OrganizationSettingsUpdate,
    request: Request
):
    """
    Update organization settings

    Args:
        org_id: Organization ID
        settings_data: Settings to update

    Returns:
        Updated settings

    Example:
        PUT /api/v1/org/org_12345/settings
        Body: {"settings": {"notification_email": "admin@acme.com"}}
        Response: {
            "success": true,
            "message": "Settings updated",
            "settings": {"notification_email": "admin@acme.com"}
        }
    """
    # Require owner role to update settings
    await verify_org_access(request, org_id, required_role="owner")

    # Verify organization exists (Postgres source of truth)
    conn = await get_db_connection()
    try:
        org = await _get_org_row(conn, org_id)
    finally:
        await conn.close()

    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # TODO: Persist settings to the organization_settings table.
    # For now, just return success.

    logger.info(f"Updated settings for org {org_id}")

    return {
        "success": True,
        "message": "Settings updated",
        "settings": settings_data.settings
    }
