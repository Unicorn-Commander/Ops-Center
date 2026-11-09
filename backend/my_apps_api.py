"""
My Apps API - Returns apps filtered by user's subscription tier and organization grants

Integrates with existing RBAC system:
- tier_features: Features granted by user's subscription tier
- org_features: Features explicitly granted to user's organization

User sees an app IF: (tier includes feature) OR (org has explicit grant for feature)
"""

import os
import json
import sys
from typing import Any, Dict, List, Literal, Optional, Union
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, ValidationError
import asyncpg

# Router configuration
router = APIRouter(prefix="/api/v1/my-apps", tags=["my-apps"])


# =============================================================================
# Pydantic Models
# =============================================================================

AppState = Literal["ready", "needs_first_open", "not_entitled"]


class CompanionLink(BaseModel):
    """A safe, user-facing companion download link."""

    label: str
    url: str


class PrimaryActionMetadata(BaseModel):
    """Static metadata for an entitled app's primary action."""

    label: str
    route_id: Optional[str] = None


class ReadinessMetadata(BaseModel):
    """How an app's initial card state is determined."""

    check: Literal["none", "first_open"] = "none"


class CompanionMetadata(BaseModel):
    """Catalogued MCP endpoint and optional native companion links."""

    label: str = "Connect your AI"
    mcp_url: str
    chatgpt_url: str
    desktop: List[CompanionLink] = Field(default_factory=list)
    mobile: List[CompanionLink] = Field(default_factory=list)


class DashboardMetadata(BaseModel):
    """Typed dashboard metadata stored in an add-on's JSONB metadata."""

    purpose: str
    primary_action: PrimaryActionMetadata
    readiness: ReadinessMetadata = Field(default_factory=ReadinessMetadata)
    companion: Optional[CompanionMetadata] = None
    internal_ring: bool = False


class AppDashboardMetadata(BaseModel):
    """Envelope for the dashboard metadata namespace."""

    dashboard: DashboardMetadata


class PrimaryAction(BaseModel):
    label: str
    url: str


class CompanionResponse(BaseModel):
    """Safe connect instructions. It never contains a token or credential."""

    kind: Literal["mcp"] = "mcp"
    label: str
    mcp_url: str
    claude_code_command: str
    client_config: Dict[str, Any]
    chatgpt_url: str
    desktop: List[CompanionLink] = Field(default_factory=list)
    mobile: List[CompanionLink] = Field(default_factory=list)


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    """Support the Pydantic version used by the app and lightweight test doubles."""

    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


_PLACEHOLDER_HOSTS = {
    "example.com",
    "www.example.com",
    "invalid",
    "localhost",
}


def _validate_catalog_url(value: str, field_name: str, *, require_path: bool = True) -> str:
    """Reject unusable or credential-bearing catalog URLs before they reach users."""

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host or (require_path and not parsed.path):
        raise ValueError(f"{field_name} must be an absolute HTTP URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} must not contain URL credentials")
    if host in _PLACEHOLDER_HOSTS or host.endswith(".example.com"):
        raise ValueError(f"{field_name} uses a placeholder host")
    return value


def _validate_companion(companion: CompanionMetadata) -> None:
    """Validate the actual MCP path and every optional download URL."""

    _validate_catalog_url(companion.mcp_url, "companion.mcp_url")
    _validate_catalog_url(companion.chatgpt_url, "companion.chatgpt_url")
    mcp_path = (urlparse(companion.mcp_url).path or "").rstrip("/")
    if not mcp_path.endswith("/mcp"):
        raise ValueError("companion.mcp_url must use the app's /mcp endpoint")
    for link in [*companion.desktop, *companion.mobile]:
        _validate_catalog_url(link.url, "companion download URL")


