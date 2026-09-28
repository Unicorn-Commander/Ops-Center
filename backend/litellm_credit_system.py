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
import os
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

# ---------------------------------------------------------------------------
# COST UNIT (see CREDITS.md)
# ONE CREDIT = ONE US DOLLAR of metered provider-equivalent cost.
# amount == cost on the ledger. Do not reintroduce a second unit.
# ---------------------------------------------------------------------------

# Single named configurable margin lever. Aaron sets this; default 1.0 is
# pass-through (zero cloud margin). Do not scatter other markups.
CREDIT_MARKUP_MULTIPLIER = float(os.environ.get("CREDIT_MARKUP_MULTIPLIER", "1.0"))

# When a model is not in llm_models and has no static rate, charge this
# clearly-labelled conservative default rather than refusing the call.
# Frontier-class rates so an unknown model is never undercharged into a loss.
# Logged WARNING every time it fires.
CONSERVATIVE_DEFAULT_USD_PER_MTOK = {
    "input": 5.0,
    "output": 15.0,
    "label": "conservative_default_unknown_model",
}

# Legacy provider-prefix table (USD per 1K tokens, blended). Kept only as a
# last-resort map for ancient callers; calculate_cost no longer uses it for
# primary pricing. Prefer MODEL_RATES_USD_PER_MTOK / llm_models.
PRICING = {
    "local": 0.0,
    "groq": 0.0,
    "huggingface": 0.0,
    "together": 0.002,
    "fireworks": 0.002,
    "deepinfra": 0.003,
    "openrouter:mixtral": 0.003,
    "openrouter:claude-3.5": 0.008,
    "openrouter:gpt-4o": 0.010,
    "anthropic": 0.015,
    "openai": 0.015,
    "default": 0.01,
}

# Static per-model rates (USD per 1M tokens), input vs output.
# Sourced from provider published / OpenRouter catalog prices (2026-08).
# Runtime prefers llm_models.cost_per_1m_{input,output}_tokens when DB is up.
MODEL_RATES_USD_PER_MTOK = {
    # OpenAI
    "openai/gpt-4o": {"input": 2.50, "output": 10.00, "source": "openai"},
    "openai/gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00, "source": "openai"},
    "openai/gpt-4o-2024-11-20": {"input": 2.50, "output": 10.00, "source": "openai"},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60, "source": "openai"},
    "openai/gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60, "source": "openai"},
    "gpt-4o": {"input": 2.50, "output": 10.00, "source": "openai"},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "source": "openai"},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60, "source": "openai"},
    # Anthropic
    "anthropic/claude-3.5-sonnet": {"input": 3.00, "output": 15.00, "source": "anthropic"},
    "anthropic/claude-3.5-sonnet-20240620": {"input": 3.00, "output": 15.00, "source": "anthropic"},
    "anthropic/claude-sonnet-4": {"input": 3.00, "output": 15.00, "source": "anthropic"},
    "anthropic/claude-sonnet-4.5": {"input": 3.00, "output": 15.00, "source": "anthropic"},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00, "source": "anthropic"},
    "claude-sonnet-4-0": {"input": 3.00, "output": 15.00, "source": "anthropic"},
    # Meta / OpenRouter small + large
    "meta-llama/llama-3.2-1b-instruct": {"input": 0.005, "output": 0.010, "source": "openrouter"},
    "meta-llama/llama-3.1-8b-instruct": {"input": 0.020, "output": 0.030, "source": "openrouter"},
    "meta-llama/llama-3.3-70b-instruct": {"input": 0.130, "output": 0.380, "source": "openrouter"},
    # Google
    "google/gemini-2.0-flash-001": {"input": 0.100, "output": 0.400, "source": "openrouter"},
    "google/gemini-2.0-flash-exp:free": {"input": 0.0, "output": 0.0, "source": "openrouter-free"},
    # DeepSeek
    "deepseek/deepseek-chat-v3.1": {"input": 0.27, "output": 1.10, "source": "openrouter"},
    # Local / free catalog
    "uc/chat-default": {"input": 0.0, "output": 0.0, "source": "local"},
    "qwen/qwen3.6-flash": {"input": 0.1875, "output": 1.125, "source": "openrouter"},
}

# Back-compat alias used by older tests (blended legacy keys). Prefer MODEL_RATES.
MODEL_PRICING = {
    "llama3-8b-local": 0.0,
    "qwen-32b-local": 0.0,
    "llama3-70b-groq": 0.0,
    "mixtral-8x7b-hf": 0.0,
    "mixtral-8x22b-together": 0.002,
    "llama3-70b-deepinfra": 0.003,
    "qwen-72b-fireworks": 0.002,
    "claude-3.5-sonnet-openrouter": 0.008,
    "gpt-4o-openrouter": 0.010,
    "claude-3.5-sonnet": 0.015,
    "gpt-4o": 0.015,
}

