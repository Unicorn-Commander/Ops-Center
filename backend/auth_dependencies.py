"""
Authentication Dependencies for FastAPI
========================================

Provides reusable FastAPI dependencies for authentication that run BEFORE
request body validation, preventing information disclosure through validation errors.

Author: Ops-Center Security Team
Created: 2025-11-12
"""

from fastapi import Request, HTTPException, Depends
from typing import Dict, Any, Optional, Iterable
import hashlib
import hmac
import json
import logging
import os
import re
import uuid

logger = logging.getLogger(__name__)


# Service-key authentication is deliberately narrower than the existing
# service-key support used by the LLM/credit paths.  The hashes keep the exact
# existing JSON object format (key id -> SHA-256 hex digest), while this second
# map is an explicit per-key route grant.  An absent or malformed route map is
# deny-by-default.
SERVICE_KEY_HASHES_ENV = "OPS_CENTER_SERVICE_KEY_HASHES"
SERVICE_KEY_ROUTE_ALLOWLIST_ENV = "OPS_CENTER_SERVICE_KEY_ROUTE_ALLOWLIST"

SERVICE_KEY_ROUTE_IDS = {
    "org_create": ("POST", "/api/v1/org"),
    "org_member_add": ("POST", "/api/v1/org/{org_id}/members"),
    "paid_org_provision": ("POST", "/api/v1/admin/billing/provision-paid-org"),
    "org_feature_grant": ("POST", "/api/v1/admin/orgs/{org_id}/features"),
}

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _service_key_hashes() -> tuple[tuple[str, bytes], ...]:
    """Parse the existing key-id -> SHA-256 map without retaining plaintext."""
    raw = os.getenv(SERVICE_KEY_HASHES_ENV, "")
    if not raw.strip():
        return ()
    try:
        configured = json.loads(raw)
    except (TypeError, ValueError):
        logger.error("%s is not valid JSON; admin service-key auth is disabled", SERVICE_KEY_HASHES_ENV)
        return ()
    if not isinstance(configured, dict):
        logger.error("%s must be a JSON object; admin service-key auth is disabled", SERVICE_KEY_HASHES_ENV)
        return ()

    entries = []
    for raw_key_id, raw_digest in configured.items():
        key_id = raw_key_id.strip() if isinstance(raw_key_id, str) else ""
        digest = raw_digest.strip().lower() if isinstance(raw_digest, str) else ""
        if not key_id or len(key_id) > 128:
            logger.error("%s contains an invalid key id; that entry is disabled", SERVICE_KEY_HASHES_ENV)
            continue
        if not _SHA256_HEX_RE.fullmatch(digest):
            logger.error("%s: key id %s does not contain a SHA-256 hex digest; that entry is disabled",
                         SERVICE_KEY_HASHES_ENV, key_id)
            continue
        entries.append((key_id, bytes.fromhex(digest)))
    return tuple(entries)