def validate_dashboard_metadata(raw_metadata: Any, *, fallback_purpose: str = "") -> AppDashboardMetadata:
    """Parse and validate only the safe dashboard metadata namespace.

    The catalog stores other JSONB data for marketplace concerns. It is never copied
    into the authorized-app response. A legacy row without metadata gets a typed,
    launch-only card so a catalog migration can be rolled out independently.
    """

    if isinstance(raw_metadata, str):
        try:
            raw_metadata = json.loads(raw_metadata)
        except json.JSONDecodeError as exc:
            raise ValueError("metadata is not valid JSON") from exc

    if not raw_metadata:
        raw_metadata = {
            "dashboard": {
                "purpose": fallback_purpose or "Workspace access for this app.",
                "primary_action": {"label": "Open app"},
                "readiness": {"check": "none"},
            }
        }
    elif isinstance(raw_metadata, dict) and "dashboard" not in raw_metadata:
        raw_metadata = {"dashboard": raw_metadata}
    elif not isinstance(raw_metadata, dict):
        raise ValueError("metadata must be an object")

    try:
        metadata = (
            AppDashboardMetadata.model_validate(raw_metadata)
            if hasattr(AppDashboardMetadata, "model_validate")
            else AppDashboardMetadata.parse_obj(raw_metadata)
        )
    except ValidationError as exc:
        raise ValueError("dashboard metadata does not match the catalog schema") from exc

    purpose = metadata.dashboard.purpose.strip()
    if not purpose or "\n" in purpose or "\r" in purpose or len(purpose) > 180:
        raise ValueError("dashboard.purpose must be a one-line sentence")
    if metadata.dashboard.companion:
        _validate_companion(metadata.dashboard.companion)
    return metadata


def app_state_from_metadata(metadata: DashboardMetadata, *, has_opened: bool = False) -> AppState:
    """Resolve the card state without ever manufacturing a not-entitled card."""

    if metadata.readiness.check == "first_open" and not has_opened:
        return "needs_first_open"
    return "ready"


def build_companion_response(slug: str, companion: Optional[CompanionMetadata]) -> Optional[CompanionResponse]:
    """Build copyable client recipes from the catalogued MCP URL."""

    if not companion:
        return None
    return CompanionResponse(
        label=companion.label,
        mcp_url=companion.mcp_url,
        claude_code_command=(
            f"claude mcp add --transport http {slug} {companion.mcp_url}"
        ),
        client_config={
            "mcpServers": {
                slug: {
                    "url": companion.mcp_url,
                }
            }
        },
        chatgpt_url=companion.chatgpt_url,
        desktop=companion.desktop,
        mobile=companion.mobile,
    )

class AppResponse(BaseModel):
    """App available to user"""
    id: Union[int, str]
    name: str
    slug: str
    description: str
    icon_url: Optional[str]
    launch_url: str
    category: str
    feature_key: Optional[str]
    access_type: str  # 'tier_included', 'org_granted', 'premium_purchased', 'upgrade_required'
    purpose: str = ""
    state: AppState = "ready"
    primary_action: Optional[PrimaryAction] = None
    companion: Optional[CompanionResponse] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    features: Optional[Any] = None
    price: Optional[float] = None
    billing_type: Optional[str] = None


# =============================================================================
# Database Connection
# =============================================================================

async def get_db_connection():
    """Create database connection."""
    return await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "unicorn"),
        password=os.getenv("POSTGRES_PASSWORD", "unicorn"),
        database=os.getenv("POSTGRES_DB", "unicorn_db")
    )


# =============================================================================
# Authentication Dependency
# =============================================================================

def _session_data_from_request(request: Request) -> Optional[Dict[str, Any]]:
    """Read the request session without exposing session contents to logs."""

    session_token = request.cookies.get("session_token")
    if not session_token:
        return None

    try:
        from redis_session import redis_session_manager

        getter = getattr(redis_session_manager, "get", None)
        if callable(getter):
            return getter(session_token)
        if session_token in redis_session_manager:
            return redis_session_manager[session_token]
    except Exception:
        return None
    return None


def _session_subject(session_data: Dict[str, Any]) -> Optional[str]:
    """Return the stable session subject used by organization memberships."""

    user = session_data.get("user", {}) or {}
    return (
        session_data.get("sub")
        or session_data.get("user_id")
        or session_data.get("id")
        or user.get("sub")
        or user.get("user_id")
        or user.get("id")
    )


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    """Read a mapping or asyncpg.Record without assuming one concrete row type."""

    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _set_request_org_context(
    request: Request,
    *,
    tier: Optional[str] = None,
    org_name: Optional[str] = None,
    invalid: bool = False,
) -> None:
    """Keep the validated org decision available to the endpoint without a second lookup."""

    try:
        if tier:
            request.state.current_org_tier = tier
        if org_name:
            request.state.current_org_name = org_name
        if invalid:
            request.state.current_org_invalid = True
    except AttributeError:
        # Small request doubles in unit tests need not implement Starlette state.
        pass

