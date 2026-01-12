"""
My Apps API - Returns apps filtered by user's subscription tier and organization role
Integrates with existing RBAC system (app_definitions + tier_apps)

Role-based filtering:
- Apps can specify min_org_role (member, admin, owner)
- User must have >= min_org_role in their current organization to see the app
"""

import os
import sys
import logging
from typing import List, Optional, Tuple
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
import asyncpg

# Configure logging
logger = logging.getLogger(__name__)

# Router configuration
router = APIRouter(prefix="/api/v1/my-apps", tags=["my-apps"])


# =============================================================================
# Pydantic Models
# =============================================================================

class AppResponse(BaseModel):
    """App available to user"""
    id: int
    name: str
    slug: str
    description: str
    icon_url: Optional[str]
    launch_url: str
    category: str
    feature_key: Optional[str]
    access_type: str  # 'tier_included', 'premium_purchased', 'upgrade_required'


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

async def get_current_user_tier(request: Request) -> str:
    """
    Extract user's subscription tier from session cookies.
    Uses Redis session manager (same pattern as require_admin dependency).

    Returns:
        User's subscription tier (vip_founder, byok, managed)
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
        from redis_session import RedisSessionManager

        # Get session token from cookie
        session_token = request.cookies.get("session_token")
        if not session_token:
            # Not authenticated - return trial tier (least permissive for unauthenticated)
            return 'trial'

        # Get Redis connection info
        redis_host = os.getenv("REDIS_HOST", "unicorn-lago-redis")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))

        # Initialize session manager
        sessions = RedisSessionManager(host=redis_host, port=redis_port)

        # Get session data
        if session_token not in sessions:
            # Session expired - return trial tier
            return 'trial'

        session_data = sessions[session_token]

        # Check for tier at root level (OAuth sessions) or nested under "user" key (legacy)
        tier = session_data.get("subscription_tier")
        if not tier:
            # Try legacy nested structure
            user = session_data.get("user", {})
            tier = user.get("subscription_tier") or user.get("tier")

        # If tier not set or invalid, default to trial
        # Valid tiers: vip_founder, byok, managed, founder-friend, trial, starter, professional, enterprise
        valid_tiers = ['vip_founder', 'byok', 'managed', 'founder-friend', 'trial', 'starter', 'professional', 'enterprise']
        if not tier or tier not in valid_tiers:
            tier = 'trial'

        return tier

    except Exception as e:
        # On any error, default to trial tier
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
        'enterprise': 4
    }
    return tier_levels.get(tier_name.lower(), 0)


def get_role_level(role: str) -> int:
    """Convert role name to level for comparison (higher = more permissions)"""
    role_levels = {
        'member': 1,
        'billing_admin': 2,
        'admin': 3,
        'owner': 4
    }
    return role_levels.get(role.lower(), 0)


def role_meets_minimum(user_role: str, min_role: str) -> bool:
    """Check if user's role meets or exceeds the minimum required role"""
    return get_role_level(user_role) >= get_role_level(min_role)


async def get_user_tier_features(user_tier: str, conn) -> set:
    """Get all app keys enabled for user's tier"""
    # Validate tier before database query
    valid_tiers = ['trial', 'starter', 'professional', 'enterprise', 'vip_founder', 'founder-friend', 'byok', 'managed', 'nda-autopilot', 'partnerpulse']
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


