"""
Platform Keys Management API - Admin-Only Provider Key Management

This module provides admin-only endpoints for managing system-level provider API keys:
- OpenRouter API key
- Magic Unicorn provisioning key
- Other platform provider keys

These are DIFFERENT from user BYOK keys (user_api_keys.py) and UC API keys (uc_api_keys.py).

Platform keys are stored in the platform_settings table with encryption.

Database Table: platform_settings
Columns: id, key, value (encrypted), description, category, is_encrypted, created_at, updated_at

Author: Backend API Developer
Date: November 3, 2025
"""

import logging
import os
from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
import asyncpg
from key_encryption import get_encryption

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/platform-keys", tags=["Platform Keys (Admin)"])


# ============================================================================
# Request/Response Models
# ============================================================================

class UpdatePlatformKeyRequest(BaseModel):
    """Request to update a platform API key"""
    api_key: str = Field(..., description="Plain text API key (will be encrypted)", min_length=10)


class PlatformKeyResponse(BaseModel):
    """Response with platform key information"""
    key_name: str
    description: str
    has_key: bool
    key_preview: Optional[str]  # Masked preview if key exists
    last_updated: Optional[str]
    source: str  # database, environment, or not_set


class PlatformKeysListResponse(BaseModel):
    """Response with all platform keys"""
    keys: List[PlatformKeyResponse]
    total: int


# ============================================================================
# Authentication Dependency
# ============================================================================

async def require_admin(request: Request) -> Dict:
    """
    Require admin role from session

    Returns:
        User dict if admin

    Raises:
        HTTPException 401 if not authenticated
        HTTPException 403 if not admin
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

    # Check if user is admin
    user_role = user.get("role", "viewer")
    if user_role != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Admin access required (current role: {user_role})"
        )

    return user


async def get_db_pool(request: Request) -> asyncpg.Pool:
    """Get database pool from app state"""
    if not hasattr(request.app.state, 'db_pool') or not request.app.state.db_pool:
        raise HTTPException(status_code=503, detail="Database connection not available")
    return request.app.state.db_pool


# ============================================================================
# Helper Functions
# ============================================================================

def mask_api_key(api_key: str) -> str:
    """
    Mask API key for display

    Args:
        api_key: Full API key

    Returns:
        Masked key (first 7 chars + ... + last 4 chars)
    """
    if len(api_key) < 12:
        return "***"

    return f"{api_key[:7]}...{api_key[-4:]}"


async def get_platform_key_from_db(db_pool: asyncpg.Pool, key_name: str) -> Optional[str]:
    """
    Get encrypted platform key from database

    Args:
        db_pool: Database pool
        key_name: Key name (e.g., "openrouter_api_key")

    Returns:
        Encrypted key string or None if not found
    """
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("""
            SELECT value
            FROM platform_settings
            WHERE key = $1 AND category = 'api_keys' AND is_secret = TRUE
        """, key_name)

        return result['value'] if result else None


async def set_platform_key_in_db(
    db_pool: asyncpg.Pool,
    key_name: str,
    encrypted_value: str
) -> bool:
    """
    Set encrypted platform key in database

    Args:
        db_pool: Database pool
        key_name: Key name (e.g., "openrouter_api_key")
        encrypted_value: Encrypted API key

    Returns:
        True if successful
    """
    async with db_pool.acquire() as conn:
        # Upsert (insert or update)
        await conn.execute("""
            INSERT INTO platform_settings (key, value, category, is_secret, updated_at)
            VALUES ($1, $2, 'api_keys', TRUE, NOW())
            ON CONFLICT (key)
            DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = NOW()
        """, key_name, encrypted_value)

    return True


# ============================================================================
# Platform Key Definitions
# ============================================================================

PLATFORM_KEYS = {
    "openrouter_api_key": {
        "display_name": "OpenRouter API Key",
        "description": "OpenRouter API key for LLM inference routing",
        "env_var": "OPENROUTER_API_KEY",
        "key_format": "sk-or-v1-..."
    },
    "provisioning_key": {
        "display_name": "Magic Unicorn Provisioning Key",
        "description": "Provisioning key for Magic Unicorn services",
        "env_var": "PROVISIONING_KEY",
        "key_format": "mu-prov-..."
    },
    "litellm_master_key": {
        "display_name": "LiteLLM Master Key",
        "description": "Master key for LiteLLM proxy administration",
        "env_var": "LITELLM_MASTER_KEY",
        "key_format": "sk-litellm-..."
    }
}


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("", response_model=PlatformKeysListResponse)
async def list_platform_keys(
    request: Request,
    current_user: Dict = Depends(require_admin),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    List all platform API keys (admin only)

    Returns information about all configured platform keys with masked previews.
    Shows whether each key is stored in database, environment, or not set.

    Returns:
    - keys: List of platform keys with metadata
    - total: Total number of keys
    """
    try:
        encryption = get_encryption()
        key_list = []

        for key_name, config in PLATFORM_KEYS.items():
            # Check database
            db_encrypted = await get_platform_key_from_db(db_pool, key_name)

            # Check environment
            env_value = os.getenv(config['env_var'])

            # Determine source and preview
            if db_encrypted:
                source = "database"
                has_key = True
                try:
                    decrypted = encryption.decrypt_key(db_encrypted)
                    preview = mask_api_key(decrypted)
                except Exception as e:
                    logger.error(f"Error decrypting {key_name}: {e}")
                    preview = "***"
            elif env_value:
                source = "environment"
                has_key = True
                preview = mask_api_key(env_value)
            else:
                source = "not_set"
                has_key = False
                preview = None

            # Get last updated timestamp from database
            async with db_pool.acquire() as conn:
                result = await conn.fetchrow("""
                    SELECT updated_at FROM platform_settings WHERE key = $1
                """, key_name)

            last_updated = result['updated_at'].isoformat() if result else None

            key_list.append(PlatformKeyResponse(
                key_name=config['display_name'],
                description=config['description'],
                has_key=has_key,
                key_preview=preview,
                last_updated=last_updated,
                source=source
            ))

        logger.info(f"Admin {current_user.get('email', 'unknown')} listed platform keys")

        return PlatformKeysListResponse(
            keys=key_list,
            total=len(key_list)
        )

    except Exception as e:
        logger.error(f"Error listing platform keys: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list platform keys")