async def get_current_user_tier(request: Request) -> str:
    """
    Extract user's subscription tier from session cookies.
    Uses Redis session manager (same pattern as require_admin dependency).

    Returns:
        User's subscription tier (vip_founder, byok, managed, founder_workspace)
        Defaults to 'managed' if not authenticated or tier not found

    Database tiers:
        - vip_founder: 4 features (chat, search, litellm, priority_support)
        - byok: 7 features (adds brigade, tts, stt)
        - managed: 11 features (adds bolt, billing, dedicated support)
    """
    # Add parent directory to path if needed
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')

    try:
        from redis_session import redis_session_manager

        # Get session token from cookie
        session_token = request.cookies.get("session_token")
        if not session_token:
            # Not authenticated - return trial tier (limited access)
            return 'trial'

        # Get Redis connection info
        redis_host = os.getenv("REDIS_HOST", "unicorn-redis")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))

        # Reuse the startup-configured session manager.
        sessions = redis_session_manager

        # Get session data
        if session_token not in sessions:
            # Session expired - return trial tier
            return 'trial'

        session_data = sessions[session_token]

        # Check for tier — prefer nested "user" dict (from Keycloak), fall back to root level
        user = session_data.get("user", {})
        tier = user.get("subscription_tier") or user.get("tier")
        if not tier:
            # Fall back to root level (may be stale/default)
            tier = session_data.get("subscription_tier")

        # If tier not set or invalid, try database fallback
        # Valid tiers: All tiers from subscription_tiers table
        valid_tiers = [
            'free', 'app',
            'vip_founder', 'byok', 'managed', 'founder_workspace', 'founder_friend', 'founder-friend',
            'trial', 'starter', 'professional', 'enterprise',
            'nda-autopilot', 'partnerpulse', 'm10_partner',
            'human_interest', 'loopnet_starter', 'loopnet_professional'
        ]
        if not tier or tier not in valid_tiers:
            # Try database fallback - get tier from user's organization
            # First try to get user's Keycloak sub (stored as zitadel_id in users table)
            keycloak_sub = session_data.get("sub") or session_data.get("user", {}).get("sub")

            import logging
            logger = logging.getLogger(__name__)

            # Also get user's email for fallback lookup
            user_email = session_data.get("email") or session_data.get("user", {}).get("email")

            if keycloak_sub or user_email:
                try:
                    conn = await get_db_connection()
                    try:
                        tier_row = None
                        user_id_to_update = None

                        # First, try lookup by zitadel_id (Keycloak sub)
                        if keycloak_sub:
                            tier_row = await conn.fetchrow("""
                                SELECT o.plan_tier, u.id as user_id
                                FROM users u
                                JOIN organization_members om ON u.id::text = om.user_id
                                JOIN organizations o ON om.org_id = o.id
                                WHERE u.zitadel_id = $1
                                ORDER BY om.is_default DESC, om.joined_at ASC
                                LIMIT 1
                            """, str(keycloak_sub))

                        # Fallback: lookup by email if zitadel_id lookup failed
                        if not tier_row and user_email:
                            logger.info(f"[MY-APPS] zitadel_id lookup failed, trying email fallback: {user_email}")
                            tier_row = await conn.fetchrow("""
                                SELECT o.plan_tier, u.id as user_id
                                FROM users u
                                JOIN organization_members om ON u.id::text = om.user_id
                                JOIN organizations o ON om.org_id = o.id
                                WHERE u.email = $1
                                ORDER BY om.is_default DESC, om.joined_at ASC
                                LIMIT 1
                            """, user_email)

                            # If found by email, update zitadel_id for future lookups
                            if tier_row and keycloak_sub:
                                user_id_to_update = tier_row['user_id']
                                await conn.execute(
                                    "UPDATE users SET zitadel_id = $1 WHERE id = $2",
                                    str(keycloak_sub), user_id_to_update
                                )
                                logger.info(f"[MY-APPS] Updated zitadel_id for user {user_email} to {keycloak_sub}")

                        if tier_row and tier_row['plan_tier']:
                            tier = tier_row['plan_tier']
                            logger.info(f"[MY-APPS] Tier from database lookup: {tier} for user {user_email or keycloak_sub}")
                    finally:
                        await conn.close()
                except Exception as db_error:
                    logger.warning(f"Database tier lookup failed: {db_error}")

            # If still no tier, default to trial (limited access until they subscribe)
            if not tier or tier not in valid_tiers:
                tier = 'trial'

        return tier

    except Exception as e:
        # On any error, default to trial tier (limited access)
        # Log warning but don't fail the request
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error extracting user tier from session: {e}")
        return 'trial'