def _route_id_from_config(value: object) -> Optional[str]:
    """Accept a route id or a method/path entry from the allowlist."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate in SERVICE_KEY_ROUTE_IDS:
        return candidate

    method = "POST"
    path = candidate
    if " " in candidate:
        method, path = candidate.split(None, 1)
        method = method.upper()
    for route_id, (route_method, route_path) in SERVICE_KEY_ROUTE_IDS.items():
        if method == route_method and path == route_path:
            return route_id
    return None


def _service_key_route_allowlist() -> Dict[str, frozenset[str]]:
    """Parse key-id -> route-set configuration; unknown routes are ignored."""
    raw = os.getenv(SERVICE_KEY_ROUTE_ALLOWLIST_ENV, "")
    if not raw.strip():
        return {}
    try:
        configured = json.loads(raw)
    except (TypeError, ValueError):
        logger.error("%s is not valid JSON; admin service-key routes are disabled",
                     SERVICE_KEY_ROUTE_ALLOWLIST_ENV)
        return {}
    if not isinstance(configured, dict):
        logger.error("%s must be a JSON object; admin service-key routes are disabled",
                     SERVICE_KEY_ROUTE_ALLOWLIST_ENV)
        return {}

    allowlist: Dict[str, frozenset[str]] = {}
    for raw_key_id, raw_routes in configured.items():
        key_id = raw_key_id.strip() if isinstance(raw_key_id, str) else ""
        if not key_id:
            continue
        if isinstance(raw_routes, str):
            raw_routes = [raw_routes]
        if not isinstance(raw_routes, list):
            logger.error("%s: route set for key id %s is not a list; it is disabled",
                         SERVICE_KEY_ROUTE_ALLOWLIST_ENV, key_id)
            continue
        route_ids = {
            route_id
            for route_id in (_route_id_from_config(route) for route in raw_routes)
            if route_id is not None
        }
        allowlist[key_id] = frozenset(route_ids)
    return allowlist


def _request_route_id(request: Request) -> Optional[str]:
    """Map the routed request to one of the four exact onboarding routes."""
    method = request.method.upper()
    path = request.scope.get("path", "")
    path_parts = path.split("/")
    for route_id, (route_method, route_path) in SERVICE_KEY_ROUTE_IDS.items():
        if method != route_method:
            continue
        template_parts = route_path.split("/")
        if len(path_parts) != len(template_parts):
            continue
        if all(
            actual == expected
            or (expected.startswith("{") and expected.endswith("}") and bool(actual))
            for actual, expected in zip(path_parts, template_parts)
        ):
            return route_id
    return None


def _request_org_id(request: Request, route_id: Optional[str]) -> Optional[str]:
    """Extract a path org id for audit context without trusting it as a UUID."""
    if route_id not in {"org_member_add", "org_feature_grant"}:
        return None
    path_parts = request.scope.get("path", "").split("/")
    try:
        index = 4 if route_id == "org_member_add" else 5
        value = path_parts[index]
    except (IndexError, TypeError):
        return None
    return value or None


def _audit_uuid(value: Optional[str]) -> Optional[str]:
    """Return a database-safe UUID string, leaving non-UUID route ids in details."""
    if not value:
        return None
    try:
        return str(uuid.UUID(value.removeprefix("org_")))
    except (ValueError, AttributeError):
        return None


def _service_key_token(request: Request) -> Optional[str]:
    """Read either supported service-key header without logging its value."""
    explicit = request.headers.get("X-Ops-Center-Service-Key")
    authorization = request.headers.get("Authorization")
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()

    if explicit is None and bearer is None:
        return None
    if explicit is not None and bearer is not None:
        explicit_value = explicit.strip()
        if not hmac.compare_digest(explicit_value, bearer):
            raise HTTPException(status_code=401, detail="Invalid service key")
        return explicit_value
    return (explicit if explicit is not None else bearer or "").strip()


def _match_service_key(token: str, entries: Iterable[tuple[str, bytes]]) -> Optional[str]:
    """Match every configured digest so the key id is not timing-disclosed."""
    presented = hashlib.sha256(token.encode("utf-8")).digest()
    matched_key_id = None
    for key_id, digest in entries:
        if hmac.compare_digest(presented, digest) and matched_key_id is None:
            matched_key_id = key_id
    return matched_key_id


async def _get_audit_pool():
    """Late import keeps the auth module usable in isolated dependency tests."""
    from database import get_db_pool

    return await get_db_pool()


async def write_organization_audit_log(
    request: Request,
    *,
    org_id: Optional[str],
    principal: str,
    action: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist a service-key action in the organization audit table."""
    route_path = request.scope.get("path", "")
    route_details = {"route": route_path, "method": request.method.upper()}
    if details:
        route_details.update(details)
    client = request.client
    ip_address = client.host if client else None
    user_agent = request.headers.get("user-agent")
    resource_id = org_id or route_path

    try:
        pool = await _get_audit_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO organization_audit_log
                    (org_id, user_id, action, resource_type, resource_id,
                     details, ip_address, user_agent)
                VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7::inet, $8)
                """,
                _audit_uuid(org_id),
                principal,
                action,
                "onboarding_route",
                resource_id,
                json.dumps(route_details, separators=(",", ":")),
                ip_address,
                user_agent,
            )
    except Exception as exc:
        # Do not expose a database error (which can contain connection details) or
        # allow an unaudited service-key write to proceed.
        logger.error("organization audit write failed for service-key request")
        raise HTTPException(status_code=503, detail="Organization audit service unavailable") from exc


async def get_service_key_user(request: Request) -> Optional[Dict[str, Any]]:
    """Authenticate a route-scoped admin service key, or return ``None``."""
    cached_user = getattr(request.state, "ops_center_service_key_user", None)
    if cached_user is not None:
        return cached_user
    if getattr(request.state, "ops_center_service_key_checked", False):
        return None

    # Existing browser sessions have always been cookie-authenticated and have
    # ignored unrelated Authorization headers. Keep that behavior unless the
    # caller explicitly selects the new service-key header.
    if request.cookies.get("session_token") and request.headers.get("X-Ops-Center-Service-Key") is None:
        request.state.ops_center_service_key_checked = True
        return None

    token = _service_key_token(request)
    if token is None:
        request.state.ops_center_service_key_checked = True
        return None

    key_id = _match_service_key(token, _service_key_hashes())
    if key_id is None:
        raise HTTPException(status_code=401, detail="Invalid service key")

    route_id = _request_route_id(request)
    allowed_routes = _service_key_route_allowlist().get(key_id, frozenset())
    if route_id is None or route_id not in allowed_routes:
        raise HTTPException(status_code=403, detail="Service key is not authorized for this route")

    acting_user = request.headers.get("X-Acting-User")
    acting_user = acting_user.strip() if acting_user else None
    principal = f"service-key:{key_id}"
    await write_organization_audit_log(
        request,
        org_id=_request_org_id(request, route_id),
        principal=principal,
        action=f"service-key.{route_id}",
        details={"acting_user": acting_user} if acting_user else None,
    )
    request.state.ops_center_service_key_user = {
        "id": principal,
        "sub": principal,
        "user_id": principal,
        "email": principal,
        "role": "admin",
        "roles": ["admin"],
        "is_admin": True,
        "service_key_id": key_id,
        "acting_user": acting_user,
    }
    request.state.ops_center_service_key_checked = True
    return request.state.ops_center_service_key_user


async def require_authenticated_user(request: Request) -> Dict[str, Any]:
    """
    Dependency that requires authentication BEFORE body validation.

    This runs before FastAPI/Pydantic validates the request body,
    preventing information disclosure through validation errors.

    Usage:
        @router.post("/endpoint")
        async def my_endpoint(
            user: Dict = Depends(require_authenticated_user),
            data: MyModel  # ← Validation happens AFTER auth check
        ):
            # user is already authenticated here

    Returns:
        Dict: User data from session (includes user_id, email, roles, etc.)

    Raises:
        HTTPException(401): If not authenticated
    """
    import sys
    import os

    service_key_user = await get_service_key_user(request)
    if service_key_user is not None:
        return service_key_user

    if '/app' not in sys.path:
        sys.path.insert(0, '/app')

    from redis_session import RedisSessionUnavailable, redis_session_manager

    # Check for session token in cookie
    session_token = request.cookies.get("session_token")
    # NB: this dependency now runs on EVERY /api/* request (default-deny AuthMiddleware),
    # so keep per-request logging at debug and never log raw token/PII at info.
    logger.debug(f"[AUTH] session cookie present: {bool(session_token)}")
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please login to access this resource."
        )

    try:
        # Use the startup-configured singleton. This accessor performs one
        # request-time Redis operation and never enters the startup retry loop.
        session_data = redis_session_manager.get_for_request(session_token)
    except RedisSessionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Session service unavailable. Please try again shortly.",
        ) from exc

    if not session_data:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session. Please login again."
        )

    # Session structure: {"user": {user_info}, "access_token": ..., "org_id": ..., ...}
    # Extract user info from the nested "user" key
    user_data = session_data.get("user", {})

    logger.debug(f"[AUTH] session resolved, user present: {bool(user_data)}")
    if not user_data:
        logger.warning("[AUTH] session present but missing user data")
        raise HTTPException(
            status_code=401,
            detail="Session missing user data. Please login again."
        )

    # Ensure user_id field exists (map from Keycloak 'sub' if needed)
    if "user_id" not in user_data:
        user_data["user_id"] = user_data.get("sub") or user_data.get("id", "unknown")

    # Copy org context from session to user data for convenience
    user_data["org_id"] = session_data.get("org_id")
    user_data["org_name"] = session_data.get("org_name")
    user_data["org_role"] = session_data.get("org_role")

    logger.debug(f"Authenticated user: {user_data.get('email', 'unknown')}")
    return user_data


async def require_admin_user(request: Request) -> Dict[str, Any]:
    """
    Dependency that requires admin authentication BEFORE body validation.

    This checks both authentication AND admin role before request processing.

    Usage:
        @router.post("/admin-endpoint")
        async def admin_endpoint(
            user: Dict = Depends(require_admin_user),
            data: MyModel
        ):
            # user is already authenticated AND verified as admin

    Returns:
        Dict: User data from session

    Raises:
        HTTPException(401): If not authenticated
        HTTPException(403): If not admin
    """
    # First check authentication
    user = await require_authenticated_user(request)

    # Check admin role - session stores singular "role", not plural "roles"
    user_role = user.get("role", "")
    user_roles = user.get("roles", [])  # Fallback for legacy sessions

    # Check both singular role and roles array for compatibility
    is_admin = (
        user_role == "admin" or
        user_role == "system_admin" or
        "admin" in user_roles or
        "system_admin" in user_roles
    )

    if not is_admin:
        logger.warning(f"Non-admin user {user.get('email')} (role: {user_role}) attempted admin access")
        raise HTTPException(
            status_code=403,
            detail="Admin access required. You do not have permission to access this resource."
        )

    return user


async def require_org_admin(request: Request, org_id: str) -> Dict[str, Any]:
    """
    Dependency that requires org admin authentication BEFORE body validation.

    Checks if user is either:
    1. System admin (can access any org)
    2. Organization admin for the specified org

    Usage:
        @router.post("/orgs/{org_id}/endpoint")
        async def org_endpoint(
            org_id: str,
            user: Dict = Depends(lambda r: require_org_admin(r, org_id)),
            data: MyModel
        ):
            # user is already verified as org admin

    Args:
        request: FastAPI request object
        org_id: Organization UUID to check membership

    Returns:
        Dict: User data from session

    Raises:
        HTTPException(401): If not authenticated
        HTTPException(403): If not authorized for this org
    """
    import asyncpg
    from database import get_db_connection

    # First check authentication
    user = await require_authenticated_user(request)

    # Check if system admin (can access any org)
    user_role = user.get("role", "")
    user_roles = user.get("roles", [])  # Fallback for legacy sessions
    is_system_admin = (
        user_role == "admin" or
        user_role == "system_admin" or
        "admin" in user_roles or
        "system_admin" in user_roles
    )

    if is_system_admin:
        return user

    # Check org membership and role
    conn = await get_db_connection()
    try:
        member = await conn.fetchrow(
            """
            SELECT role FROM organization_members
            WHERE org_id = $1 AND user_id = $2
            """,
            org_id, user["user_id"]
        )

        if not member:
            logger.warning(
                f"User {user.get('email')} attempted access to org {org_id} without membership"
            )
            raise HTTPException(
                status_code=403,
                detail="Not a member of this organization"
            )

        # Check if user has admin role in org
        if member["role"] not in ["admin", "owner"]:
            logger.warning(
                f"User {user.get('email')} attempted admin action in org {org_id} with role {member['role']}"
            )
            raise HTTPException(
                status_code=403,
                detail="Organization admin access required"
            )

        return user

    finally:
        await conn.close()
