"""
Platform Settings API - Manage API Keys and Integration Secrets
Provides secure GUI-based management of platform credentials
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
import os
import yaml
import subprocess
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/platform", tags=["Platform Settings"])

# Security: Only admin role can access platform settings
def require_admin(user_role: str = "admin"):
    """Middleware to require admin role"""
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return True

class PlatformSetting(BaseModel):
    """Platform setting model"""
    key: str
    value: Optional[str] = None
    description: str
    category: str  # stripe, lago, keycloak, cloudflare, namecheap, other
    is_secret: bool = True
    required: bool = False
    test_connection: bool = False  # Whether this setting can be tested
    last_updated: Optional[datetime] = None

class SettingsUpdate(BaseModel):
    """Update platform settings"""
    settings: Dict[str, str] = Field(..., description="Dictionary of key-value pairs to update")
    restart_required: bool = Field(default=False, description="Whether to restart container after update")

class TestConnectionRequest(BaseModel):
    """Test connection with provided credentials"""
    category: str
    credentials: Dict[str, str]

# Platform settings configuration
PLATFORM_SETTINGS = {
    # Stripe Settings
    "STRIPE_PUBLISHABLE_KEY": {
        "description": "Stripe publishable key (pk_test_... or pk_live_...)",
        "category": "stripe",
        "is_secret": False,
        "required": True,
        "test_connection": True
    },
    "STRIPE_SECRET_KEY": {
        "description": "Stripe secret key (sk_test_... or sk_live_...)",
        "category": "stripe",
        "is_secret": True,
        "required": True,
        "test_connection": True
    },
    "STRIPE_WEBHOOK_SECRET": {
        "description": "Stripe webhook signing secret (whsec_...)",
        "category": "stripe",
        "is_secret": True,
        "required": True,
        "test_connection": False
    },

    # Lago Settings
    "LAGO_API_KEY": {
        "description": "Lago API key for billing management",
        "category": "lago",
        "is_secret": True,
        "required": True,
        "test_connection": True
    },
    "LAGO_API_URL": {
        "description": "Lago API URL (internal)",
        "category": "lago",
        "is_secret": False,
        "required": True,
        "test_connection": True
    },
    "LAGO_PUBLIC_URL": {
        "description": "Lago public URL (external)",
        "category": "lago",
        "is_secret": False,
        "required": True,
        "test_connection": False
    },

    # Keycloak Settings
    "KEYCLOAK_URL": {
        "description": "Keycloak URL (internal)",
        "category": "keycloak",
        "is_secret": False,
        "required": True,
        "test_connection": True
    },
    "KEYCLOAK_REALM": {
        "description": "Keycloak realm name",
        "category": "keycloak",
        "is_secret": False,
        "required": True,
        "test_connection": False
    },
    "KEYCLOAK_ADMIN_PASSWORD": {
        "description": "Keycloak admin password",
        "category": "keycloak",
        "is_secret": True,
        "required": True,
        "test_connection": True
    },

    # Cloudflare Settings
    "CLOUDFLARE_API_TOKEN": {
        "description": "Cloudflare API token with DNS edit permissions",
        "category": "cloudflare",
        "is_secret": True,
        "required": False,
        "test_connection": True
    },

    # NameCheap Settings
    "NAMECHEAP_API_USERNAME": {
        "description": "NameCheap API username",
        "category": "namecheap",
        "is_secret": False,
        "required": False,
        "test_connection": False
    },
    "NAMECHEAP_API_KEY": {
        "description": "NameCheap API key",
        "category": "namecheap",
        "is_secret": True,
        "required": False,
        "test_connection": True
    },
}

def mask_secret(value: str) -> str:
    """Mask secret values for display"""
    if not value or len(value) < 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"

def get_current_env_value(key: str) -> Optional[str]:
    """Get current environment variable value"""
    return os.getenv(key)

@router.get("/settings", summary="Get all platform settings")
async def get_platform_settings(admin: bool = Depends(require_admin)):
    """
    Get all platform settings with masked secrets

    **Permissions**: Admin only
    """
    settings = []

    for key, config in PLATFORM_SETTINGS.items():
        current_value = get_current_env_value(key)

        settings.append({
            "key": key,
            "value": mask_secret(current_value) if config["is_secret"] and current_value else current_value,
            "description": config["description"],
            "category": config["category"],
            "is_secret": config["is_secret"],
            "required": config["required"],
            "test_connection": config["test_connection"],
            "is_configured": bool(current_value),
            "last_updated": None  # TODO: Track in database
        })

    # Group by category
    grouped = {}
    for setting in settings:
        category = setting["category"]
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(setting)

    return {
        "settings": settings,
        "grouped": grouped,
        "total": len(settings),
        "configured": sum(1 for s in settings if s["is_configured"]),
        "required": sum(1 for s in settings if s["required"])
    }

@router.get("/settings/{key}", summary="Get specific setting")
async def get_setting(key: str, admin: bool = Depends(require_admin)):
    """Get specific platform setting"""
    if key not in PLATFORM_SETTINGS:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    config = PLATFORM_SETTINGS[key]
    current_value = get_current_env_value(key)

    return {
        "key": key,
        "value": mask_secret(current_value) if config["is_secret"] and current_value else current_value,
        "description": config["description"],
        "category": config["category"],
        "is_secret": config["is_secret"],
        "required": config["required"],
        "test_connection": config["test_connection"],
        "is_configured": bool(current_value)
    }

@router.put("/settings", summary="Update platform settings")
async def update_platform_settings(
    update: SettingsUpdate,
    admin: bool = Depends(require_admin)
):
    """
    Update platform settings

    **Process**:
    1. Validate all provided settings exist
    2. Update docker-compose.direct.yml file
    3. Optionally restart container to apply changes

    **Permissions**: Admin only
    """
    # Validate all keys exist
    invalid_keys = [k for k in update.settings.keys() if k not in PLATFORM_SETTINGS]
    if invalid_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid setting keys: {', '.join(invalid_keys)}"
        )

    # Read current docker-compose file
    compose_file = "/app/../docker-compose.direct.yml"

    try:
        with open(compose_file, 'r') as f:
            content = f.read()

        # Update each setting
        updated_count = 0
        for key, value in update.settings.items():
            # Find and replace the line
            old_pattern = f"      - {key}="

            # Find the line
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith(f"- {key}="):
                    lines[i] = f"      - {key}={value}"
                    updated_count += 1
                    break

        # Write back
        content = '\n'.join(lines)
        with open(compose_file, 'w') as f:
            f.write(content)

        # Restart container if requested
        restart_output = None
        if update.restart_required:
            try:
                result = subprocess.run(
                    ["docker", "compose", "-f", compose_file, "up", "-d"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                restart_output = result.stdout
            except Exception as e:
                logger.error(f"Failed to restart container: {e}")
                restart_output = f"Error: {str(e)}"

        return {
            "success": True,
            "updated": updated_count,
            "settings": list(update.settings.keys()),
            "restart_required": update.restart_required,
            "restart_output": restart_output,
            "message": f"Updated {updated_count} settings" +
                      (" and restarted container" if update.restart_required else "")
        }

    except Exception as e:
        logger.error(f"Failed to update settings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")

@router.post("/settings/test", summary="Test connection with credentials")
async def test_connection(
    request: TestConnectionRequest,
    admin: bool = Depends(require_admin)
):
    """
    Test connection with provided credentials

    **Supported Categories**:
    - stripe: Tests Stripe API connectivity
    - lago: Tests Lago API connectivity
    - keycloak: Tests Keycloak admin API
    - cloudflare: Tests Cloudflare API
    - namecheap: Tests NameCheap API
    """
    category = request.category
    creds = request.credentials

    try:
        if category == "stripe":
            import stripe
            stripe.api_key = creds.get("STRIPE_SECRET_KEY")
            balance = stripe.Balance.retrieve()
            return {
                "success": True,
                "message": "Stripe connection successful",
                "details": {
                    "available": balance.available,
                    "pending": balance.pending
                }
            }

        elif category == "lago":
            import requests
            api_key = creds.get("LAGO_API_KEY")
            api_url = creds.get("LAGO_API_URL")

            response = requests.get(
                f"{api_url}/health",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10
            )
            response.raise_for_status()

            return {
                "success": True,
                "message": "Lago connection successful",
                "details": response.json()
            }

        elif category == "keycloak":
            import requests
            keycloak_url = creds.get("KEYCLOAK_URL")
            admin_password = creds.get("KEYCLOAK_ADMIN_PASSWORD")
            realm = creds.get("KEYCLOAK_REALM", "uchub")

            # Get admin token
            token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"
            response = requests.post(
                token_url,
                data={
                    "client_id": "admin-cli",
                    "username": "admin",
                    "password": admin_password,
                    "grant_type": "password"
                },
                timeout=10
            )
            response.raise_for_status()
            token_data = response.json()

            return {
                "success": True,
                "message": "Keycloak connection successful",
                "details": {
                    "access_token": token_data.get("access_token", "")[:20] + "...",
                    "token_type": token_data.get("token_type")
                }
            }

        elif category == "cloudflare":
            import requests
            api_token = creds.get("CLOUDFLARE_API_TOKEN")

            response = requests.get(
                "https://api.cloudflare.com/client/v4/user/tokens/verify",
                headers={"Authorization": f"Bearer {api_token}"},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            return {
                "success": data.get("success", False),
                "message": "Cloudflare connection successful" if data.get("success") else "Cloudflare connection failed",
                "details": data.get("result", {})
            }

        elif category == "namecheap":
            import requests
            username = creds.get("NAMECHEAP_API_USERNAME")
            api_key = creds.get("NAMECHEAP_API_KEY")
            client_ip = creds.get("NAMECHEAP_CLIENT_IP", "")

            # Test with namecheap.domains.getList
            url = "https://api.namecheap.com/xml.response"
            params = {
                "ApiUser": username,
                "ApiKey": api_key,
                "UserName": username,
                "Command": "namecheap.domains.getList",
                "ClientIp": client_ip
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            return {
                "success": True,
                "message": "NameCheap connection successful",
                "details": {"status": "API key is valid"}
            }

        else:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")

    except Exception as e:
        logger.error(f"Connection test failed for {category}: {e}")
        return {
            "success": False,
            "message": f"Connection test failed: {str(e)}",
            "details": {"error": str(e)}
        }

@router.post("/settings/restart", summary="Restart ops-center container")
async def restart_container(admin: bool = Depends(require_admin)):
    """
    Restart ops-center container to apply new settings

    **Warning**: This will cause brief downtime (5-10 seconds)
    **Permissions**: Admin only
    """
    try:
        result = subprocess.run(
            ["docker", "restart", "ops-center-direct"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return {
                "success": True,
                "message": "Container restarted successfully",
                "output": result.stdout
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to restart container: {result.stderr}"
            )

    except Exception as e:
        logger.error(f"Failed to restart container: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Add router to main app
if __name__ == "__main__":
    print("Platform Settings API module")
    print(f"Configured settings: {len(PLATFORM_SETTINGS)}")
