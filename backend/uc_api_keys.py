"""
UC API Keys Management - User API Keys for calling api.unicorncommander.ai

This module manages UC-specific API keys that users can generate to call
api.unicorncommander.ai from external systems (Postman, curl, custom apps, etc.)

Key Features:
- Generate UC API keys with bcrypt hashing
- List user's API keys (with masked preview)
- Revoke API keys
- Track last used timestamp
- Optional expiration dates

Database Table: user_api_keys (already exists)
Columns: id, user_id, key_name, key_hash, key_prefix, permissions, created_at, last_used, expires_at, is_active

Author: Backend API Developer
Date: November 3, 2025
"""

import logging
import os
import secrets
import time
import bcrypt
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
import asyncpg
import json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/account/uc-api-keys", tags=["UC API Keys"])


# ============================================================================
# Permission scopes
# ============================================================================
# llm:* — OpenAI-compatible gateway (chat, models, speech)
# mcp:* — public MCP servers for customer agents (Claude Desktop, Cursor, …)
# mcp:<app> — single-app MCP scope (e.g. mcp:accounting-ops)
DEFAULT_UC_KEY_PERMISSIONS = [
    "llm:inference",
    "llm:models",
    "mcp:accounting-ops",
]

# Step 1.5 is deliberately dark until dogfood enables it.  The endpoint is
# still registered while disabled so the console has a stable wiring target.
AUTO_PROVISION_DEFAULT_UC_API_KEY_ENV = "UC_API_KEY_AUTO_PROVISION_ENABLED"
DEFAULT_ONBOARDING_KEY_NAME = "onboarding-default"
_API_KEY_ELIGIBLE_TIERS = frozenset(
    {
        "app",
        "byok",
        "enterprise",
        "founder_friend",
        "managed",
        "professional",
        "starter",
        "vip_founder",
    }
)

_LLM_PERMISSIONS = frozenset({"llm:inference", "llm:models", "llm:embeddings", "llm:audio"})
_MCP_WILDCARD = "mcp:*"


def _is_allowed_permission(perm: str) -> bool:
    """Allow known llm scopes, mcp:*, and mcp:<app-slug> (lowercase slug)."""
    if not isinstance(perm, str) or not perm:
        return False
    if perm in _LLM_PERMISSIONS:
        return True
    if perm == _MCP_WILDCARD:
        return True
    if perm.startswith("mcp:") and len(perm) > 4:
        slug = perm[4:]
        # app slug: lowercase letters, digits, hyphen
        return bool(slug) and all(c.isalnum() or c == "-" for c in slug) and slug == slug.lower()
    return False


def sanitize_permissions(permissions: Optional[List[str]]) -> List[str]:
    """Validate and normalize a permissions list. Raises HTTP 400 on unknowns."""
    if permissions is None:
        return list(DEFAULT_UC_KEY_PERMISSIONS)
    if not isinstance(permissions, list) or not permissions:
        raise HTTPException(
            status_code=400,
            detail="permissions must be a non-empty list of scope strings",
        )
    cleaned: List[str] = []
    seen = set()
    for p in permissions:
        if not _is_allowed_permission(p):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown permission '{p}'. Allowed: llm:inference, llm:models, "
                    f"llm:embeddings, llm:audio, mcp:*, mcp:<app> (e.g. mcp:accounting-ops)"
                ),
            )
        if p not in seen:
            seen.add(p)
            cleaned.append(p)
    return cleaned


def key_has_mcp_permission(permissions: List[str], app: Optional[str] = None) -> bool:
    """True if permissions grant MCP access (wildcard or specific app)."""
    if not permissions:
        return False
    if _MCP_WILDCARD in permissions:
        return True
    if app:
        return f"mcp:{app}" in permissions
    # any mcp:* or mcp:<app>
    return any(p == _MCP_WILDCARD or p.startswith("mcp:") for p in permissions)


# ============================================================================
# Request/Response Models
# ============================================================================