# =============================================================================
# Helper Functions
# =============================================================================

def get_tier_level(tier_name: str) -> int:
    """Convert tier name to level for comparison"""
    tier_levels = {
        'trial': 1,
        'starter': 2,
        'professional': 3,
        'founder_workspace': 3,
        'enterprise': 4
    }
    return tier_levels.get(tier_name.lower(), 0)


async def get_user_org_from_session(request: Request) -> Optional[str]:
    """
    Get user's current organization ID from session or database fallback.

    Returns:
        Organization ID (UUID string) or None if user has no org
    """
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')

    try:
        session_data = _session_data_from_request(request)
        if not session_data:
            return None

        user = session_data.get("user", {}) or {}
        session_org_id = session_data.get("org_id") or user.get("org_id")
        cookie_org_id = request.cookies.get("current_org_id")
        requested_org_id = cookie_org_id or session_org_id
        subject = _session_subject(session_data)

        if requested_org_id and subject:
            conn = await get_db_connection()
            try:
                org_row = await conn.fetchrow(
                    """
                    SELECT om.org_id::text AS org_id, o.plan_tier, o.name AS org_name
                    FROM organization_members om
                    JOIN organizations o ON o.id = om.org_id
                    LEFT JOIN users u ON u.id::text = om.user_id
                    WHERE (om.user_id = $1 OR u.zitadel_id = $1)
                      AND om.org_id::text = $2
                      AND o.status = 'active'
                    LIMIT 1
                    """,
                    str(subject),
                    str(requested_org_id),
                )
            finally:
                await conn.close()

            if org_row:
                _set_request_org_context(
                    request,
                    tier=_row_value(org_row, "plan_tier"),
                    org_name=_row_value(org_row, "org_name"),
                )
                return str(_row_value(org_row, "org_id"))

            # An explicit organization cookie must never fall back to another org.
            if cookie_org_id:
                _set_request_org_context(request, invalid=True)
                return None

        # An org ID in a session is a selection hint, not proof of membership.
        # Without a stable subject we cannot validate it, so fail closed rather
        # than allowing a stale or forged org context to read its grants.
        if requested_org_id and not subject:
            _set_request_org_context(request, invalid=True)
            return None

        if subject:
            conn = await get_db_connection()
            try:
                org_row = await conn.fetchrow(
                    """
                    SELECT om.org_id::text AS org_id, o.plan_tier, o.name AS org_name
                    FROM organization_members om
                    JOIN organizations o ON o.id = om.org_id
                    LEFT JOIN users u ON u.id::text = om.user_id
                    WHERE (om.user_id = $1 OR u.zitadel_id = $1)
                      AND o.status = 'active'
                    ORDER BY om.is_default DESC, om.joined_at ASC, om.org_id::text ASC
                    LIMIT 1
                    """,
                    str(subject),
                )
            finally:
                await conn.close()
            if org_row:
                _set_request_org_context(
                    request,
                    tier=_row_value(org_row, "plan_tier"),
                    org_name=_row_value(org_row, "org_name"),
                )
                return str(_row_value(org_row, "org_id"))

        return None

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Error getting current organization for my-apps: %s", e)
        if request.cookies.get("current_org_id"):
            _set_request_org_context(request, invalid=True)
        return None


async def get_org_features(org_id: str, conn) -> set:
    """
    Get all feature keys explicitly granted to an organization.

    Args:
        org_id: Organization UUID
        conn: Database connection

    Returns:
        Set of feature_key strings enabled for this org
    """
    if not org_id:
        return set()

    try:
        # Query org_features table for explicit feature grants
        feature_rows = await conn.fetch(
            "SELECT feature_key FROM org_features WHERE org_id = $1 AND enabled = TRUE AND (expires_at IS NULL OR expires_at > now())",
            org_id
        )
        return {row['feature_key'] for row in feature_rows}
    except Exception as e:
        # Table might not exist yet - gracefully return empty set
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"org_features query failed (table may not exist): {e}")
        return set()