@router.put("/openrouter")
async def update_openrouter_key(
    key_request: UpdatePlatformKeyRequest,
    request: Request,
    current_user: Dict = Depends(require_admin),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Update OpenRouter API key (admin only)

    Stores the OpenRouter API key in encrypted form in the database.
    This key is used by LiteLLM for routing LLM inference requests.

    **Note**: After updating, you'll need to restart the LiteLLM container
    or update its configuration to use the new key.

    Request Body:
    - api_key: OpenRouter API key (plain text, will be encrypted)

    Returns:
    - success: True if updated
    - message: Confirmation message
    """
    try:
        # Validate key format (basic check)
        if not key_request.api_key.startswith("sk-or-"):
            logger.warning(f"OpenRouter key doesn't match expected format (sk-or-*)")

        # Encrypt the key
        encryption = get_encryption()
        encrypted_key = encryption.encrypt_key(key_request.api_key)

        # Store in database
        await set_platform_key_in_db(
            db_pool,
            "openrouter_api_key",
            encrypted_key
        )

        logger.info(f"Admin {current_user.get('email', 'unknown')} updated OpenRouter API key")

        return {
            "success": True,
            "message": "OpenRouter API key updated successfully",
            "key_preview": mask_api_key(key_request.api_key),
            "next_steps": [
                "Key stored in database (encrypted)",
                "To use this key, restart LiteLLM container or update its config",
                "See LITELLM_CONFIG_UPDATE.md for instructions"
            ]
        }

    except Exception as e:
        logger.error(f"Error updating OpenRouter key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update OpenRouter key")


@router.put("/provisioning")
async def update_provisioning_key(
    key_request: UpdatePlatformKeyRequest,
    request: Request,
    current_user: Dict = Depends(require_admin),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Update Magic Unicorn provisioning key (admin only)

    Stores the provisioning key in encrypted form in the database.
    This key is used for provisioning Magic Unicorn services.

    Request Body:
    - api_key: Provisioning key (plain text, will be encrypted)

    Returns:
    - success: True if updated
    - message: Confirmation message
    """
    try:
        # Encrypt the key
        encryption = get_encryption()
        encrypted_key = encryption.encrypt_key(key_request.api_key)

        # Store in database
        await set_platform_key_in_db(
            db_pool,
            "provisioning_key",
            encrypted_key
        )

        logger.info(f"Admin {current_user.get('email', 'unknown')} updated provisioning key")

        return {
            "success": True,
            "message": "Provisioning key updated successfully",
            "key_preview": mask_api_key(key_request.api_key)
        }

    except Exception as e:
        logger.error(f"Error updating provisioning key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update provisioning key")


@router.get("/openrouter/decrypted")
async def get_openrouter_key_decrypted(
    request: Request,
    current_user: Dict = Depends(require_admin),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Get decrypted OpenRouter API key (admin only)

    **WARNING**: This exposes the full API key. Use with caution.

    Returns:
    - api_key: Decrypted API key
    - source: database or environment
    """
    try:
        # Check database first
        db_encrypted = await get_platform_key_from_db(db_pool, "openrouter_api_key")

        if db_encrypted:
            encryption = get_encryption()
            api_key = encryption.decrypt_key(db_encrypted)
            source = "database"
        else:
            # Fall back to environment
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise HTTPException(status_code=404, detail="OpenRouter API key not configured")
            source = "environment"

        logger.info(f"Admin {current_user.get('email', 'unknown')} retrieved OpenRouter API key")

        return {
            "api_key": api_key,
            "source": source,
            "warning": "This is the full API key. Keep it secure."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving OpenRouter key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve OpenRouter key")


@router.get("/provisioning/decrypted")
async def get_provisioning_key_decrypted(
    request: Request,
    current_user: Dict = Depends(require_admin),
    db_pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Get decrypted provisioning key (admin only)

    **WARNING**: This exposes the full provisioning key. Use with caution.

    Returns:
    - api_key: Decrypted provisioning key
    - source: database or environment
    """
    try:
        # Check database first
        db_encrypted = await get_platform_key_from_db(db_pool, "provisioning_key")

        if db_encrypted:
            encryption = get_encryption()
            api_key = encryption.decrypt_key(db_encrypted)
            source = "database"
        else:
            # Fall back to environment
            api_key = os.getenv("PROVISIONING_KEY")
            if not api_key:
                raise HTTPException(status_code=404, detail="Provisioning key not configured")
            source = "environment"

        logger.info(f"Admin {current_user.get('email', 'unknown')} retrieved provisioning key")

        return {
            "api_key": api_key,
            "source": source,
            "warning": "This is the full provisioning key. Keep it secure."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving provisioning key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve provisioning key")
