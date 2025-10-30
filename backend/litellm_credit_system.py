"""
LiteLLM Credit System - Core credit management for LLM usage

This module handles:
- Credit balance tracking and caching
- Credit debit/credit transactions
- Cost calculation based on tokens and models
- Transaction history
- Integration with PostgreSQL and Redis

Author: Backend Developer #1
Date: October 20, 2025
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import json

import asyncpg
import redis.asyncio as aioredis
from fastapi import HTTPException

logger = logging.getLogger(__name__)


# Power level configurations
POWER_LEVELS = {
    "eco": {
        "cost_multiplier": 0.1,
        "max_tokens": 2000,
        "temperature": 0.7,
        "max_cost_per_request": 0.001,
        "preferred_providers": ["local", "groq", "huggingface"],
        "quality_threshold": 0.6,
        "latency_slo": "normal"
    },
    "balanced": {
        "cost_multiplier": 0.25,
        "max_tokens": 4000,
        "temperature": 0.8,
        "max_cost_per_request": 0.01,
        "preferred_providers": ["together", "fireworks", "openrouter"],
        "quality_threshold": 0.8,
        "latency_slo": "fast"
    },
    "precision": {
        "cost_multiplier": 1.0,
        "max_tokens": 16000,
        "temperature": 0.3,
        "max_cost_per_request": 0.1,
        "preferred_providers": ["anthropic", "openai", "openrouter:premium"],
        "quality_threshold": 0.95,
        "latency_slo": "instant"
    }
}

# Cost per 1K tokens (platform markup included)
PRICING = {
    # Free tier
    "local": 0.0,
    "groq": 0.0,
    "huggingface": 0.0,

    # Paid tier (low cost)
    "together": 0.002,
    "fireworks": 0.002,
    "deepinfra": 0.003,

    # OpenRouter (multi-provider)
    "openrouter:mixtral": 0.003,
    "openrouter:claude-3.5": 0.008,
    "openrouter:gpt-4o": 0.010,

    # Premium (direct)
    "anthropic": 0.015,
    "openai": 0.015,

    # Default fallback
    "default": 0.01
}

# Model-specific pricing overrides
MODEL_PRICING = {
    # Local models
    "llama3-8b-local": 0.0,
    "qwen-32b-local": 0.0,

    # Free tier
    "llama3-70b-groq": 0.0,
    "mixtral-8x7b-hf": 0.0,

    # Paid tier
    "mixtral-8x22b-together": 0.002,
    "llama3-70b-deepinfra": 0.003,
    "qwen-72b-fireworks": 0.002,

    # OpenRouter
    "claude-3.5-sonnet-openrouter": 0.008,
    "gpt-4o-openrouter": 0.010,

    # Premium
    "claude-3.5-sonnet": 0.015,
    "gpt-4o": 0.015
}

# Tier-based markup percentages
TIER_MARKUP = {
    "free": 0.0,      # Platform absorbs cost
    "starter": 0.4,   # 40% markup
    "professional": 0.6,  # 60% markup
    "enterprise": 0.8     # 80% markup
}


class CreditSystem:
    """Core credit management system for LLM usage"""

    def __init__(self, db_pool: asyncpg.Pool, redis_client: aioredis.Redis):
        self.db_pool = db_pool
        self.redis = redis_client
        self.cache_ttl = 60  # 60 seconds cache

    async def get_user_credits(self, user_id: str) -> float:
        """
        Get user's current credit balance (cached)

        Args:
            user_id: User identifier (email or UUID)

        Returns:
            Current credit balance as float
        """
        try:
            # Try cache first
            cache_key = f"credits:balance:{user_id}"
            cached = await self.redis.get(cache_key)

            if cached:
                logger.debug(f"Credit balance cache hit for {user_id}")
                return float(cached)

            # Query database
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    SELECT credits_remaining, tier
                    FROM user_credits
                    WHERE user_id = $1
                    """,
                    user_id
                )

                if not result:
                    # AUTO-PROVISION: Create credit account for new user with trial tier
                    # Default: trial tier with 5.0 credits
                    logger.info(f"Auto-provisioning credit account for new user: {user_id}")
                    await conn.execute(
                        """
                        INSERT INTO user_credits (user_id, credits_remaining, credits_allocated, tier)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (user_id) DO NOTHING
                        """,
                        user_id, 5.0, 5.0, "trial"
                    )
                    credits = 5.0
                else:
                    credits = float(result['credits_remaining'])

                # Cache the result
                await self.redis.setex(cache_key, self.cache_ttl, str(credits))

                return credits

        except Exception as e:
            logger.error(f"Error getting user credits: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve credit balance")

    async def debit_credits(
        self,
        user_id: str,
        amount: float,
        metadata: Dict
    ) -> Tuple[float, str]:
        """
        Debit credits from user account

        Args:
            user_id: User identifier
            amount: Amount to debit (positive number)
            metadata: Transaction metadata (provider, model, tokens, etc.)

        Returns:
            Tuple of (new_balance, transaction_id)

        Raises:
            HTTPException: If insufficient credits
        """
        try:
            async with self.db_pool.acquire() as conn:
                # Start transaction
                async with conn.transaction():
                    # Lock row and check balance
                    result = await conn.fetchrow(
                        """
                        SELECT credits_remaining, monthly_cap, tier
                        FROM user_credits
                        WHERE user_id = $1
                        FOR UPDATE
                        """,
                        user_id
                    )

                    if not result:
                        raise HTTPException(status_code=404, detail="User not found")

                    current_balance = float(result['credits_remaining'])

                    # Check sufficient credits (except free tier)
                    if result['tier'] != 'free' and current_balance < amount:
                        raise HTTPException(
                            status_code=402,  # Payment Required
                            detail=f"Insufficient credits. Balance: {current_balance}, Required: {amount}"
                        )

                    # Debit credits
                    new_balance = max(0, current_balance - amount)
                    await conn.execute(
                        """
                        UPDATE user_credits
                        SET credits_remaining = $1,
                            last_reset = CASE
                                WHEN EXTRACT(EPOCH FROM (NOW() - last_reset)) > 2592000
                                THEN NOW()
                                ELSE last_reset
                            END
                        WHERE user_id = $2
                        """,
                        new_balance, user_id
                    )

                    # Record transaction
                    transaction_id = await conn.fetchval(
                        """
                        INSERT INTO credit_transactions (
                            user_id, amount, transaction_type,
                            provider, model, tokens_used, cost, metadata
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        RETURNING id
                        """,
                        user_id,
                        -amount,  # Negative for debit
                        "usage",
                        metadata.get('provider', 'unknown'),
                        metadata.get('model', 'unknown'),
                        metadata.get('tokens_used', 0),
                        metadata.get('cost', amount),
                        json.dumps(metadata)
                    )

            # Invalidate cache
            await self.redis.delete(f"credits:balance:{user_id}")

            logger.info(f"Debited {amount} credits from {user_id}. New balance: {new_balance}")
            return new_balance, str(transaction_id)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error debiting credits: {e}")
            raise HTTPException(status_code=500, detail="Failed to debit credits")

    async def credit_credits(
        self,
        user_id: str,
        amount: float,
        reason: str = "purchase"
    ) -> float:
        """
        Add credits to user account

        Args:
            user_id: User identifier
            amount: Amount to credit (positive number)
            reason: Transaction reason (purchase, refund, bonus)

        Returns:
            New credit balance
        """
        try:
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    # Update balance
                    new_balance = await conn.fetchval(
                        """
                        UPDATE user_credits
                        SET credits_remaining = credits_remaining + $1
                        WHERE user_id = $2
                        RETURNING credits_remaining
                        """,
                        amount, user_id
                    )

                    if new_balance is None:
                        # Create new entry
                        new_balance = await conn.fetchval(
                            """
                            INSERT INTO user_credits (user_id, credits_remaining, tier)
                            VALUES ($1, $2, $3)
                            RETURNING credits_remaining
                            """,
                            user_id, amount, "free"
                        )

                    # Record transaction
                    await conn.execute(
                        """
                        INSERT INTO credit_transactions (
                            user_id, amount, transaction_type, metadata
                        )
                        VALUES ($1, $2, $3, $4)
                        """,
                        user_id, amount, reason, json.dumps({"reason": reason})
                    )

            # Invalidate cache
            await self.redis.delete(f"credits:balance:{user_id}")

            logger.info(f"Credited {amount} credits to {user_id}. New balance: {new_balance}")
            return float(new_balance)

        except Exception as e:
            logger.error(f"Error crediting credits: {e}")
            raise HTTPException(status_code=500, detail="Failed to add credits")

    async def get_credit_history(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """
        Get credit transaction history

        Args:
            user_id: User identifier
            limit: Maximum number of records
            offset: Pagination offset

        Returns:
            List of transaction records
        """
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        id, amount, transaction_type, provider, model,
                        tokens_used, cost, metadata, created_at
                    FROM credit_transactions
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    user_id, limit, offset
                )

                return [
                    {
                        'id': str(row['id']),
                        'amount': float(row['amount']),
                        'type': row['transaction_type'],
                        'provider': row['provider'],
                        'model': row['model'],
                        'tokens_used': row['tokens_used'],
                        'cost': float(row['cost']) if row['cost'] else 0.0,
                        'metadata': json.loads(row['metadata']) if row['metadata'] else {},
                        'created_at': row['created_at'].isoformat()
                    }
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Error retrieving credit history: {e}")
            return []

    def calculate_cost(
        self,
        tokens_used: int,
        model: str,
        power_level: str = "balanced",
        user_tier: str = "free"
    ) -> float:
        """
        Calculate cost for LLM request

        Args:
            tokens_used: Total tokens (prompt + completion)
            model: Model identifier
            power_level: User's selected power level (eco, balanced, precision)
            user_tier: User's subscription tier

        Returns:
            Cost in credits (float)
        """
        try:
            # Get base cost from model pricing
            if model in MODEL_PRICING:
                base_cost_per_1k = MODEL_PRICING[model]
            else:
                # Extract provider from model name
                provider = self._extract_provider(model)
                base_cost_per_1k = PRICING.get(provider, PRICING["default"])

            # Calculate base cost
            base_cost = (tokens_used / 1000) * base_cost_per_1k

            # Apply power level multiplier
            power_config = POWER_LEVELS.get(power_level, POWER_LEVELS["balanced"])
            cost_with_power = base_cost * power_config["cost_multiplier"]

            # Apply tier markup
            tier_multiplier = 1 + TIER_MARKUP.get(user_tier, 0)
            final_cost = cost_with_power * tier_multiplier

            # Round to 6 decimal places
            return round(final_cost, 6)

        except Exception as e:
            logger.error(f"Error calculating cost: {e}")
            # Return safe default
            return (tokens_used / 1000) * 0.01

    def _extract_provider(self, model: str) -> str:
        """Extract provider from model name"""
        # Handle openrouter prefix
        if model.startswith("openrouter/"):
            if "claude" in model.lower():
                return "openrouter:claude-3.5"
            elif "gpt-4o" in model.lower():
                return "openrouter:gpt-4o"
            else:
                return "openrouter:mixtral"

        # Handle direct providers
        if model.startswith("anthropic/"):
            return "anthropic"
        if model.startswith("openai/"):
            return "openai"
        if model.startswith("together_ai/"):
            return "together"
        if model.startswith("fireworks_ai/"):
            return "fireworks"
        if model.startswith("deepinfra/"):
            return "deepinfra"
        if model.startswith("groq/"):
            return "groq"
        if model.startswith("huggingface/"):
            return "huggingface"
        if model.startswith("ollama/") or model.startswith("vllm/"):
            return "local"

        return "default"

    async def get_user_tier(self, user_id: str) -> str:
        """Get user's subscription tier"""
        try:
            async with self.db_pool.acquire() as conn:
                tier = await conn.fetchval(
                    """
                    SELECT tier FROM user_credits WHERE user_id = $1
                    """,
                    user_id
                )
                return tier or "free"
        except Exception as e:
            logger.error(f"Error getting user tier: {e}")
            return "free"

    async def check_monthly_cap(self, user_id: str, amount: float) -> bool:
        """Check if transaction would exceed monthly spending cap"""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    SELECT monthly_cap, last_reset
                    FROM user_credits
                    WHERE user_id = $1
                    """,
                    user_id
                )

                if not result or not result['monthly_cap']:
                    return True  # No cap set

                # Get monthly spending
                monthly_spending = await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(ABS(amount)), 0)
                    FROM credit_transactions
                    WHERE user_id = $1
                    AND transaction_type = 'usage'
                    AND created_at >= $2
                    """,
                    user_id,
                    result['last_reset'] or datetime.utcnow() - timedelta(days=30)
                )

                return (monthly_spending + amount) <= result['monthly_cap']

        except Exception as e:
            logger.error(f"Error checking monthly cap: {e}")
            return True  # Allow on error

    async def get_usage_stats(self, user_id: str, days: int = 30) -> Dict:
        """Get usage statistics for user"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            async with self.db_pool.acquire() as conn:
                stats = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_requests,
                        SUM(tokens_used) as total_tokens,
                        SUM(ABS(amount)) as total_cost,
                        AVG(ABS(amount)) as avg_cost_per_request
                    FROM credit_transactions
                    WHERE user_id = $1
                    AND transaction_type = 'usage'
                    AND created_at >= $2
                    """,
                    user_id, cutoff_date
                )

                # Provider breakdown
                provider_stats = await conn.fetch(
                    """
                    SELECT
                        provider,
                        COUNT(*) as requests,
                        SUM(tokens_used) as tokens,
                        SUM(ABS(amount)) as cost
                    FROM credit_transactions
                    WHERE user_id = $1
                    AND transaction_type = 'usage'
                    AND created_at >= $2
                    GROUP BY provider
                    ORDER BY cost DESC
                    """,
                    user_id, cutoff_date
                )

                return {
                    'total_requests': stats['total_requests'] or 0,
                    'total_tokens': stats['total_tokens'] or 0,
                    'total_cost': float(stats['total_cost'] or 0),
                    'avg_cost_per_request': float(stats['avg_cost_per_request'] or 0),
                    'providers': [
                        {
                            'provider': row['provider'],
                            'requests': row['requests'],
                            'tokens': row['tokens'],
                            'cost': float(row['cost'])
                        }
                        for row in provider_stats
                    ]
                }

        except Exception as e:
            logger.error(f"Error getting usage stats: {e}")
            return {
                'total_requests': 0,
                'total_tokens': 0,
                'total_cost': 0.0,
                'avg_cost_per_request': 0.0,
                'providers': []
            }