class CreateUCAPIKeyRequest(BaseModel):
    """Request to create a new UC API key"""
    name: str = Field(..., description="Descriptive name for the key", min_length=1, max_length=255)
    expires_in_days: Optional[int] = Field(90, description="Days until expiration (default: 90)", ge=1, le=3650)
    permissions: Optional[List[str]] = Field(
        default_factory=lambda: list(DEFAULT_UC_KEY_PERMISSIONS),
        description="API permissions (llm:* and/or mcp:*)",
    )


class UCAPIKeyResponse(BaseModel):
    """Response with UC API key information"""
    key_id: str
    key_name: str
    key_preview: str  # First 8 and last 4 chars (uc_12345...abcd)
    permissions: List[str]
    created_at: str
    last_used: Optional[str]
    expires_at: Optional[str]
    is_active: bool
    status: str  # active, expired, revoked


class UCAPIKeyCreateResponse(BaseModel):
    """Response when creating a new API key (includes full key ONE TIME)"""
    key_id: str
    api_key: str  # FULL KEY - shown only once!
    key_name: str
    key_preview: str
    permissions: List[str]
    created_at: str
    expires_at: Optional[str]
    warning: str = "Save this API key now. You won't be able to see it again."


class EnsureDefaultUCAPIKeyResponse(BaseModel):
    """Result of the idempotent signup/onboarding API-key step."""

    enabled: bool
    eligible: bool
    created: bool
    key_id: Optional[str] = None
    api_key: Optional[str] = None
    key_name: Optional[str] = None
    key_preview: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    reason: Optional[str] = None
    warning: Optional[str] = None


# ============================================================================
# Authentication Dependency
# ============================================================================

async def get_current_user(request: Request) -> Dict:
    """
    Get current authenticated user from session

    Returns:
        User dict with user_id, email, role

    Raises:
        HTTPException 401 if not authenticated
    """
    session_token = request.cookies.get("session_token")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated - no session token")

    # Get sessions from app state
    sessions = getattr(request.app.state, "sessions", {})
    session_data = sessions.get(session_token)

    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session - please login again")

    user = session_data.get("user", {})
    if not user:
        raise HTTPException(status_code=401, detail="User not found in session")

    # Ensure user_id exists
    if "user_id" not in user:
        user["user_id"] = user.get("sub") or user.get("id", "unknown")

    return user


async def get_db_pool(request: Request) -> asyncpg.Pool:
    """Get database pool from app state"""
    if not hasattr(request.app.state, 'db_pool') or not request.app.state.db_pool:
        raise HTTPException(status_code=503, detail="Database connection not available")
    return request.app.state.db_pool


# ============================================================================
# Helper Functions
# ============================================================================

def generate_uc_api_key() -> tuple[str, str]:
    """
    Generate a secure UC API key

    Returns:
        (full_key, prefix) tuple
        Example: ("REMOVED", "uc_12345")
    """
    # Generate 32 random bytes (256 bits)
    random_bytes = secrets.token_bytes(32)
    key_hex = random_bytes.hex()

    # Format: uc_<64-char-hex>
    full_key = f"uc_{key_hex}"
    prefix = full_key[:8]  # "uc_12345"

    return full_key, prefix


def hash_api_key(api_key: str) -> str:
    """Hash API key with bcrypt"""
    return bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """Verify API key against stored hash"""
    try:
        return bcrypt.checkpw(api_key.encode(), key_hash.encode())
    except Exception as e:
        logger.error(f"Key verification error: {e}")
        return False


def mask_api_key(full_key: str) -> str:
    """
    Mask API key for display

    Args:
        full_key: Full API key (uc_<64-char-hex>)

    Returns:
        Masked key (uc_12345...abcd)
    """
    if len(full_key) < 12:
        return "***"

    return f"{full_key[:8]}...{full_key[-4:]}"


def get_key_status(key_record) -> str:
    """Determine key status"""
    if not key_record['is_active']:
        return "revoked"
    if key_record['expires_at'] and key_record['expires_at'] < datetime.utcnow():
        return "expired"
    return "active"