async def get_user_org_context(request: Request, conn) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Get user's current organization context including their role.

    Returns:
        Tuple of (user_id, org_id, org_role) or (None, None, None) if not in an org
    """
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')

    try:
        from redis_session import RedisSessionManager

        # Get session token from cookie
        session_token = request.cookies.get("session_token")
        if not session_token:
            return None, None, None

        # Get Redis connection info
        redis_host = os.getenv("REDIS_HOST", "unicorn-lago-redis")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))

        # Initialize session manager
        sessions = RedisSessionManager(host=redis_host, port=redis_port)

        # Get session data
        if session_token not in sessions:
            return None, None, None

        session_data = sessions[session_token]

        # Get user_id from session
        user_id = (
            session_data.get("user_id") or
            session_data.get("sub") or
            session_data.get("id") or
            session_data.get("user", {}).get("id") or
            session_data.get("user", {}).get("sub")
        )

        if not user_id:
            return None, None, None

        # Get current org_id from cookie or session
        current_org_id = request.cookies.get("current_org_id")
        if not current_org_id:
            current_org_id = session_data.get("current_org_id")

        if not current_org_id:
            # No org selected - try to get user's first org
            org_row = await conn.fetchrow(
                """SELECT org_id, role FROM organization_members
                   WHERE user_id = $1 ORDER BY joined_at LIMIT 1""",
                user_id
            )
            if org_row:
                return user_id, str(org_row['org_id']), org_row['role']
            return user_id, None, None

        # Get user's role in current org
        role_row = await conn.fetchrow(
            """SELECT role FROM organization_members
               WHERE org_id = $1 AND user_id = $2""",
            current_org_id, user_id
        )

        if role_row:
            return user_id, current_org_id, role_row['role']

        return user_id, None, None

    except Exception as e:
        logger.warning(f"Error getting user org context: {e}")
        return None, None, None


async def get_org_tier(org_id: str, conn) -> Optional[str]:
    """Get the tier_code for an organization"""
    row = await conn.fetchrow(
        """SELECT st.tier_code FROM organizations o
           JOIN subscription_tiers st ON o.tier_id = st.id
           WHERE o.id = $1""",
        org_id
    )
    return row['tier_code'] if row else None


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/authorized", response_model=List[AppResponse])
async def get_my_apps(request: Request, user_tier: str = Depends(get_current_user_tier)):
    """
    Get apps the current user is authorized to access based on their subscription tier
    and their role in their current organization.

    Returns apps where:
    - User's tier includes the app's feature_key
    - User's role in current org meets or exceeds app's min_org_role
    - User has purchased the app separately (future: check user_add_ons table)

    Role-based filtering:
    - Apps with min_org_role='member' are visible to all org members
    - Apps with min_org_role='admin' require admin or owner role
    - Apps with min_org_role='owner' require owner role
    """
    conn = await get_db_connection()
    try:
        # Get user's organization context (user_id, org_id, role)
        user_id, current_org_id, org_role = await get_user_org_context(request, conn)

        # Get org tier if user is in an org (may differ from user's session tier)
        org_tier = None
        if current_org_id:
            org_tier = await get_org_tier(current_org_id, conn)

        # COMBINE user's personal tier features with org tier features
        # User always gets their personal tier apps PLUS any apps from current org
        enabled_features = set()

        # Add features from user's personal subscription tier
        user_features = await get_user_tier_features(user_tier, conn)
        enabled_features.update(user_features)

        # Add features from current org's tier (if different)
        if org_tier and org_tier != user_tier:
            org_features = await get_user_tier_features(org_tier, conn)
            enabled_features.update(org_features)

        logger.info(f"User {user_id} - Org: {current_org_id}, Role: {org_role}, UserTier: {user_tier}, OrgTier: {org_tier}, TotalFeatures: {len(enabled_features)}")

        # Get all active apps including min_org_role
        apps_query = """
            SELECT id, name, slug, description, icon_url, launch_url,
                   category, feature_key, base_price, features,
                   COALESCE(min_org_role, 'member') as min_org_role
            FROM add_ons
            WHERE is_active = TRUE
            ORDER BY sort_order, name
        """
        app_rows = await conn.fetch(apps_query)

        # Filter apps based on tier AND role
        authorized_apps = []
        for app in app_rows:
            app_dict = dict(app)
            feature_key = app_dict.get('feature_key')
            min_role = app_dict.get('min_org_role', 'member')

            # Skip apps without launch URLs
            if not app_dict.get('launch_url'):
                continue

            # Check if user has access via tier
            access_type = None

            if feature_key and feature_key in enabled_features:
                # User's tier includes this app
                access_type = 'tier_included'
            elif app_dict['base_price'] == 0 and not feature_key:
                # Free app with no feature restriction
                access_type = 'tier_included'
            else:
                # App not included in tier - skip it
                continue

            # Check role-based access (only if user is in an org)
            # If app requires admin+ role, user must have that role in their org
            if min_role != 'member':
                if not org_role:
                    # User has no org role - skip apps requiring elevated roles
                    logger.debug(f"Skipping {app_dict['name']} - requires {min_role}, user has no org role")
                    continue
                if not role_meets_minimum(org_role, min_role):
                    # User's role is insufficient
                    logger.debug(f"Skipping {app_dict['name']} - requires {min_role}, user has {org_role}")
                    continue

            authorized_apps.append({
                'id': app_dict['id'],
                'name': app_dict['name'],
                'slug': app_dict['slug'],
                'description': app_dict['description'] or '',
                'icon_url': app_dict['icon_url'],
                'launch_url': app_dict['launch_url'],
                'category': app_dict['category'] or 'general',
                'feature_key': feature_key,
                'access_type': access_type,
                'features': app_dict.get('features') or {}
            })

        return authorized_apps

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


@router.get("/marketplace", response_model=List[AppResponse])
async def get_marketplace_apps(user_tier: str = Depends(get_current_user_tier)):
    """
    Get apps available for purchase (not included in user's current tier).

    Returns:
    - Premium apps user can purchase
    - Apps requiring tier upgrade
    """
    conn = await get_db_connection()
    try:
        # User's tier is now extracted from session via dependency injection

        # Get enabled features for user's tier
        enabled_features = await get_user_tier_features(user_tier, conn)

        # Get all active apps
        apps_query = """
            SELECT id, name, slug, description, icon_url, launch_url,
                   category, feature_key, base_price, billing_type
            FROM add_ons
            WHERE is_active = TRUE
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
