"""
Forgejo API Client for Ops-Center Integration

Provides async HTTP client for Forgejo Git server API.
Supports both user-token and admin-token authentication.

Author: Ops-Center AI
Created: November 8, 2025
"""

import httpx
from typing import Optional, List, Dict, Any
import os
import logging

logger = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://git.unicorncommander.ai"

class ForgejoClient:
    """Async client for Forgejo Git server API"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        admin_token: Optional[str] = None,
        timeout: int = 10
    ):
        """
        Initialize Forgejo client

        Args:
            base_url: Forgejo instance URL
            admin_token: Admin API token for elevated operations
            timeout: Request timeout in seconds
        """
        self._base_url = base_url.rstrip('/') if base_url else None
        self._admin_token = admin_token
        self.timeout = timeout

    @staticmethod
    def _lookup(key: str, default: str = "") -> str:
        """Resolve settings from platform_settings, then environment."""
        try:
            from get_credential import get_credential
            return (get_credential(key, default) or "").strip()
        except Exception as exc:
            logger.warning("Forgejo credential lookup for %s failed: %s", key, exc)
            return (os.getenv(key, default) or "").strip()

    @property
    def base_url(self) -> str:
        if self._base_url is None:
            self._base_url = (self._lookup("FORGEJO_API_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip('/')
        return self._base_url

    @property
    def admin_token(self) -> Optional[str]:
        if self._admin_token is None:
            self._admin_token = self._lookup("FORGEJO_API_TOKEN") or None
        return self._admin_token

    def _get_headers(self, user_token: Optional[str] = None) -> Dict[str, str]:
        """Get authorization headers for API requests"""
        token = user_token or self.admin_token
        if not token:
            raise RuntimeError("Forgejo API token is not configured; refusing an authenticated request")
        return {
            "Authorization": f"token {token}",
            "Content-Type": "application/json"
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        Check Forgejo instance health

        Returns:
            dict: Health status with online/offline and version info
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Try to fetch version info (public endpoint)
                response = await client.get(f"{self.base_url}/api/v1/version")

                if response.status_code == 200:
                    version_data = response.json()
                    return {
                        "online": True,
                        "version": version_data.get("version", "unknown"),
                        "status": "healthy"
                    }
                else:
                    return {
                        "online": False,
                        "status": "unreachable",
                        "error": f"HTTP {response.status_code}"
                    }
        except Exception as e:
            logger.error(f"Forgejo health check failed: {e}")
            return {
                "online": False,
                "status": "error",
                "error": str(e)
            }

    async def get_user_repos(self, user_token: str) -> List[Dict[str, Any]]:
        """
        Get repositories for authenticated user

        Args:
            user_token: User's Forgejo access token

        Returns:
            list: User's repositories
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/user/repos",
                    headers=self._get_headers(user_token)
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch user repos: {e}")
            return []

    async def get_all_orgs(self) -> List[Dict[str, Any]]:
        """
        Get all organizations (admin only)

        Returns:
            list: All organizations in Forgejo
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/orgs",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch organizations: {e}")
            return []

    async def get_org_repos(self, org_name: str) -> List[Dict[str, Any]]:
        """
        Get repositories for specific organization

        Args:
            org_name: Organization name

        Returns:
            list: Organization's repositories
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/orgs/{org_name}/repos",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch org repos for {org_name}: {e}")
            return []

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get Forgejo instance statistics (admin only)

        Returns:
            dict: Instance statistics
        """
        try:
            # Get organizations
            orgs = await self.get_all_orgs()

            # Count total repos across all orgs
            total_repos = 0
            for org in orgs:
                org_repos = await self.get_org_repos(org["username"])
                total_repos += len(org_repos)

            return {
                "total_organizations": len(orgs),
                "total_repositories": total_repos,
                "instance_url": self.base_url
            }
        except Exception as e:
            logger.error(f"Failed to fetch Forgejo stats: {e}")
            return {
                "error": str(e)
            }