def auto_provision_default_uc_api_key_enabled() -> bool:
    """Return whether signup/onboarding key provisioning is enabled."""
    return os.getenv(
        AUTO_PROVISION_DEFAULT_UC_API_KEY_ENV, "false"
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _normalize_tier(value) -> Optional[str]:
    """Normalize a tier value from Keycloak attributes or a session."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    return str(value).strip().lower().replace("-", "_") or None


def plan_allows_default_uc_api_key(
    plan_tier: Optional[str],
    api_calls_limit: Optional[int] = None,
) -> bool:
    """Apply the existing API-access plan boundary, failing closed for unknown tiers.

    The customer-facing tier definitions exclude ``free`` and ``trial`` from API
    access.  The database's ``api_calls_limit`` is authoritative for custom tiers;
    the known tier list is used when a session is all the endpoint can resolve.
    """
    tier = _normalize_tier(plan_tier)
    if not tier or tier in {"free", "trial"}:
        return False

    if api_calls_limit is not None:
        try:
            return int(api_calls_limit) != 0
        except (TypeError, ValueError):
            return False

    return tier in _API_KEY_ELIGIBLE_TIERS


def _record_value(record, key: str, default=None):
    """Read a value from an asyncpg Record or a plain mapping used by tests."""
    if record is None:
        return default
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return default


def _session_plan_tier(request: Optional[Request], current_user: Dict) -> Optional[str]:
    """Read a plan from the authenticated user/session without trusting request data."""
    candidates = [
        current_user.get("subscription_tier"),
        current_user.get("plan_tier"),
        current_user.get("tier"),
    ]

    if request is not None:
        session_token = request.cookies.get("session_token")
        sessions = getattr(request.app.state, "sessions", {})
        session_data = sessions.get(session_token) if session_token else None
        if session_data:
            candidates.extend(
                [
                    session_data.get("subscription_tier"),
                    session_data.get("plan_tier"),
                    session_data.get("tier"),
                ]
            )
            session_user = session_data.get("user") or {}
            candidates.extend(
                [
                    session_user.get("subscription_tier"),
                    session_user.get("plan_tier"),
                    session_user.get("tier"),
                ]
            )

    for candidate in candidates:
        tier = _normalize_tier(candidate)
        if tier:
            return tier
    return None


async def _resolve_default_key_plan(
    request: Optional[Request],
    current_user: Dict,
    db_pool: asyncpg.Pool,
) -> tuple[Optional[str], Optional[int]]:
    """Resolve the caller's org plan, preferring the database over session data."""
    user_id = current_user.get("user_id")
    session_tier = _session_plan_tier(request, current_user)

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT o.plan_tier, st.api_calls_limit
                FROM organization_members om
                JOIN organizations o ON o.id = om.org_id
                LEFT JOIN users u ON u.id::text = om.user_id
                LEFT JOIN subscription_tiers st ON st.tier_code = o.plan_tier
                WHERE om.user_id = $1 OR u.zitadel_id = $1
                LIMIT 1
                """,
                str(user_id),
            )
        if row:
            return _normalize_tier(_record_value(row, "plan_tier")), _record_value(
                row, "api_calls_limit"
            )
    except Exception as exc:
        # A missing/legacy entitlement table should not turn a login into a 500.
        # If a trusted session carries a known tier, use that; otherwise fail closed.
        logger.warning(
            "Default API-key plan lookup failed for user %s: %s", user_id, exc
        )

    return session_tier, None


def _isoformat(value) -> Optional[str]:
    """Format a timestamp from asyncpg or a test double."""
    return (
        value.isoformat()
        if value is not None and hasattr(value, "isoformat")
        else value
    )


def _permissions_from_record(record) -> List[str]:
    permissions = _record_value(record, "permissions", [])
    if isinstance(permissions, str):
        permissions = json.loads(permissions)
    return list(permissions or [])


def _existing_default_key_response(record) -> EnsureDefaultUCAPIKeyResponse:
    """Return metadata for an existing default key without returning its secret."""
    key_prefix = _record_value(record, "key_prefix") or ""
    return EnsureDefaultUCAPIKeyResponse(
        enabled=True,
        eligible=True,
        created=False,
        key_id=str(_record_value(record, "id")),
        key_name=_record_value(record, "key_name", DEFAULT_ONBOARDING_KEY_NAME),
        key_preview=f"{key_prefix}...****" if key_prefix else None,
        permissions=_permissions_from_record(record),
        created_at=_isoformat(_record_value(record, "created_at")),
        expires_at=_isoformat(_record_value(record, "expires_at")),
        reason="already_provisioned",
    )


async def ensure_default_uc_api_key(
    current_user: Dict,
    db_pool: asyncpg.Pool,
    request: Optional[Request] = None,
) -> EnsureDefaultUCAPIKeyResponse:
    """Mint the reserved onboarding key once and only once for an entitled user."""
    if not auto_provision_default_uc_api_key_enabled():
        return EnsureDefaultUCAPIKeyResponse(
            enabled=False,
            eligible=False,
            created=False,
            reason="feature_disabled",
        )

    user_id = (
        current_user.get("user_id") or current_user.get("sub") or current_user.get("id")
    )
    if not user_id or user_id == "unknown":
        raise HTTPException(
            status_code=401, detail="Authenticated user has no stable ID"
        )

    plan_tier, api_calls_limit = await _resolve_default_key_plan(
        request, current_user, db_pool
    )
    if not plan_allows_default_uc_api_key(plan_tier, api_calls_limit):
        return EnsureDefaultUCAPIKeyResponse(
            enabled=True,
            eligible=False,
            created=False,
            reason="plan_not_entitled",
        )

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # There is no uniqueness constraint on user_api_keys.key_name.  The
            # advisory lock makes the read-then-insert idempotence safe when two
            # onboarding requests arrive at the same time.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                f"uc-api-key:{user_id}:{DEFAULT_ONBOARDING_KEY_NAME}",
            )
            existing = await conn.fetchrow(
                """
                SELECT id, key_name, key_prefix, permissions, created_at, expires_at
                FROM user_api_keys
                WHERE user_id = $1 AND key_name = $2
                ORDER BY created_at ASC
                LIMIT 1
                """,
                user_id,
                DEFAULT_ONBOARDING_KEY_NAME,
            )
            if existing:
                return _existing_default_key_response(existing)

            api_key, prefix = generate_uc_api_key()
            key_hash = hash_api_key(api_key)
            expires_at = datetime.utcnow() + timedelta(days=90)
            result = await conn.fetchrow(
                """
                INSERT INTO user_api_keys (
                    user_id, key_name, key_hash, key_prefix,
                    permissions, expires_at
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                RETURNING id, created_at
                """,
                user_id,
                DEFAULT_ONBOARDING_KEY_NAME,
                key_hash,
                prefix,
                json.dumps(DEFAULT_UC_KEY_PERMISSIONS),
                expires_at,
            )

    # Deliberately log only non-secret metadata.  The plaintext is returned in
    # this response and is never retained or interpolated into a log message.
    logger.info("Provisioned default UC API key for user %s", user_id)
    return EnsureDefaultUCAPIKeyResponse(
        enabled=True,
        eligible=True,
        created=True,
        key_id=str(_record_value(result, "id")),
        api_key=api_key,
        key_name=DEFAULT_ONBOARDING_KEY_NAME,
        key_preview=mask_api_key(api_key),
        permissions=list(DEFAULT_UC_KEY_PERMISSIONS),
        created_at=_isoformat(_record_value(result, "created_at")),
        expires_at=expires_at.isoformat(),
        warning="Save this API key now. You won't be able to see it again.",
    )


# ============================================================================
# API Endpoints
# ============================================================================


@router.post(
    "/ensure-default",
    response_model=EnsureDefaultUCAPIKeyResponse,
    status_code=200,
)
async def ensure_default_uc_api_key_endpoint(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    """Step 1.5: provision the entitled user's default UC API key once.

    The console should call this after the first authenticated signup/onboarding
    response.  The plaintext ``api_key`` is present only when this call creates
    the row; retries return metadata without the secret.
    """
    if not auto_provision_default_uc_api_key_enabled():
        return EnsureDefaultUCAPIKeyResponse(
            enabled=False,
            eligible=False,
            created=False,
            reason="feature_disabled",
        )

    try:
        db_pool = await get_db_pool(request)
        return await ensure_default_uc_api_key(current_user, db_pool, request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error ensuring default UC API key: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to provision default API key"
        )


@router.post("", response_model=UCAPIKeyCreateResponse, status_code=201)
async def create_uc_api_key(
    key_request: CreateUCAPIKeyRequest,
    request: Request,
    current_user: Dict = Depends(get_current_user),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Create a new UC API key for the authenticated user

    This generates a unique API key that can be used to call api.unicorncommander.ai
    endpoints from external systems (Postman, curl, custom applications).

    **IMPORTANT**: The full API key is shown ONLY ONCE in the response. Save it securely.

    Request Body:
    - name: Descriptive name for the key (e.g., "Production Server", "Mobile App")
    - expires_in_days: Days until expiration (default: 90, max: 3650)
    - permissions: List of allowed permissions (default: ["llm:inference", "llm:models"])

    Returns:
    - api_key: The full API key (SHOWN ONLY ONCE!)
    - key_id: UUID of the key
    - key_preview: Masked preview (uc_12345...abcd)
    - created_at: Creation timestamp
    - expires_at: Expiration timestamp
    """
    try:
        user_id = current_user.get("user_id")
        permissions = sanitize_permissions(key_request.permissions)

        # Generate API key
        api_key, prefix = generate_uc_api_key()
        key_hash = hash_api_key(api_key)

        # Calculate expiration
        expires_at = datetime.utcnow() + timedelta(days=key_request.expires_in_days)

        # Store in database
        import json as json_lib
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("""
                INSERT INTO user_api_keys (
                    user_id, key_name, key_hash, key_prefix,
                    permissions, expires_at
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                RETURNING id, created_at
            """, user_id, key_request.name, key_hash, prefix,
                json_lib.dumps(permissions), expires_at)

        logger.info(f"Created UC API key '{key_request.name}' for user {user_id} perms={permissions}")

        return UCAPIKeyCreateResponse(
            key_id=str(result['id']),
            api_key=api_key,  # FULL KEY - shown only once!
            key_name=key_request.name,
            key_preview=mask_api_key(api_key),
            permissions=permissions,
            created_at=result['created_at'].isoformat(),
            expires_at=expires_at.isoformat()
        )

    except Exception as e:
        logger.error(f"Error creating UC API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create API key")


@router.get("", response_model=List[UCAPIKeyResponse])
async def list_uc_api_keys(
    request: Request,
    current_user: Dict = Depends(get_current_user),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    List all UC API keys for the authenticated user

    Returns a list of API keys with masked previews (full keys are never shown again).

    Response includes:
    - key_id: UUID of the key
    - key_name: Descriptive name
    - key_preview: Masked preview (uc_12345...abcd)
    - permissions: Allowed API permissions
    - created_at: Creation timestamp
    - last_used: Last usage timestamp (null if never used)
    - expires_at: Expiration timestamp
    - is_active: Whether key is active
    - status: active, expired, or revoked
    """
    try:
        user_id = current_user.get("user_id")

        async with db_pool.acquire() as conn:
            keys = await conn.fetch("""
                SELECT id, key_name, key_prefix, permissions,
                       created_at, last_used, expires_at, is_active
                FROM user_api_keys
                WHERE user_id = $1
                ORDER BY created_at DESC
            """, user_id)

        return [
            UCAPIKeyResponse(
                key_id=str(k['id']),
                key_name=k['key_name'],
                key_preview=f"{k['key_prefix']}...****",  # Mask based on prefix
                permissions=k["permissions"] if isinstance(k["permissions"], list) else json.loads(k["permissions"]) if isinstance(k["permissions"], str) else list(k["permissions"] or []),
                created_at=k['created_at'].isoformat(),
                last_used=k['last_used'].isoformat() if k['last_used'] else None,
                expires_at=k['expires_at'].isoformat() if k['expires_at'] else None,
                is_active=k['is_active'],
                status=get_key_status(k)
            )
            for k in keys
        ]

    except Exception as e:
        logger.error(f"Error listing UC API keys: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list API keys")


@router.delete("/{key_id}")
async def revoke_uc_api_key(
    key_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Revoke a UC API key

    This marks the key as inactive. The key will no longer work for API calls.

    Path Parameters:
    - key_id: UUID of the key to revoke

    Returns:
    - success: True if revoked
    - message: Confirmation message
    """
    try:
        user_id = current_user.get("user_id")

        async with db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE user_api_keys
                SET is_active = FALSE
                WHERE id = $1 AND user_id = $2
            """, UUID(key_id), user_id)

        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="API key not found")

        logger.info(f"Revoked UC API key {key_id} for user {user_id}")

        return {
            "success": True,
            "message": "API key revoked successfully",
            "key_id": key_id
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid key_id format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking UC API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to revoke API key")


# === T6 ===
class RegenerateUCAPIKeyRequest(BaseModel):
    """Optional body for key regeneration"""
    expires_in_days: Optional[int] = Field(
        90, description="Days until the regenerated key expires (default: 90)", ge=1, le=3650
    )


@router.post("/{key_id}/regenerate", response_model=UCAPIKeyCreateResponse)
async def regenerate_uc_api_key(
    key_id: str,
    request: Request,
    key_request: RegenerateUCAPIKeyRequest = RegenerateUCAPIKeyRequest(),
    current_user: Dict = Depends(get_current_user),
    db_pool: asyncpg.Pool = Depends(get_db_pool),
):
    """
    Regenerate a UC API key (same creation pathway as POST /uc-api-keys).

    Generates a fresh secret with generate_uc_api_key(), bcrypt-hashes it, and
    replaces the stored hash + prefix in a single UPDATE on the caller's own
    row — so the old secret is revoked atomically the moment the new one
    exists. Name and permissions are preserved; the expiry window restarts.

    **IMPORTANT**: The new full key is shown ONLY ONCE in the response.

    Returns 404 if the key doesn't exist or belongs to another user,
    409 if the key was revoked (revoked keys stay revoked — create a new one).
    """
    try:
        user_id = current_user.get("user_id")

        try:
            key_uuid = UUID(key_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid key_id format")

        # Same creation pathway as the create endpoint: random secret + bcrypt
        api_key, prefix = generate_uc_api_key()
        key_hash = hash_api_key(api_key)
        expires_at = datetime.utcnow() + timedelta(days=key_request.expires_in_days)

        async with db_pool.acquire() as conn:
            # Ownership check first so we can distinguish 404 from 409
            existing = await conn.fetchrow("""
                SELECT id, key_name, is_active
                FROM user_api_keys
                WHERE id = $1 AND user_id = $2
            """, key_uuid, user_id)

            if not existing:
                raise HTTPException(status_code=404, detail="API key not found")

            if not existing["is_active"]:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot regenerate a revoked key. Generate a new key instead.",
                )

            # Atomic swap: the old secret stops working the instant this commits
            result = await conn.fetchrow("""
                UPDATE user_api_keys
                SET key_hash = $3, key_prefix = $4, expires_at = $5
                WHERE id = $1 AND user_id = $2 AND is_active = TRUE
                RETURNING id, key_name, permissions, created_at
            """, key_uuid, user_id, key_hash, prefix, expires_at)

        if not result:
            raise HTTPException(status_code=404, detail="API key not found")

        permissions = result["permissions"]
        if isinstance(permissions, str):
            permissions = json.loads(permissions)
        permissions = list(permissions or [])

        logger.info(f"Regenerated UC API key {key_id} ('{result['key_name']}') for user {user_id}")

        return UCAPIKeyCreateResponse(
            key_id=str(result["id"]),
            api_key=api_key,  # NEW FULL KEY - shown only once!
            key_name=result["key_name"],
            key_preview=mask_api_key(api_key),
            permissions=permissions,
            created_at=result["created_at"].isoformat(),
            expires_at=expires_at.isoformat(),
            warning="Key regenerated! Save this new API key now. The old key is now invalid.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating UC API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to regenerate API key")


@router.get("/{key_id}", response_model=UCAPIKeyResponse)
async def get_uc_api_key(
    key_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Get details of a specific UC API key

    Returns key information with masked preview (full key is never shown again).

    Path Parameters:
    - key_id: UUID of the key

    Returns:
    - UCAPIKeyResponse with key details
    """
    try:
        user_id = current_user.get("user_id")

        async with db_pool.acquire() as conn:
            key = await conn.fetchrow("""
                SELECT id, key_name, key_prefix, permissions,
                       created_at, last_used, expires_at, is_active
                FROM user_api_keys
                WHERE id = $1 AND user_id = $2
            """, UUID(key_id), user_id)

        if not key:
            raise HTTPException(status_code=404, detail="API key not found")

        return UCAPIKeyResponse(
            key_id=str(key['id']),
            key_name=key['key_name'],
            key_preview=f"{key['key_prefix']}...****",
            permissions=key['permissions'],
            created_at=key['created_at'].isoformat(),
            last_used=key['last_used'].isoformat() if key['last_used'] else None,
            expires_at=key['expires_at'].isoformat() if key['expires_at'] else None,
            is_active=key['is_active'],
            status=get_key_status(key)
        )

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid key_id format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting UC API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get API key")


# ============================================================================
# P10: "Sign in with Unicorn Commander" — mint a key from a Keycloak Bearer
# ============================================================================
# Native apps (Majiks DJ copilot) complete an OAuth device flow against the
# uchub realm and call this endpoint with the resulting access token to mint
# a uc_ API key for https://api.unicorncommander.ai/api/v1/llm — no Ops-Center
# session cookie involved. Token verification reuses the entitlements JWKS
# pattern (RS256, allowlisted uchub issuers, both realms).

from entitlements_api import _verify_bearer as _verify_kc_bearer  # noqa: E402

_MINT_RATE_LIMIT = 5        # mints
_MINT_RATE_WINDOW = 3600.0  # per hour, per user (in-process; server runs single-worker)
_mint_attempts: Dict[str, List[float]] = {}


def _check_mint_rate_limit(user_id: str) -> None:
    """Modest fixed-window per-user limit so key minting stays boring."""
    now = time.time()
    attempts = [t for t in _mint_attempts.get(user_id, []) if now - t < _MINT_RATE_WINDOW]
    if len(attempts) >= _MINT_RATE_LIMIT:
        retry_after = int(_MINT_RATE_WINDOW - (now - attempts[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {_MINT_RATE_LIMIT} key mints per hour. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
    attempts.append(now)
    _mint_attempts[user_id] = attempts


class MintViaTokenRequest(BaseModel):
    """Mint (or replace) the caller's API key for a named app, authed by a KC Bearer."""
    name: str = Field("majiks-dj", description="App key name (one live key per name)",
                      min_length=1, max_length=255)
    expires_in_days: Optional[int] = Field(90, ge=1, le=3650)
    # Default stays LLM-only for native apps (Majiks DJ); pass mcp:* explicitly
    # when the client needs Ops MCP. Account-page mint uses DEFAULT_UC_KEY_PERMISSIONS.
    permissions: Optional[List[str]] = Field(["llm:inference", "llm:models"])


class MintViaTokenResponse(UCAPIKeyCreateResponse):
    """Create response + identity/credits context for the signing-in app."""
    replaced_key_ids: List[str] = []
    email: Optional[str] = None
    credits_remaining: Optional[float] = None
    tier: Optional[str] = None


@router.post("/mint-via-token", response_model=MintViaTokenResponse, status_code=201)
async def mint_uc_api_key_via_token(
    request: Request,
    body: MintViaTokenRequest = MintViaTokenRequest(),
    db_pool: asyncpg.Pool = Depends(get_db_pool),
):
    """
    Mint a uc_ API key using a Keycloak (uchub realm) Bearer access token.

    Auth: `Authorization: Bearer <KC RS256 access token>` — verified via JWKS
    against the allowlisted uchub issuers (same pattern as /api/v1/entitlements).
    No session cookie or CSRF token required (path is exempted; it verifies its
    own bearer).

    Behavior:
    - One live key per app name: any active keys with the same `name` owned by
      the caller are revoked in the same transaction (replaced_key_ids).
    - First-time users get their org auto-provisioned exactly like SSO login.
    - Returns the plaintext key ONCE, plus expiry and a best-effort credits
      snapshot (same source as GET /api/v1/llm/credits).
    - Rate limited per user (5/hour).
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    claims = _verify_kc_bearer(token)  # 401 on bad signature / untrusted iss / expiry
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token has no sub claim")
    email = claims.get("email")

    _check_mint_rate_limit(user_id)

    # Resolve/create the local user's org context EXACTLY the way SSO login does
    # (server.oauth_callback): get_user_org_context, then auto-provision for
    # first-time non-admin users. Late import — server.py imports this module.
    from server import get_user_org_context, auto_provision_user_org
    org_context = await get_user_org_context(user_id, email)
    realm_roles = (claims.get("realm_access") or {}).get("roles") or []
    if not org_context.get("org_id") and "admin" not in realm_roles:
        display_name = claims.get("name") or claims.get("preferred_username") or (email or "user")
        try:
            org_context = await auto_provision_user_org(
                user_id=user_id, email=email, display_name=display_name
            )
            logger.info(f"mint-via-token: auto-provisioned org for first-time user {email}")
        except Exception as provision_error:
            # Key minting still proceeds — org context is not required for per-user credits.
            logger.error(f"mint-via-token: auto-provisioning failed for {email}: {provision_error}")

    permissions = sanitize_permissions(body.permissions)
    api_key, prefix = generate_uc_api_key()
    key_hash = hash_api_key(api_key)
    expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days)

    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                replaced = await conn.fetch("""
                    UPDATE user_api_keys SET is_active = FALSE
                    WHERE user_id = $1 AND key_name = $2 AND is_active = TRUE
                    RETURNING id
                """, user_id, body.name)
                result = await conn.fetchrow("""
                    INSERT INTO user_api_keys (
                        user_id, key_name, key_hash, key_prefix, permissions, expires_at
                    )
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    RETURNING id, created_at
                """, user_id, body.name, key_hash, prefix,
                    json.dumps(permissions), expires_at)
    except Exception as db_err:
        logger.error(f"mint-via-token: DB error for user {user_id}: {db_err}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to mint API key")

    # Credits snapshot — same source as GET /api/v1/llm/credits (best-effort;
    # also auto-provisions the trial credit account for brand-new users).
    credits_remaining = None
    tier = None
    try:
        credit_system = getattr(request.app.state, "credit_system", None)
        if credit_system:
            credits_remaining = await credit_system.get_user_credits(user_id)
            tier = await credit_system.get_user_tier(user_id)
    except Exception as credit_err:
        logger.warning(f"mint-via-token: credits snapshot failed for {user_id}: {credit_err}")

    if replaced:
        logger.info(
            f"mint-via-token: replaced {len(replaced)} prior '{body.name}' key(s) for user {user_id}"
        )
    logger.info(
        f"mint-via-token: minted '{body.name}' key for user {user_id} (expires {expires_at.date()})"
    )

    return MintViaTokenResponse(
        key_id=str(result["id"]),
        api_key=api_key,  # FULL KEY — shown only once!
        key_name=body.name,
        key_preview=mask_api_key(api_key),
        permissions=permissions,
        created_at=result["created_at"].isoformat(),
        expires_at=expires_at.isoformat(),
        replaced_key_ids=[str(r["id"]) for r in replaced],
        email=email,
        credits_remaining=credits_remaining,
        tier=tier,
    )


@router.post("/revoke-self")
async def revoke_self_uc_api_key(
    request: Request,
    db_pool: asyncpg.Pool = Depends(get_db_pool),
):
    """
    Revoke exactly the API key presented as the Bearer token.

    Native-app sign-out (P10 \"Sign in with Unicorn Commander\"): the app holds
    only its own uc_ key, so the key authenticates AND names the row to revoke.
    No session cookie or CSRF involved; nothing but the presented key is
    affected. 401 for missing/unknown/expired keys (revoking an already
    revoked key therefore also 401s, which is fine for a best-effort client).
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth.split(" ", 1)[1].strip()
    if not token.startswith("uc_"):
        raise HTTPException(status_code=401, detail="Not an API key")

    from api_key_manager import get_api_key_manager
    try:
        manager = get_api_key_manager()
        info = await manager.validate_api_key(token)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Key manager not ready")
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_api_keys SET is_active = FALSE WHERE id = $1",
            UUID(info["key_id"]),
        )
    logger.info(
        "revoke-self: key %s revoked by its owner (user %s)",
        info["key_id"], info["user_id"],
    )
    return {"success": True, "key_id": info["key_id"]}