async def get_user_tier_features(user_tier: str, conn) -> set:
    """Get all app keys enabled for user's tier"""
    # Validate tier before database query - include all tiers from subscription_tiers table
    valid_tiers = [
        'free', 'app',
        'trial', 'starter', 'professional', 'enterprise',
        'vip_founder', 'founder_friend', 'founder-friend', 'byok', 'managed', 'founder_workspace',
        'nda-autopilot', 'partnerpulse', 'm10_partner',
        'human_interest', 'loopnet_starter', 'loopnet_professional'
    ]
    if user_tier.lower() not in valid_tiers:
        raise HTTPException(status_code=400, detail=f"Invalid subscription tier: {user_tier}")

    # Get tier_id from subscription_tiers (using tier_code which matches Keycloak attribute)
    tier_row = await conn.fetchrow(
        "SELECT id FROM subscription_tiers WHERE tier_code = $1",
        user_tier.lower()  # tier_code is lowercase
    )

    if not tier_row:
        return set()

    tier_id = tier_row['id']

    # Get all enabled features for this tier from tier_features table
    feature_rows = await conn.fetch(
        "SELECT feature_key FROM tier_features WHERE tier_id = $1 AND enabled = TRUE",
        tier_id
    )

    return {row['feature_key'] for row in feature_rows}


async def get_combined_features(user_tier: str, org_id: Optional[str], conn) -> set:
    """
    Get all feature keys the user has access to.

    Combines:
    - Features from user's subscription tier (tier_features)
    - Features explicitly granted to user's organization (org_features)

    User sees an app IF: (tier includes feature) OR (org has explicit grant)

    Args:
        user_tier: User's subscription tier code
        org_id: User's current organization ID (may be None)
        conn: Database connection

    Returns:
        Set of all feature_key strings user has access to
    """
    # Get tier-based features
    tier_features = await get_user_tier_features(user_tier, conn)

    # Get org-based features (if user has an org)
    org_features = await get_org_features(org_id, conn)

    # Union of both sets - user sees app if EITHER grants access
    return tier_features.union(org_features)


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/authorized", response_model=List[AppResponse])
async def get_my_apps(request: Request, user_tier: str = Depends(get_current_user_tier)):
    """
    Get apps the current user is authorized to access based on their subscription tier
    and organization grants.

    Returns apps where:
    - User's tier includes the app's feature_key (tier_features table)
    - User's organization has explicit access grant (org_features table)
    - User has purchased the app separately (future: check user_add_ons table)
    """
    import logging
    logger = logging.getLogger(__name__)

    session_data = _session_data_from_request(request) or {}
    user_data = session_data.get("user", {}) or {}
    roles = set()
    for role_source in (user_data.get("roles"), session_data.get("roles")):
        if isinstance(role_source, str):
            roles.update(role_source.split())
        elif role_source:
            roles.update(role_source)
    for role_source in (user_data.get("role"), session_data.get("role")):
        if isinstance(role_source, str):
            roles.update(role_source.split())
    is_admin = bool(
        user_data.get("is_admin")
        or session_data.get("is_admin")
        or roles.intersection({"admin", "super_admin", "platform_admin"})
    )

    # Resolve the selected org before opening the catalog. An invalid current-org
    # cookie is fail-closed and must not fall back to the session's old org.
    org_id = await get_user_org_from_session(request)
    org_context_invalid = bool(getattr(getattr(request, "state", None), "current_org_invalid", False))
    org_tier = getattr(getattr(request, "state", None), "current_org_tier", None)
    org_name = getattr(getattr(request, "state", None), "current_org_name", None)

    conn = await get_db_connection()
    try:
        if org_context_invalid:
            tier_features = set()
            org_features_set = set()
            enabled_features = set()
        else:
            effective_tier = org_tier or user_tier
            try:
                tier_features = await get_user_tier_features(effective_tier, conn)
            except HTTPException:
                # An unknown organization tier is not a reason to expose the
                # session tier. Treat it as no tier entitlement.
                tier_features = set()
            org_features_set = await get_org_features(org_id, conn)
            enabled_features = tier_features.union(org_features_set)

        # Admins are still allowed to inspect every active catalog entry, but the
        # response uses the same safe metadata contract as ordinary users.
        apps_query = """
            SELECT id, name, slug, description, icon_url, launch_url,
                   category, feature_key, base_price, metadata
            FROM add_ons
            WHERE is_active = TRUE
            ORDER BY sort_order, name
        """
        app_rows = await conn.fetch(apps_query)

        authorized_apps = []
        for app in app_rows:
            app_dict = dict(app)
            feature_key = app_dict.get("feature_key")

            # A catalog row without a launch URL cannot become a primary card.
            if not app_dict.get("launch_url"):
                continue

            if feature_key:
                if (not is_admin or org_context_invalid) and feature_key not in enabled_features:
                    continue
                access_type = "tier_included" if feature_key in tier_features else "org_granted"
            elif app_dict.get("base_price") == 0:
                if org_context_invalid:
                    continue
                access_type = "tier_included"
            else:
                continue

            try:
                _validate_catalog_url(app_dict["launch_url"], "launch_url", require_path=False)
                metadata = validate_dashboard_metadata(
                    app_dict.get("metadata"),
                    fallback_purpose=app_dict.get("description") or "",
                )
            except ValueError as exc:
                logger.error("Invalid dashboard metadata for catalog app %s: %s", app_dict.get("slug"), exc)
                raise HTTPException(
                    status_code=500,
                    detail="The app catalog needs attention before apps can be loaded.",
                ) from exc

            dashboard = metadata.dashboard
            if dashboard.internal_ring and org_name != "ops-center-dogfood":
                # Internal cards are not an admin shortcut. The org context is
                # the ring boundary, including for platform administrators.
                continue
            state = app_state_from_metadata(dashboard)
            companion = build_companion_response(app_dict["slug"], dashboard.companion)

            # Only the typed dashboard namespace is returned. In particular,
            # add_ons.features and arbitrary marketplace metadata never cross the
            # entitlement boundary.
            authorized_apps.append({
                "id": app_dict["id"],
                "name": app_dict["name"],
                "slug": app_dict["slug"],
                "description": app_dict.get("description") or "",
                "icon_url": app_dict.get("icon_url"),
                "launch_url": app_dict["launch_url"],
                "category": app_dict.get("category") or "general",
                "feature_key": feature_key,
                "access_type": access_type,
                "purpose": dashboard.purpose,
                "state": state,
                "primary_action": {
                    "label": dashboard.primary_action.label,
                    "url": app_dict["launch_url"],
                },
                "companion": _model_dump(companion) if companion else None,
                "metadata": _model_dump(metadata),
            })

        return authorized_apps

    except asyncpg.PostgresError as e:
        logger.error("my-apps catalog query failed: %s", e)
        raise HTTPException(status_code=500, detail="Apps are temporarily unavailable.") from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("my-apps request failed: %s", e)
        raise HTTPException(status_code=500, detail="Apps are temporarily unavailable.") from e
    finally:
        await conn.close()