# Legacy tier markup map. NOT applied by calculate_cost anymore.
# Margin is CREDIT_MARKUP_MULTIPLIER only (Aaron-controlled).
TIER_MARKUP = {
    "free": 0.0,
    "starter": 0.4,
    "professional": 0.6,
    "enterprise": 0.8,
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

        Supports both regular user IDs and service organization IDs.
        Service org IDs start with 'org_' (e.g., 'org_presenton_service')

        Args:
            user_id: User identifier (email, UUID, or org ID)

        Returns:
            Current credit balance as float (credits, not millicredits)
        """
        try:
            # Try cache first
            cache_key = f"credits:balance:{user_id}"
            cached = await self.redis.get(cache_key)

            if cached:
                logger.debug(f"Credit balance cache hit for {user_id}")
                return float(cached)

            # Check if this is a service organization ID
            if user_id and user_id.startswith('org_'):
                org_uuid = user_id[4:]  # Remove 'org_' prefix to get raw UUID
                async with self.db_pool.acquire() as conn:
                    result = await conn.fetchval(
                        """
                        SELECT available_credits FROM organization_credit_pools WHERE org_id = $1
                        """,
                        org_uuid
                    )
                    if result is not None:
                        # Credits are stored as integers (no millicredits conversion)
                        balance = float(result)
                        # Cache the result
                        await self.redis.setex(cache_key, self.cache_ttl, str(balance))
                        logger.info(f"Service org {user_id} balance: {balance} credits")
                        return balance
                    else:
                        logger.warning(f"Service org {user_id} not found, returning 0 balance")
                        return 0.0

            # Query database for regular users
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
        Debit credits from user or service organization account

        Supports both regular user IDs and service organization IDs.
        Service org IDs start with 'org_' (e.g., 'org_presenton_service')

        Args:
            user_id: User identifier or organization ID
            amount: Amount to debit (positive number, in credits)
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
                    # Check if this is a service organization ID
                    if user_id and user_id.startswith('org_'):
                        # Service organization billing - strip 'org_' prefix for UUID lookup
                        org_uuid = user_id[4:]  # Remove 'org_' prefix to get raw UUID
                        result = await conn.fetchrow(
                            """
                            SELECT ocp.available_credits, ocp.used_credits, o.plan_tier
                            FROM organization_credit_pools ocp
                            JOIN organizations o ON ocp.org_id = o.id
                            WHERE ocp.org_id = $1
                            FOR UPDATE OF ocp
                            """,
                            org_uuid
                        )

                        if not result:
                            raise HTTPException(status_code=404, detail=f"Service organization {user_id} not found")

                        # Credits are stored as integers (no millicredits)
                        current_balance = float(result['available_credits'])
                        tier = result['plan_tier']

                        # Check sufficient credits
                        if current_balance < amount:
                            raise HTTPException(
                                status_code=402,  # Payment Required
                                detail=f"Insufficient service credits for {user_id}. Balance: {current_balance:.2f}, Required: {amount:.2f}"
                            )

                        # Debit credits - update used_credits (available_credits is computed)
                        new_used = int(result['used_credits']) + int(amount)
                        await conn.execute(
                            """
                            UPDATE organization_credit_pools
                            SET used_credits = $1,
                                updated_at = NOW()
                            WHERE org_id = $2
                            """,
                            new_used,
                            org_uuid
                        )
                        new_balance = current_balance - amount

                        # Log service usage for analytics (optional - table may not exist).
                        # In a SAVEPOINT: a failed statement aborts the enclosing
                        # transaction, and catching the exception does not undo that,
                        # so the COMMIT below silently became a ROLLBACK and the debit
                        # above never landed (measured: every service-org debit on a
                        # schema without service_usage_log reported success, moved 0).
                        try:
                            async with conn.transaction():
                                service_name = metadata.get('service_name', user_id.replace('org_', '').replace('_service', ''))
                                await conn.execute(
                                    """
                                    INSERT INTO service_usage_log (
                                        service_org_id, service_name, endpoint,
                                        credits_used, model_used, user_id, request_metadata
                                    )
                                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                                    """,
                                    org_uuid,
                                    service_name,
                                    metadata.get('endpoint', '/api/v1/llm/chat/completions'),
                                    amount,
                                    metadata.get('model', 'unknown'),
                                    metadata.get('proxied_user_id'),  # NULL if service-initiated
                                    json.dumps(metadata)
                                )
                        except Exception as log_error:
                            logger.debug(f"Service usage log not recorded (table may not exist): {log_error}")

                        # Create placeholder transaction ID for service
                        transaction_id = f"svc_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

                        logger.info(f"✅ Service org {user_id} debited {amount} credits. New balance: {new_balance:.2f}")

                    else:
                        # Regular user billing (existing logic)
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

                        request_id = metadata.get("request_id")
                        if request_id:
                            existing = await conn.fetchrow(
                                """SELECT id FROM credit_transactions
                                   WHERE user_id = $1 AND metadata->>'request_id' = $2
                                   LIMIT 1""",
                                user_id, str(request_id),
                            )
                            if existing:
                                return current_balance, str(existing["id"])

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

            # Invalidate cache. The debit has already committed here, so a cache
            # error must not report it as failed: the caller would queue a retry
            # of a charge that landed (and service-org debits have no request_id
            # dedup). The cached balance expires on its own (cache_ttl).
            try:
                await self.redis.delete(f"credits:balance:{user_id}")
            except Exception as cache_exc:
                logger.warning(f"Credit balance cache invalidation failed for {user_id} (debit committed): {cache_exc}")

            # NEW: Send metering event to Lago (non-blocking)
            try:
                from lago_integration import record_api_call

                # Get user's org_id from metadata or database
                org_id = metadata.get('org_id')

                if not org_id:
                    # Query database to get org_id for user
                    async with self.db_pool.acquire() as conn_org:
                        org_result = await conn_org.fetchrow(
                            """
                            SELECT org_id
                            FROM organization_members
                            WHERE user_id = $1
                            LIMIT 1
                            """,
                            user_id
                        )
                        if org_result:
                            org_id = str(org_result['org_id'])

                if org_id:
                    # Build properties with cost information
                    properties = {
                        "endpoint": metadata.get('endpoint', '/api/v1/llm/chat/completions'),
                        "user_id": user_id,
                        "tokens": metadata.get('tokens_used', 0),
                        "cost": float(amount),  # Cost in credits
                    }
                    if metadata.get('model'):
                        properties["model"] = metadata.get('model')
                    if metadata.get('provider'):
                        properties["provider"] = metadata.get('provider')

                    # Send usage event to Lago using record_usage (more flexible than record_api_call)
                    from lago_integration import record_usage
                    await record_usage(
                        org_id=org_id,
                        event_code="api_call",
                        transaction_id=str(transaction_id),
                        properties=properties
                    )
                    logger.info(f"✓ Sent Lago metering event for org {org_id}: {amount} credits, {metadata.get('tokens_used', 0)} tokens, model: {metadata.get('model', 'unknown')}")
                else:
                    logger.warning(f"No org_id found for user {user_id}, skipping Lago event")

            except Exception as e:
                # Non-blocking: Don't fail credit deduction if Lago is down
                logger.warning(f"Failed to record Lago event (non-blocking): {e}")

            # ------------------------------------------------------------------
            # APPEND-ONLY HOOK (T7): low-credit email notification.
            # Fires at most once, when this debit made the balance CROSS below
            # 10% of the user's allocation (dispatcher re-checks prefs + applies
            # a 1/hour/user rate limit). Fire-and-forget: must NEVER delay or
            # break the debit path.
            # ------------------------------------------------------------------
            try:
                if user_id and not user_id.startswith('org_'):
                    from notification_dispatcher import maybe_notify_low_credit
                    asyncio.create_task(
                        maybe_notify_low_credit(
                            user_id=user_id,
                            previous_balance=float(current_balance),
                            new_balance=float(new_balance),
                            db_pool=self.db_pool,
                        )
                    )
            except Exception as notify_exc:
                logger.warning(f"Low-credit notification hook failed (non-blocking): {notify_exc}")

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

    @staticmethod
    def is_free_model(*model_ids) -> bool:
        """True if any id is an OpenRouter-style free variant (endswith ':free')."""
        for mid in model_ids:
            if mid and str(mid).endswith(":free"):
                return True
        return False

    @staticmethod
    def ledger_attribution(
        provider_used: Optional[str],
        request_model: Optional[str],
        catalog_provider: Optional[str],
        is_local: bool,
    ) -> tuple[str, str]:
        """Return provider/model labels for the existing credit-ledger path.

        Provider responses identify the served backend model, not the catalog
        provider. Preserve that historical convention for cloud calls, while
        local calls must be attributable to the local provider and requested
        catalog alias so local-serve share is measurable.
        """
        served = provider_used or "unknown"
        if is_local:
            return catalog_provider or "UC Gateway Local", request_model or served
        return served, served

    async def _lookup_model_rates(self, model: str):
        """
        Resolve input/output USD-per-1M rates for a model id.
        Order: exact llm_models row → static MODEL_RATES → basename aliases.
        Returns dict with keys input, output, source — or None if unknown.
        """
        if not model:
            return None

        candidates = [model]
        if model.startswith("openrouter/"):
            candidates.append(model[len("openrouter/"):])
        if "/" in model:
            candidates.append(model.split("/", 1)[1])

        # 1) Database catalog (authoritative when populated)
        try:
            async with self.db_pool.acquire() as conn:
                for cand in candidates:
                    row = await conn.fetchrow(
                        """
                        SELECT name,
                               cost_per_1m_input_tokens,
                               cost_per_1m_output_tokens
                          FROM llm_models
                         WHERE name = $1
                         LIMIT 1
                        """,
                        cand,
                    )
                    if row is None:
                        row = await conn.fetchrow(
                            """
                            SELECT name,
                                   cost_per_1m_input_tokens,
                                   cost_per_1m_output_tokens
                              FROM llm_models
                             WHERE lower(name) = lower($1)
                             LIMIT 1
                            """,
                            cand,
                        )
                    if row is not None:
                        inn = row["cost_per_1m_input_tokens"]
                        out = row["cost_per_1m_output_tokens"]
                        if inn is not None and out is not None:
                            return {
                                "input": float(inn),
                                "output": float(out),
                                "source": f"llm_models:{row['name']}",
                            }
        except Exception as db_err:
            logger.warning(f"Model rate DB lookup failed for {model}: {db_err}")

        # 2) Static table
        lower_map = {k.lower(): v for k, v in MODEL_RATES_USD_PER_MTOK.items()}
        for cand in candidates:
            if cand in MODEL_RATES_USD_PER_MTOK:
                rates = MODEL_RATES_USD_PER_MTOK[cand]
                return {
                    "input": float(rates["input"]),
                    "output": float(rates["output"]),
                    "source": f"static:{rates.get('source', 'MODEL_RATES')}",
                }
            if cand.lower() in lower_map:
                rates = lower_map[cand.lower()]
                return {
                    "input": float(rates["input"]),
                    "output": float(rates["output"]),
                    "source": f"static:{rates.get('source', 'MODEL_RATES')}",
                }

        return None

    async def calculate_cost(
        self,
        tokens_used: int,
        model: str,
        power_level: str = "balanced",
        user_tier: str = "vip_founder",
        is_local: bool = False,
        use_catalog_local_rates: bool = False,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        request_model: Optional[str] = None,
    ) -> float:
        """
        Calculate cost for an LLM request in credits (1 credit = $1 USD).

        Pricing is per-model, input vs output, sourced from llm_models (preferred)
        or MODEL_RATES_USD_PER_MTOK. Power-level multipliers are NOT applied —
        they previously flattened every cloud call into a ~$2.50–$3.75/Mtok band.
        Tier markup is NOT applied; the only margin lever is CREDIT_MARKUP_MULTIPLIER.

        Args:
            tokens_used: Total tokens (prompt + completion). Used when split missing.
            model: Model identifier used for rate lookup (often the provider echo).
            power_level: Kept for call-site compatibility; does not affect cost.
            user_tier: Kept for call-site compatibility; does not affect cost.
            is_local: Authoritative local/cloud signal from the resolved provider.
            use_catalog_local_rates: Price local usage through the same llm_models
                split input/output rate lookup used for cloud models.
            prompt_tokens / completion_tokens: Preferred split for asymmetric rates.
            request_model: Original client model id. Required for :free safety when
                the provider echoes the model WITHOUT the :free suffix.

        Returns:
            Cost in credits (float), rounded to 6 decimal places.
        """
        try:
            # --- Free / local short-circuits ---
            if self.is_free_model(model, request_model):
                # OpenRouter free variants cost the provider $0 at every site,
                # including post-call when the provider drops the :free suffix.
                return 0.0

            if is_local:
                if not use_catalog_local_rates:
                    return 0.0

            # Resolve rates
            rates = await self._lookup_model_rates(model or "")
            if rates is None and request_model:
                rates = await self._lookup_model_rates(request_model)

            if rates is None:
                # Explicit policy: do NOT flat-guess a provider-prefix rate.
                # Charge a clearly-labelled conservative default and warn.
                rates = {
                    "input": CONSERVATIVE_DEFAULT_USD_PER_MTOK["input"],
                    "output": CONSERVATIVE_DEFAULT_USD_PER_MTOK["output"],
                    "source": CONSERVATIVE_DEFAULT_USD_PER_MTOK["label"],
                }
                logger.warning(
                    "UNKNOWN_MODEL_PRICING model=%r request_model=%r — using "
                    "conservative_default_unknown_model ($%.2f/$%.2f per 1M in/out). "
                    "Add the model to llm_models or MODEL_RATES_USD_PER_MTOK.",
                    model,
                    request_model,
                    rates["input"],
                    rates["output"],
                )

            in_rate = float(rates["input"])
            out_rate = float(rates["output"])

            # Token split
            p_tok = int(prompt_tokens) if prompt_tokens is not None else None
            c_tok = int(completion_tokens) if completion_tokens is not None else None

            if p_tok is not None and c_tok is not None and (p_tok + c_tok) > 0:
                base_cost = (p_tok / 1_000_000.0) * in_rate + (c_tok / 1_000_000.0) * out_rate
            else:
                # No split available (common on streaming without usage chunk).
                # Conservative: price all tokens at the OUTPUT rate so we never
                # undercharge a completion-heavy call. Prefer wiring prompt/completion.
                total = max(int(tokens_used or 0), 0)
                if total == 0:
                    return 0.0
                base_cost = (total / 1_000_000.0) * out_rate
                if in_rate != out_rate:
                    logger.debug(
                        "cost_no_token_split model=%s total=%s using output_rate=%.4f "
                        "(in=%.4f) source=%s",
                        model, total, out_rate, in_rate, rates.get("source"),
                    )

            final_cost = base_cost * float(CREDIT_MARKUP_MULTIPLIER)
            return round(final_cost, 6)

        except Exception as e:
            logger.error(f"Error calculating cost: {e}", exc_info=True)
            if is_local:
                # Local pricing fails open: never substitute an unrelated cloud rate.
                return 0.0
            # Safe conservative fallback on unexpected errors
            total = max(int(tokens_used or 0), 0)
            return round(
                (total / 1_000_000.0) * CONSERVATIVE_DEFAULT_USD_PER_MTOK["output"]
                * float(CREDIT_MARKUP_MULTIPLIER),
                6,
            )


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
        """
        Get user's subscription tier

        Supports both regular user IDs and service organization IDs.
        Service org IDs start with 'org_' (e.g., 'org_presenton_service')

        Args:
            user_id: User UUID or organization ID

        Returns:
            Subscription tier (free, starter, professional, enterprise, managed, etc)
        """
        try:
            # Check if this is a service organization ID
            if user_id and user_id.startswith('org_'):
                # Strip org_ prefix to get UUID for DB lookup (id column is UUID type)
                org_uuid = user_id[4:]
                async with self.db_pool.acquire() as conn:
                    # plan_tier is present on all org schemas; subscription_tier may not exist
                    tier = await conn.fetchval(
                        """
                        SELECT plan_tier FROM organizations WHERE id::text = $1
                        """,
                        org_uuid
                    )
                    if tier:
                        logger.info(f"Service org {user_id} tier: {tier}")
                        return tier
                    else:
                        logger.warning(f"Service org {user_id} not found, defaulting to managed tier")
                        return "managed"

            # Regular user tier lookup
            async with self.db_pool.acquire() as conn:
                # First try to get tier from user's organization membership
                # organization_members.user_id stores UUIDs as varchar, users.id is UUID
                # Need to cast users.id to text for comparison
                tier = await conn.fetchval(
                    """
                    SELECT o.plan_tier
                    FROM organization_members om
                    JOIN organizations o ON o.id = om.org_id
                    JOIN users u ON u.id::text = om.user_id
                    WHERE u.email = $1
                    ORDER BY om.joined_at DESC
                    LIMIT 1
                    """,
                    user_id
                )
                if tier:
                    logger.info(f"User {user_id} tier from organization: {tier}")
                    return tier

                # Fallback to user_credits table if it exists
                try:
                    tier = await conn.fetchval(
                        """
                        SELECT tier FROM user_credits WHERE user_id = $1
                        """,
                        user_id
                    )
                    return tier or "free"
                except Exception:
                    return "free"
        except Exception as e:
            logger.error(f"Error getting user tier for {user_id}: {e}")
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

                # FIX: Convert Decimal to float for comparison
                return (float(monthly_spending) + amount) <= float(result['monthly_cap'])

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
