"""
Epic 1.8: Credit & Usage Metering System
Module: openrouter_automation.py

Purpose: OpenRouter BYOK (Bring Your Own Key) account management with
         automatic free model detection and platform markup calculation.

Author: Backend Team Lead
Date: October 23, 2025
"""

import asyncpg
import httpx
import os
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from decimal import Decimal
from cryptography.fernet import Fernet
import base64
from audit_logger import audit_logger

# Logging setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class OpenRouterError(Exception):
    """Base exception for OpenRouter operations"""
    pass


class OpenRouterManager:
    """
    Manages OpenRouter BYOK accounts with encrypted key storage,
    free model detection, and cost calculation with platform markup.

    Features:
    - Secure key encryption using Fernet
    - Automatic free model detection (40+ models with :free suffix)
    - Platform markup calculation (0% for free, 5-10% for paid)
    - Free credit sync from OpenRouter API
    - Request routing with cost tracking
    """

    # Free tier model patterns (OpenRouter models with :free suffix)
    FREE_MODEL_PATTERNS = [
        "free",  # Any model with :free suffix
        "llama",  # Many Llama models are free
        "mistral-7b",  # Mistral 7B variants
        "mythomax",
        "toppy",
        "cinematika"
    ]

    # Markup rates by model tier
    MARKUP_RATES = {
        "free": Decimal("0.00"),      # 0% markup on free models
        "budget": Decimal("0.05"),    # 5% markup on budget models
        "standard": Decimal("0.10"),  # 10% markup on standard models
        "premium": Decimal("0.15")    # 15% markup on premium models
    }

    def __init__(self):
        self.db_pool: Optional[asyncpg.Pool] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self._encryption_key = self._get_or_create_encryption_key()
        self.fernet = Fernet(self._encryption_key)

    def _get_or_create_encryption_key(self) -> bytes:
        """Get or create Fernet encryption key"""
        key_path = "/app/data/openrouter_encryption.key"

        # Try to load existing key
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                return f.read()

        # Generate new key
        key = Fernet.generate_key()

        # Save to file
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        with open(key_path, "wb") as f:
            f.write(key)

        logger.info("Generated new OpenRouter encryption key")
        return key

    async def initialize(self):
        """Initialize database connection pool and HTTP client"""
        if not self.db_pool:
            try:
                self.db_pool = await asyncpg.create_pool(
                    host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
                    port=int(os.getenv("POSTGRES_PORT", 5432)),
                    user=os.getenv("POSTGRES_USER", "unicorn"),
                    password=os.getenv("POSTGRES_PASSWORD", "unicorn"),
                    database=os.getenv("POSTGRES_DB", "unicorn_db"),
                    min_size=5,
                    max_size=20
                )
                logger.info("OpenRouterManager database pool initialized")
            except Exception as e:
                logger.error(f"Failed to initialize database pool: {e}")
                raise

        if not self.http_client:
            self.http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={"HTTP-Referer": "https://unicorncommander.ai"}
            )

    async def close(self):
        """Close database connection pool and HTTP client"""
        if self.db_pool:
            await self.db_pool.close()
            self.db_pool = None

        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None

        logger.info("OpenRouterManager closed")

    def encrypt_key(self, api_key: str) -> str:
        """Encrypt OpenRouter API key"""
        return self.fernet.encrypt(api_key.encode()).decode()

    def decrypt_key(self, encrypted_key: str) -> str:
        """Decrypt OpenRouter API key"""
        return self.fernet.decrypt(encrypted_key.encode()).decode()

    async def create_account(
        self,
        user_id: str,
        api_key: str,
        user_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create OpenRouter BYOK account for user.

        Args:
            user_id: Keycloak user ID
            api_key: User's OpenRouter API key
            user_email: User's email (optional)

        Returns:
            Account information
        """
        if not self.db_pool:
            await self.initialize()

        # Encrypt API key
        encrypted_key = self.encrypt_key(api_key)

        # Verify API key is valid
        try:
            account_info = await self._verify_api_key(api_key)
        except Exception as e:
            raise OpenRouterError(f"Invalid OpenRouter API key: {e}")

        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                # Create or update account
                await conn.execute(
                    """
                    INSERT INTO openrouter_accounts (
                        user_id, openrouter_key, openrouter_email,
                        account_id, free_credits_remaining, is_active
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (user_id) DO UPDATE
                    SET openrouter_key = EXCLUDED.openrouter_key,
                        openrouter_email = EXCLUDED.openrouter_email,
                        account_id = EXCLUDED.account_id,
                        is_active = EXCLUDED.is_active,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    user_id, encrypted_key, user_email or account_info.get("email"),
                    account_info.get("id"), Decimal("0.00"), True
                )

                # Audit log
                await audit_logger.log(
                    action="openrouter.account_create",
                    user_id=user_id,
                    resource_type="openrouter_account",
                    resource_id=user_id,
                    details={
                        "email": user_email or account_info.get("email"),
                        "account_id": account_info.get("id")
                    },
                    status="success"
                )

        # Sync free credits
        await self.sync_free_credits(user_id)

        return await self.get_account(user_id)

    async def get_account(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get OpenRouter account for user.

        Args:
            user_id: Keycloak user ID

        Returns:
            Account information (with key redacted) or None
        """
        if not self.db_pool:
            await self.initialize()

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id, openrouter_email, account_id,
                       free_credits_remaining, is_active,
                       last_synced, created_at, updated_at
                FROM openrouter_accounts
                WHERE user_id = $1
                """,
                user_id
            )

            if not row:
                return None

            return {
                "user_id": row["user_id"],
                "email": row["openrouter_email"],
                "account_id": row["account_id"],
                "free_credits_remaining": row["free_credits_remaining"],
                "is_active": row["is_active"],
                "last_synced": row["last_synced"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }

    async def sync_free_credits(self, user_id: str) -> Decimal:
        """
        Sync free credits from OpenRouter API.

        Args:
            user_id: Keycloak user ID

        Returns:
            Updated free credits balance
        """
        if not self.db_pool:
            await self.initialize()

        # Get API key
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT openrouter_key FROM openrouter_accounts WHERE user_id = $1",
                user_id
            )

        if not row:
            raise OpenRouterError(f"No OpenRouter account for user {user_id}")

        api_key = self.decrypt_key(row["openrouter_key"])

        # Query OpenRouter API for credit balance
        try:
            credits_info = await self._get_credits_balance(api_key)
            free_credits = Decimal(str(credits_info.get("free_credits", 0)))
        except Exception as e:
            logger.error(f"Failed to sync free credits for {user_id}: {e}")
            return Decimal("0.00")

        # Update database
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE openrouter_accounts
                SET free_credits_remaining = $1,
                    last_synced = CURRENT_TIMESTAMP
                WHERE user_id = $2
                """,
                free_credits, user_id
            )

        logger.info(f"Synced {free_credits} free credits for user {user_id}")
        return free_credits

    async def route_request(
        self,
        user_id: str,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Route LLM request through OpenRouter with user's BYOK key.

        Args:
            user_id: Keycloak user ID
            model: Model name
            messages: Chat messages
            **kwargs: Additional OpenRouter parameters

        Returns:
            OpenRouter API response
        """
        if not self.db_pool:
            await self.initialize()

        # Get API key
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT openrouter_key, is_active
                FROM openrouter_accounts
                WHERE user_id = $1
                """,
                user_id
            )

        if not row:
            raise OpenRouterError(f"No OpenRouter account for user {user_id}")

        if not row["is_active"]:
            raise OpenRouterError(f"OpenRouter account inactive for user {user_id}")

        api_key = self.decrypt_key(row["openrouter_key"])

        # Make request to OpenRouter
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://unicorncommander.ai",
            "X-Title": "UC-Cloud Ops Center"
        }

        payload = {
            "model": model,
            "messages": messages,
            **kwargs
        }

        try:
            response = await self.http_client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"OpenRouter request failed: {e}")
            raise OpenRouterError(f"OpenRouter API error: {e}")

    def detect_free_model(self, model: str) -> bool:
        """
        Detect if a model is on the free tier.

        Args:
            model: Model name (e.g., "meta-llama/llama-3.1-8b-instruct:free")

        Returns:
            True if model is free tier
        """
        model_lower = model.lower()

        # Check for :free suffix
        if ":free" in model_lower:
            return True

        # Check for free model patterns
        for pattern in self.FREE_MODEL_PATTERNS:
            if pattern in model_lower:
                return True

        return False

    def calculate_markup(
        self,
        model: str,
        provider_cost: Decimal
    ) -> Tuple[Decimal, Decimal]:
        """
        Calculate platform markup for a model.

        Args:
            model: Model name
            provider_cost: Cost from OpenRouter provider

        Returns:
            (markup_amount, total_cost)
        """
        # Free models have no markup
        if self.detect_free_model(model):
            return (Decimal("0.00"), Decimal("0.00"))

        # Determine markup tier
        if provider_cost == 0:
            tier = "free"
        elif provider_cost < Decimal("0.001"):
            tier = "budget"
        elif provider_cost < Decimal("0.01"):
            tier = "standard"
        else:
            tier = "premium"

        markup_rate = self.MARKUP_RATES[tier]
        markup_amount = provider_cost * markup_rate
        total_cost = provider_cost + markup_amount

        return (markup_amount, total_cost)

    async def delete_account(self, user_id: str):
        """
        Delete OpenRouter account for user.

        Args:
            user_id: Keycloak user ID
        """
        if not self.db_pool:
            await self.initialize()

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM openrouter_accounts WHERE user_id = $1",
                user_id
            )

        await audit_logger.log(
            action="openrouter.account_delete",
            user_id=user_id,
            resource_type="openrouter_account",
            resource_id=user_id,
            status="success"
        )

        logger.info(f"Deleted OpenRouter account for user {user_id}")

    async def _verify_api_key(self, api_key: str) -> Dict[str, Any]:
        """Verify OpenRouter API key and get account info"""
        if not self.http_client:
            await self.initialize()

        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        try:
            response = await self.http_client.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers=headers
            )
            response.raise_for_status()
            return response.json().get("data", {})
        except httpx.HTTPError as e:
            raise OpenRouterError(f"API key verification failed: {e}")

    async def _get_credits_balance(self, api_key: str) -> Dict[str, Any]:
        """Get credit balance from OpenRouter API"""
        if not self.http_client:
            await self.initialize()

        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        try:
            response = await self.http_client.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers=headers
            )
            response.raise_for_status()
            data = response.json().get("data", {})

            # OpenRouter returns credits in "usage" field
            return {
                "free_credits": data.get("limit", 0),
                "used_credits": data.get("usage", 0)
            }
        except httpx.HTTPError as e:
            logger.error(f"Failed to get credits balance: {e}")
            return {"free_credits": 0, "used_credits": 0}


# Global instance
openrouter_manager = OpenRouterManager()