@router.get("/marketplace", response_model=List[AppResponse])
async def get_marketplace_apps(request: Request, user_tier: str = Depends(get_current_user_tier)):
    """
    Get apps available for purchase (not included in user's current tier or org).

    Returns:
    - Premium apps user can purchase
    - Apps requiring tier upgrade
    """
    # Get user's current organization from session
    org_id = await get_user_org_from_session(request)

    conn = await get_db_connection()
    try:
        # User's tier is now extracted from session via dependency injection

        # Get combined features (tier + org) - user already has access to these
        enabled_features = await get_combined_features(user_tier, org_id, conn)

        # Get all active apps
        # is_public IS NOT FALSE keeps legacy rows (NULL) visible while hiding
        # explicitly admin-only apps (e.g. Brigade) from the retail marketplace.
        apps_query = """
            SELECT id, name, slug, description, icon_url, launch_url,
                   category, feature_key, base_price, billing_type
            FROM add_ons
            WHERE is_active = TRUE
              AND is_public IS NOT FALSE
            ORDER BY base_price DESC, name
        """
        app_rows = await conn.fetch(apps_query)

        # Filter to apps NOT in user's tier
        marketplace_apps = []
        for app in app_rows:
            app_dict = dict(app)
            feature_key = app_dict.get('feature_key')

            # Skip apps without launch URLs
            if not app_dict.get('launch_url'):
                continue

            # Skip apps user already has access to
            if feature_key and feature_key in enabled_features:
                continue

            # Determine access type
            access_type = 'premium_purchase' if app_dict['base_price'] > 0 else 'upgrade_required'

            marketplace_apps.append({
                'id': app_dict['id'],
                'name': app_dict['name'],
                'slug': app_dict['slug'],
                'description': app_dict['description'] or '',
                'icon_url': app_dict['icon_url'],
                'launch_url': app_dict['launch_url'],
                'category': app_dict['category'] or 'general',
                'feature_key': feature_key,
                'access_type': access_type,
                'price': float(app_dict['base_price']) if app_dict['base_price'] else 0,
                'billing_type': app_dict.get('billing_type', 'monthly')
            })

        return marketplace_apps

    except asyncpg.PostgresError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error: {str(e)}"
        )
    finally:
        await conn.close()
