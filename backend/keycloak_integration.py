"""
Keycloak Integration for UC-1 Pro
Provides admin token management and user operations
"""

import httpx
import os
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Keycloak Configuration
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://auth.unicorncommander.ai")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "admin-cli")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_ADMIN_USERNAME = os.getenv("KEYCLOAK_ADMIN_USER", os.getenv("KEYCLOAK_ADMIN_USERNAME", "admin"))
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "")

# Token cache
_admin_token_cache = {
    "token": None,
    "expires_at": None
}


async def get_admin_token() -> str:
    """
    Get Keycloak admin access token
    Uses cached token if still valid
    """
    # Check if cached token is still valid
    if _admin_token_cache["token"] and _admin_token_cache["expires_at"]:
        if datetime.now() < _admin_token_cache["expires_at"]:
            return _admin_token_cache["token"]

    # Request new token from master realm (admin user exists in master, not uchub)
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": KEYCLOAK_CLIENT_ID,
                    "username": KEYCLOAK_ADMIN_USERNAME,
                    "password": KEYCLOAK_ADMIN_PASSWORD
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0
            )

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 300)  # Default 5 minutes

                # Cache token with 30 second buffer before expiration
                _admin_token_cache["token"] = access_token
                _admin_token_cache["expires_at"] = datetime.now() + timedelta(seconds=expires_in - 30)

                logger.info("Successfully obtained Keycloak admin token")
                return access_token
            else:
                logger.error(f"Failed to get admin token: {response.status_code} - {response.text}")
                raise Exception(f"Failed to authenticate with Keycloak: {response.status_code}")

    except Exception as e:
        logger.error(f"Error getting admin token: {e}")
        raise


async def get_all_users() -> List[Dict[str, Any]]:
    """
    Fetch all users from Keycloak
    """
    try:
        token = await get_admin_token()

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
                headers={"Authorization": f"Bearer {token}"},
                params={"max": 1000},
                timeout=10.0
            )

            if response.status_code == 200:
                users = response.json()
                logger.info(f"Successfully fetched {len(users)} users from Keycloak")
                return users
            else:
                logger.error(f"Failed to fetch users: {response.status_code} - {response.text}")
                return []

    except Exception as e:
        logger.error(f"Error fetching users from Keycloak: {e}")
        return []


