"""
Tier Features API
Manage feature associations with subscription tiers.
"""

import os
from typing import List, Optional
from datetime import datetime

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field

# Router configuration
router = APIRouter(prefix="/api/v1", tags=["subscriptions", "features"])


# =============================================================================
# Authentication
# =============================================================================

async def get_current_admin(request: Request) -> str:
    """Get current admin user from session"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    sessions = getattr(request.app.state, "sessions", {})
    session_data = sessions.get(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")

    user = session_data.get("user", {})
    username = user.get("username") or user.get("email", "unknown")

    # Check if user has admin role
    role = user.get("role", "").lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return username


# =============================================================================
# Pydantic Models
# =============================================================================

class FeatureInfo(BaseModel):
    """Feature information"""
    id: int
    feature_key: str
    feature_name: str
    category: str
    description: Optional[str] = None
    is_active: bool
    sort_order: int


class TierFeatureResponse(BaseModel):
    """Tier feature association"""
    tier_id: int
    tier_code: str
    tier_name: str
    feature_id: int
    feature_key: str
    feature_name: str
    category: str
    enabled: bool
    description: Optional[str] = None


class TierFeaturesListResponse(BaseModel):
    """Complete list of features for a tier"""
    tier_id: int
    tier_code: str
    tier_name: str
    features: List[FeatureInfo]


class UpdateTierFeatureRequest(BaseModel):
    """Request to update a tier-feature association"""
    feature_key: str = Field(..., description="Feature key to update")
    enabled: bool = Field(..., description="Whether to enable or disable this feature")


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
# Public Endpoints (No Auth Required)
# =============================================================================

@router.get("/tiers/features", response_model=List[TierFeaturesListResponse])
async def list_all_tier_features():
    """
    Get all subscription tiers with their associated features.
    This endpoint is public - no authentication required.
    """
    conn = await get_db_connection()
    try:
        # Get all active tiers
        tiers_query = """
            SELECT id, tier_code, tier_name
            FROM subscription_tiers
            WHERE is_active = TRUE
            ORDER BY sort_order
        """
        tiers = await conn.fetch(tiers_query)

        result = []
        for tier in tiers:
            # Get features for this tier
            features_query = """
                SELECT
                    fd.id,
                    fd.feature_key,
                    fd.feature_name,
                    fd.category,
                    fd.description,
                    fd.is_active,
                    fd.sort_order
                FROM tier_features tf
                JOIN feature_definitions fd ON tf.feature_key = fd.feature_key
                WHERE tf.tier_id = $1 AND tf.enabled = TRUE AND fd.is_active = TRUE
                ORDER BY fd.category, fd.sort_order, fd.feature_name
            """
            features = await conn.fetch(features_query, tier['id'])

            result.append({
                "tier_id": tier['id'],
                "tier_code": tier['tier_code'],
                "tier_name": tier['tier_name'],
                "features": [dict(f) for f in features]
            })

        return result
    finally:
        await conn.close()


@router.get("/tiers/{tier_code}/features", response_model=TierFeaturesListResponse)
async def get_tier_features(tier_code: str):
    """
    Get all features for a specific tier by tier code.
    This endpoint is public - no authentication required.

    - **tier_code**: Tier code (e.g., 'vip_founder', 'byok', 'managed')
    """
    conn = await get_db_connection()
    try:
        # Get tier info
        tier_query = """
            SELECT id, tier_code, tier_name
            FROM subscription_tiers
            WHERE tier_code = $1 AND is_active = TRUE
        """
        tier = await conn.fetchrow(tier_query, tier_code)

        if not tier:
            raise HTTPException(status_code=404, detail=f"Tier '{tier_code}' not found")

        # Get features for this tier
        features_query = """
            SELECT
                fd.id,
                fd.feature_key,
                fd.feature_name,
                fd.category,
                fd.description,
                fd.is_active,
                fd.sort_order
            FROM tier_features tf
            JOIN feature_definitions fd ON tf.feature_key = fd.feature_key
            WHERE tf.tier_id = $1 AND tf.enabled = TRUE AND fd.is_active = TRUE
            ORDER BY fd.category, fd.sort_order, fd.feature_name
        """
        features = await conn.fetch(features_query, tier['id'])

        return {
            "tier_id": tier['id'],
            "tier_code": tier['tier_code'],
            "tier_name": tier['tier_name'],
            "features": [dict(f) for f in features]
        }
    finally:
        await conn.close()


# =============================================================================
# Admin Endpoints (Auth Required)
# =============================================================================

@router.get("/admin/tiers/features/detailed", response_model=List[TierFeatureResponse])
async def list_all_tier_features_detailed(
    admin: str = Depends(get_current_admin)
):
    """
    Get detailed view of all tier-feature associations.
    Admin only.
    """
    conn = await get_db_connection()
    try:
        query = """
            SELECT
                st.id as tier_id,
                st.tier_code,
                st.tier_name,
                fd.id as feature_id,
                fd.feature_key,
                fd.feature_name,
                fd.category,
                fd.description,
                tf.enabled
            FROM tier_features tf
            JOIN subscription_tiers st ON tf.tier_id = st.id
            JOIN feature_definitions fd ON tf.feature_key = fd.feature_key
            WHERE st.is_active = TRUE AND fd.is_active = TRUE
            ORDER BY st.sort_order, fd.category, fd.sort_order, fd.feature_name
        """
        rows = await conn.fetch(query)
        return [dict(row) for row in rows]
    finally:
        await conn.close()


@router.put("/admin/tiers/{tier_code}/features")
async def update_tier_features(
    tier_code: str,
    updates: List[UpdateTierFeatureRequest],
    admin: str = Depends(get_current_admin)
):
    """
    Update which features are enabled for a specific tier.
    Admin only.

    - **tier_code**: Tier code to update
    - **updates**: List of feature updates
    """
    conn = await get_db_connection()
    try:
        # Get tier ID
        tier = await conn.fetchrow(
            "SELECT id FROM subscription_tiers WHERE tier_code = $1",
            tier_code
        )
        if not tier:
            raise HTTPException(status_code=404, detail=f"Tier '{tier_code}' not found")

        tier_id = tier['id']

        # Update each feature
        updated_count = 0
        for update in updates:
            # Check if association exists
            existing = await conn.fetchrow(
                "SELECT id FROM tier_features WHERE tier_id = $1 AND feature_key = $2",
                tier_id, update.feature_key
            )

            if existing:
                # Update existing
                await conn.execute(
                    """
                    UPDATE tier_features
                    SET enabled = $1, updated_at = NOW()
                    WHERE tier_id = $2 AND feature_key = $3
                    """,
                    update.enabled, tier_id, update.feature_key
                )
                updated_count += 1
            else:
                # Insert new
                await conn.execute(
                    """
                    INSERT INTO tier_features (tier_id, feature_key, enabled)
                    VALUES ($1, $2, $3)
                    """,
                    tier_id, update.feature_key, update.enabled
                )
                updated_count += 1

        return {
            "success": True,
            "tier_code": tier_code,
            "updated_count": updated_count,
            "message": f"Updated {updated_count} feature(s) for tier '{tier_code}'"
        }
    finally:
        await conn.close()


@router.post("/admin/tiers/{tier_code}/features/bulk")
async def bulk_set_tier_features(
    tier_code: str,
    feature_keys: List[str],
    enabled: bool = True,
    admin: str = Depends(get_current_admin)
):
    """
    Bulk enable/disable multiple features for a tier.
    Admin only.

    - **tier_code**: Tier code to update
    - **feature_keys**: List of feature keys to update
    - **enabled**: Whether to enable or disable these features
    """
    conn = await get_db_connection()
    try:
        # Get tier ID
        tier = await conn.fetchrow(
            "SELECT id FROM subscription_tiers WHERE tier_code = $1",
            tier_code
        )
        if not tier:
            raise HTTPException(status_code=404, detail=f"Tier '{tier_code}' not found")

        tier_id = tier['id']

        # Update all features
        for feature_key in feature_keys:
            # Upsert (insert or update)
            await conn.execute(
                """
                INSERT INTO tier_features (tier_id, feature_key, enabled)
                VALUES ($1, $2, $3)
                ON CONFLICT (tier_id, feature_key)
                DO UPDATE SET enabled = $3, updated_at = NOW()
                """,
                tier_id, feature_key, enabled
            )

        return {
            "success": True,
            "tier_code": tier_code,
            "feature_count": len(feature_keys),
            "enabled": enabled,
            "message": f"Bulk {'enabled' if enabled else 'disabled'} {len(feature_keys)} feature(s) for tier '{tier_code}'"
        }
    finally:
        await conn.close()