async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Fetch specific user by email from Keycloak
    """
    try:
        token = await get_admin_token()

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
                headers={"Authorization": f"Bearer {token}"},
                params={"email": email, "exact": "true"},
                timeout=10.0
            )

            if response.status_code == 200:
                users = response.json()
                if users:
                    logger.info(f"Found user: {email}")
                    return users[0]
                else:
                    logger.warning(f"No user found with email: {email}")
                    return None
            else:
                logger.error(f"Failed to fetch user {email}: {response.status_code}")
                return None

    except Exception as e:
        logger.error(f"Error fetching user by email: {e}")
        return None


async def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """
    Fetch specific user by username from Keycloak
    """
    try:
        token = await get_admin_token()

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
                headers={"Authorization": f"Bearer {token}"},
                params={"username": username, "exact": "true"},
                timeout=10.0
            )

            if response.status_code == 200:
                users = response.json()
                if users:
                    logger.info(f"Found user: {username}")
                    return users[0]
                else:
                    logger.warning(f"No user found with username: {username}")
                    return None
            else:
                logger.error(f"Failed to fetch user {username}: {response.status_code}")
                return None

    except Exception as e:
        logger.error(f"Error fetching user by username: {e}")
        return None


async def update_user_attributes(email: str, attributes: Dict[str, List[str]]) -> bool:
    """
    Update user attributes in Keycloak
    Attributes should be in format: {"key": ["value"]} (Keycloak expects arrays)
    """
    try:
        # Get user first
        user = await get_user_by_email(email)
        if not user:
            logger.error(f"User not found: {email}")
            return False

        user_id = user.get("id")
        token = await get_admin_token()

        # Get existing attributes
        existing_attrs = user.get("attributes", {})

        # Merge with new attributes
        updated_attrs = {**existing_attrs, **attributes}

        # Update user
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.put(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={"attributes": updated_attrs},
                timeout=10.0
            )

            if response.status_code == 204:  # Keycloak returns 204 No Content on success
                logger.info(f"Successfully updated attributes for user: {email}")
                return True
            else:
                logger.error(f"Failed to update user attributes: {response.status_code} - {response.text}")
                return False

    except Exception as e:
        logger.error(f"Error updating user attributes: {e}")
        return False


async def create_user(email: str, username: str, first_name: str = "", last_name: str = "",
                     attributes: Dict[str, List[str]] = None, email_verified: bool = True) -> Optional[str]:
    """
    Create a new user in Keycloak
    Returns user ID on success, None on failure
    """
    try:
        token = await get_admin_token()

        user_data = {
            "email": email,
            "username": username,
            "enabled": True,
            "emailVerified": email_verified,
            "firstName": first_name,
            "lastName": last_name,
            "attributes": attributes or {}
        }

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=user_data,
                timeout=10.0
            )

            if response.status_code == 201:
                # Extract user ID from Location header
                location = response.headers.get("Location", "")
                user_id = location.split("/")[-1] if location else None
                logger.info(f"Successfully created user: {email} (ID: {user_id})")
                return user_id
            else:
                logger.error(f"Failed to create user: {response.status_code} - {response.text}")
                return None

    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return None


async def delete_user(email: str) -> bool:
    """
    Delete a user from Keycloak
    """
    try:
        # Get user first
        user = await get_user_by_email(email)
        if not user:
            logger.error(f"User not found: {email}")
            return False

        user_id = user.get("id")
        token = await get_admin_token()

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.delete(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )

            if response.status_code == 204:
                logger.info(f"Successfully deleted user: {email}")
                return True
            else:
                logger.error(f"Failed to delete user: {response.status_code} - {response.text}")
                return False

    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return False


async def get_user_groups(email: str) -> List[str]:
    """
    Get list of groups a user belongs to
    """
    try:
        user = await get_user_by_email(email)
        if not user:
            return []

        user_id = user.get("id")
        token = await get_admin_token()

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/groups",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )

            if response.status_code == 200:
                groups = response.json()
                return [group.get("name") for group in groups]
            else:
                logger.error(f"Failed to get user groups: {response.status_code}")
                return []

    except Exception as e:
        logger.error(f"Error getting user groups: {e}")
        return []


# Tier-specific helper functions

def _get_attr_value(attrs: Dict, key: str, default: Any = None) -> Any:
    """
    Get attribute value from Keycloak attributes dict.
    Keycloak stores attributes as arrays, so extract first element.
    """
    value = attrs.get(key, [default])
    if isinstance(value, list):
        return value[0] if value else default
    return value


async def get_user_tier_info(email: str) -> Dict[str, Any]:
    """
    Get user's subscription tier and usage information.

    Returns:
        Dictionary with tier info:
        {
            "user_id": str,
            "username": str,
            "email": str,
            "subscription_tier": "trial|starter|professional|enterprise",
            "subscription_status": "active|inactive|cancelled",
            "api_calls_used": int,
            "api_calls_reset_date": "YYYY-MM-DD",
            "stripe_customer_id": str or None,
            "subscription_start_date": str or None,
            "subscription_end_date": str or None
        }
    """
    user = await get_user_by_email(email)

    if not user:
        # Return default trial tier for unknown users
        return {
            "user_id": None,
            "username": None,
            "email": email,
            "subscription_tier": "trial",
            "subscription_status": "active",
            "api_calls_used": 0,
            "api_calls_reset_date": datetime.utcnow().date().isoformat(),
            "stripe_customer_id": None,
            "subscription_start_date": None,
            "subscription_end_date": None,
        }

    # Extract attributes (Keycloak stores as arrays)
    attrs = user.get("attributes", {})

    return {
        "user_id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "subscription_tier": _get_attr_value(attrs, "subscription_tier", "trial"),
        "subscription_status": _get_attr_value(attrs, "subscription_status", "active"),
        "api_calls_used": int(_get_attr_value(attrs, "api_calls_used", "0")),
        "api_calls_reset_date": _get_attr_value(
            attrs,
            "api_calls_reset_date",
            datetime.utcnow().date().isoformat()
        ),
        "stripe_customer_id": _get_attr_value(attrs, "stripe_customer_id"),
        "subscription_start_date": _get_attr_value(attrs, "subscription_start_date"),
        "subscription_end_date": _get_attr_value(attrs, "subscription_end_date"),
    }


async def increment_usage(email: str, current_usage: int = None) -> bool:
    """
    Increment user's API usage counter.
    Handles daily reset automatically.

    Args:
        email: User's email address
        current_usage: Current usage count (if known), otherwise fetches from Keycloak

    Returns:
        True if successful, False otherwise
    """
    # Get current tier info
    tier_info = await get_user_tier_info(email)

    if not tier_info.get("user_id"):
        logger.warning(f"Cannot increment usage: user not found ({email})")
        return False

    # Get current usage and reset date
    if current_usage is None:
        current_usage = tier_info.get("api_calls_used", 0)

    reset_date = tier_info.get("api_calls_reset_date")
    today = datetime.utcnow().date().isoformat()

    # Check if we need to reset counter (new day)
    if reset_date != today:
        # New day - reset counter
        new_usage = 1
        logger.info(f"Daily usage reset for {email}")
    else:
        # Increment counter
        new_usage = current_usage + 1

    # Update attributes (Keycloak expects arrays)
    return await update_user_attributes(email, {
        "api_calls_used": [str(new_usage)],
        "api_calls_reset_date": [today],
    })


async def reset_usage(email: str) -> bool:
    """
    Reset user's API usage counter to 0.
    Useful for testing or manual resets.
    """
    today = datetime.utcnow().date().isoformat()
    return await update_user_attributes(email, {
        "api_calls_used": ["0"],
        "api_calls_reset_date": [today],
    })


async def set_subscription_tier(
    email: str,
    tier: str,
    status: str = "active"
) -> bool:
    """
    Set user's subscription tier.

    Args:
        email: User's email address
        tier: Tier name (trial, starter, professional, enterprise)
        status: Subscription status (active, inactive, cancelled)

    Returns:
        True if successful, False otherwise
    """
    valid_tiers = ["trial", "free", "starter", "professional", "enterprise"]
    if tier not in valid_tiers:
        logger.error(f"Invalid tier: {tier}. Must be one of {valid_tiers}")
        return False

    return await update_user_attributes(email, {
        "subscription_tier": [tier],
        "subscription_status": [status],
    })


async def set_user_password(user_id: str, password: str, temporary: bool = False) -> bool:
    """
    Set password for a Keycloak user.

    Args:
        user_id: Keycloak user ID
        password: New password
        temporary: If True, user must change password on first login

    Returns:
        True if successful, False otherwise
    """
    try:
        token = await get_admin_token()

        password_data = {
            "type": "password",
            "value": password,
            "temporary": temporary
        }

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.put(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/reset-password",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=password_data,
                timeout=10.0
            )

            if response.status_code == 204:
                logger.info(f"Successfully set password for user ID: {user_id}")
                return True
            else:
                logger.error(f"Failed to set password: {response.status_code} - {response.text}")
                return False

    except Exception as e:
        logger.error(f"Error setting user password: {e}")
        return False
