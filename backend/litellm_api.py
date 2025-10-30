"""
LiteLLM API - OpenAI-compatible chat completions with credit system

This module provides:
- OpenAI-compatible /v1/chat/completions endpoint
- Credit management endpoints
- Model listing
- Usage statistics
- Stripe payment integration for credit purchases

Author: Backend Developer #1
Date: October 20, 2025
"""

import logging
import os
from typing import Dict, List, Optional
from datetime import datetime
import json
import httpx

from fastapi import APIRouter, HTTPException, Header, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import stripe

from litellm_credit_system import CreditSystem, POWER_LEVELS
from byok_manager import BYOKManager
from usage_metering import usage_meter
from cryptography.fernet import Fernet

# Import universal credential helper
from get_credential import get_credential

logger = logging.getLogger(__name__)

# Initialize Stripe - read credentials from database first, then environment
stripe.api_key = get_credential('STRIPE_SECRET_KEY')

# Router
router = APIRouter(prefix="/api/v1/llm", tags=["LLM"])

# LiteLLM proxy URL
LITELLM_PROXY_URL = os.getenv('LITELLM_PROXY_URL', 'http://unicorn-litellm-wilmer:4000')

# BYOK encryption key (used for both user and system keys)
BYOK_ENCRYPTION_KEY = os.getenv('BYOK_ENCRYPTION_KEY')


# ============================================================================
# Provider Configuration
# ============================================================================

# Provider configurations for BYOK routing
PROVIDER_CONFIGS = {
    'openai': {
        'base_url': 'https://api.openai.com/v1',
        'model_prefixes': ['openai/', 'gpt-', 'o1-', 'o3-'],
        'default_headers': {}
    },
    'anthropic': {
        'base_url': 'https://api.anthropic.com/v1',
        'model_prefixes': ['anthropic/', 'claude-'],
        'default_headers': {
            'anthropic-version': '2023-06-01'
        }
    },
    'openrouter': {
        'base_url': 'https://openrouter.ai/api/v1',
        'model_prefixes': [],  # Accepts all models
        'default_headers': {
            'HTTP-Referer': 'https://unicorncommander.ai',
            'X-Title': 'UC-1 Pro Ops Center'
        }
    },
    'google': {
        'base_url': 'https://generativelanguage.googleapis.com/v1beta',
        'model_prefixes': ['google/', 'gemini-'],
        'default_headers': {}
    }
}


def detect_provider_from_model(model_name: str) -> str:
    """
    Detect provider from model name

    Args:
        model_name: Model identifier (e.g., "openai/gpt-4", "claude-3-opus")

    Returns:
        Provider name (openai, anthropic, openrouter, google)
    """
    if not model_name:
        return 'openrouter'  # Default to OpenRouter

    model_lower = model_name.lower()

    # Check each provider's prefixes
    for provider, config in PROVIDER_CONFIGS.items():
        for prefix in config['model_prefixes']:
            if model_lower.startswith(prefix.lower()):
                return provider

    # Default to OpenRouter (handles all models)
    return 'openrouter'


# ============================================================================
# Session-Based Authentication for Admin Endpoints
# ============================================================================

async def get_current_user_from_session(request: Request) -> Dict:
    """
    Get current user from session cookie (used by admin endpoints)

    This uses the same session-based authentication as other admin endpoints
    in ops-center (user_management_api, subscription_api, etc.)

    Returns:
        User dict with email, username, role, etc.

    Raises:
        HTTPException 401 if not authenticated
    """
    session_token = request.cookies.get("session_token")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated - no session token")

    # Get sessions from app state (shared with main server.py)
    sessions = getattr(request.app.state, "sessions", {})
    session_data = sessions.get(session_token)

    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session - please login again")

    user = session_data.get("user", {})
    if not user:
        raise HTTPException(status_code=401, detail="User not found in session")

    return user


async def require_admin_from_session(request: Request) -> Dict:
    """
    Require admin role from session (used by admin endpoints)

    Returns:
        User dict if admin

    Raises:
        HTTPException 401 if not authenticated
        HTTPException 403 if not admin
    """
    user = await get_current_user_from_session(request)

    # Check if user is admin
    user_role = user.get("role", "viewer")
    if user_role != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Admin access required (current role: {user_role})"
        )

    return user


# ============================================================================
# Request/Response Models
# ============================================================================

class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role (system, user, assistant)")
    content: str = Field(..., description="Message content")


class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="Chat messages")
    model: Optional[str] = Field(None, description="Model override (optional)")
    max_tokens: Optional[int] = Field(None, description="Max tokens to generate")
    temperature: Optional[float] = Field(None, description="Sampling temperature")
    stream: bool = Field(False, description="Stream response")
    task_type: Optional[str] = Field(None, description="Task type (code, chat, rag, creative)")
    privacy_required: bool = Field(False, description="Require local models")
    power_level: str = Field("balanced", description="Power level (eco, balanced, precision)")


class CreditPurchaseRequest(BaseModel):
    amount: float = Field(..., description="Credits to purchase (10, 50, 100)")
    stripe_token: str = Field(..., description="Stripe payment token")


class CreditResponse(BaseModel):
    user_id: str
    credits_remaining: float
    tier: str
    monthly_cap: Optional[float]


class UsageStats(BaseModel):
    total_requests: int
    total_tokens: int
    total_cost: float
    avg_cost_per_request: float
    providers: List[Dict]


class AddBYOKKeyRequest(BaseModel):
    """Request model for adding/updating a BYOK key"""
    provider: str = Field(..., description="Provider name (openrouter, openai, anthropic, google)")
    api_key: str = Field(..., description="API key from provider", min_length=10)
    metadata: Optional[Dict] = Field(None, description="Optional metadata")


class ToggleBYOKRequest(BaseModel):
    """Request model for toggling BYOK key status"""
    enabled: bool = Field(..., description="Enable or disable key")


# ============================================================================
# System Key Manager (Admin Provider Keys)
# ============================================================================

class SystemKeyManager:
    """Manages system-level provider API keys for metering users"""

    def __init__(self, db_pool, encryption_key):
        """
        Initialize System Key Manager

        Args:
            db_pool: PostgreSQL connection pool
            encryption_key: Fernet encryption key
        """
        self.pool = db_pool
        if not encryption_key:
            raise ValueError("BYOK_ENCRYPTION_KEY environment variable required")
        self.cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)

    async def set_system_key(self, provider_id: str, api_key: str, source: str = 'database'):
        """
        Encrypt and store system API key

        Args:
            provider_id: Provider UUID
            api_key: Plain text API key
            source: 'database' or 'environment'
        """
        try:
            encrypted = self.cipher.encrypt(api_key.encode()).decode()
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE llm_providers
                    SET api_key_encrypted = $1,
                        api_key_source = $2,
                        api_key_updated_at = NOW()
                    WHERE id = $3
                """, encrypted, source, provider_id)
                logger.info(f"Updated system key for provider {provider_id}")
        except Exception as e:
            logger.error(f"Failed to set system key: {e}")
            raise HTTPException(status_code=500, detail="Failed to store system key")

    async def get_system_key(self, provider_id: str) -> Optional[str]:
        """
        Get decrypted system API key (database > environment)

        Args:
            provider_id: Provider UUID

        Returns:
            Decrypted API key or None
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT api_key_encrypted, api_key_source, name
                    FROM llm_providers WHERE id = $1
                """, provider_id)

                if not row:
                    return None

                # Try database key first
                if row['api_key_encrypted']:
                    try:
                        return self.cipher.decrypt(row['api_key_encrypted'].encode()).decode()
                    except Exception as e:
                        logger.error(f"Failed to decrypt system key: {e}")

                # Fallback to environment variable
                env_var = f"{row['name'].upper().replace('-', '_')}_API_KEY"
                return os.getenv(env_var)

        except Exception as e:
            logger.error(f"Failed to get system key: {e}")
            return None

    async def delete_system_key(self, provider_id: str):
        """
        Delete system API key (falls back to environment)

        Args:
            provider_id: Provider UUID
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE llm_providers
                    SET api_key_encrypted = NULL,
                        api_key_source = 'environment',
                        api_key_updated_at = NOW()
                    WHERE id = $1
                """, provider_id)
                logger.info(f"Deleted system key for provider {provider_id}")
        except Exception as e:
            logger.error(f"Failed to delete system key: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete system key")

    async def get_all_providers_with_keys(self):
        """
        Get all providers with masked keys

        Returns:
            List of provider dicts with key status
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, name, type as provider_type, api_key_encrypted,
                           api_key_source, api_key_last_tested, api_key_test_status
                    FROM llm_providers
                    WHERE enabled = TRUE
                    ORDER BY name
                """)

                result = []
                for row in rows:
                    has_db_key = bool(row['api_key_encrypted'])
                    env_var = f"{row['name'].upper().replace('-', '_')}_API_KEY"
                    has_env_key = bool(os.getenv(env_var))

                    # Determine key_source for frontend
                    if has_db_key:
                        key_source = 'database'
                    elif has_env_key:
                        key_source = 'environment'
                    else:
                        key_source = 'not_set'

                    result.append({
                        'id': str(row['id']),
                        'name': row['name'],
                        'provider_type': row['provider_type'],
                        'has_db_key': has_db_key,
                        'has_env_key': has_env_key,
                        'key_source': key_source,  # Frontend expects 'key_source' not 'api_key_source'
                        'last_tested': row['api_key_last_tested'].isoformat() if row['api_key_last_tested'] else None,
                        'test_status': row['api_key_test_status'],
                        'key_preview': self._mask_key(row['api_key_encrypted']) if has_db_key else None  # Frontend expects 'key_preview' not 'masked_key'
                    })
                return result

        except Exception as e:
            logger.error(f"Failed to get providers with keys: {e}")
            return []

    def _mask_key(self, encrypted_key):
        """Show first 7 and last 4 chars: sk-or-v...1234"""
        if not encrypted_key:
            return None
        try:
            decrypted = self.cipher.decrypt(encrypted_key.encode()).decode()
            if len(decrypted) > 20:
                return f"{decrypted[:7]}...{decrypted[-4:]}"
            return "***"
        except Exception as e:
            logger.error(f"Failed to mask key: {e}")
            return "***"


# ============================================================================
# Dependency Injection
# ============================================================================

async def get_credit_system(request: Request) -> CreditSystem:
    """Get credit system from app state"""
    return request.app.state.credit_system


async def get_byok_manager(request: Request) -> BYOKManager:
    """Get BYOK manager from app state"""
    return request.app.state.byok_manager


async def get_user_id(authorization: Optional[str] = Header(None)) -> str:
    """
    Extract user ID from authorization header

    Supports two authentication methods:
    1. API Key: Bearer uc_<hex-key>
    2. JWT Token: Bearer <jwt-token>
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    if not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Invalid authorization format. Use: Authorization: Bearer <api-key>")

    # Extract token
    token = authorization[7:]

    # Try API key validation first (format: uc_<hex>)
    if token.startswith('uc_'):
        from api_key_manager import get_api_key_manager
        try:
            manager = get_api_key_manager()
            user_info = await manager.validate_api_key(token)

            if user_info:
                # API key is valid
                return user_info['user_id']
            else:
                raise HTTPException(status_code=401, detail="Invalid or expired API key")
        except Exception as e:
            logger.error(f"API key validation error: {e}")
            raise HTTPException(status_code=401, detail="API key validation failed")

    # Try JWT token validation
    try:
        from api_key_manager import get_api_key_manager
        manager = get_api_key_manager()
        payload = manager.validate_jwt_token(token)

        if payload and 'user_id' in payload:
            return payload['user_id']
        else:
            raise HTTPException(status_code=401, detail="Invalid or expired JWT token")
    except Exception as e:
        logger.error(f"JWT validation error: {e}")
        raise HTTPException(status_code=401, detail="Token validation failed")


def get_user_role(user_id: str) -> str:
    """
    Get user role from userInfo (cached in memory or fetch from Keycloak)

    Args:
        user_id: User identifier

    Returns:
        User role (admin, moderator, developer, analyst, viewer)

    Note: This is a placeholder implementation. In production, this should:
    1. Validate JWT token and extract roles
    2. Query Keycloak for user roles
    3. Cache results in Redis for performance
    """
    # TODO: Implement proper role extraction from JWT or Keycloak
    # For now, assume all users are viewers unless explicitly admin

    # Simple check: if user_id contains 'admin' or is in admin list
    admin_users = os.getenv('ADMIN_USER_IDS', '').split(',')
    if user_id in admin_users or 'admin' in user_id.lower():
        return 'admin'

    return 'viewer'


# ============================================================================
# Chat Completions Endpoint
# ============================================================================

@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    user_id: str = Depends(get_user_id),
    credit_system: CreditSystem = Depends(get_credit_system),
    byok_manager: BYOKManager = Depends(get_byok_manager),
    x_power_level: Optional[str] = Header(None, alias="X-Power-Level")
):
    """
    OpenAI-compatible chat completions endpoint with credit system

    Request Headers:
        Authorization: Bearer <user-api-key>
        X-Power-Level: eco | balanced | precision (optional)

    Returns:
        OpenAI-compatible chat completion response
        + X-Provider-Used: Provider that handled request
        + X-Cost-Incurred: Credits deducted
        + X-Credits-Remaining: Updated balance
    """
    try:
        # Determine power level
        power_level = x_power_level or request.power_level
        if power_level not in POWER_LEVELS:
            power_level = "balanced"

        # Get user tier for cost calculation
        user_tier = await credit_system.get_user_tier(user_id)

        # Get power level config
        power_config = POWER_LEVELS[power_level]

        # Check if user has BYOK for preferred providers
        user_keys = await byok_manager.get_all_user_keys(user_id)

        # Determine BYOK routing:
        # 1. If user has OpenRouter BYOK, use it for ALL models (OpenRouter is universal proxy)
        # 2. Otherwise, check if user has provider-specific BYOK for this model
        using_byok = False
        user_byok_key = None
        detected_provider = None

        if 'openrouter' in user_keys:
            # User has OpenRouter BYOK - use it for all models
            using_byok = True
            user_byok_key = user_keys['openrouter']
            detected_provider = 'openrouter'
            logger.info(f"User {user_id} has OpenRouter BYOK - using for all models")
        else:
            # Check for provider-specific BYOK
            detected_provider = detect_provider_from_model(request.model)
            if detected_provider in user_keys:
                using_byok = True
                user_byok_key = user_keys[detected_provider]
                logger.info(f"User {user_id} has {detected_provider} BYOK")

        # Estimate tokens for pre-check (rough estimate)
        estimated_tokens = sum(len(msg.content.split()) * 1.5 for msg in request.messages)
        estimated_tokens = int(estimated_tokens)

        # Calculate estimated cost
        estimated_cost = credit_system.calculate_cost(
            tokens_used=estimated_tokens,
            model=request.model or "balanced",
            power_level=power_level,
            user_tier=user_tier
        )

        # Check credits BEFORE making request (skip if using BYOK)
        if not using_byok and user_tier != 'free':
            current_balance = await credit_system.get_user_credits(user_id)

            if current_balance < estimated_cost:
                raise HTTPException(
                    status_code=402,  # Payment Required
                    detail=f"Insufficient credits. Balance: {current_balance:.6f}, Estimated cost: {estimated_cost:.6f}"
                )

            # Check monthly cap
            within_cap = await credit_system.check_monthly_cap(user_id, estimated_cost)
            if not within_cap:
                raise HTTPException(
                    status_code=429,  # Too Many Requests
                    detail="Monthly spending cap exceeded"
                )

        # Prepare request for LiteLLM proxy
        proxy_request = {
            "messages": [{"role": msg.role, "content": msg.content} for msg in request.messages],
            "max_tokens": request.max_tokens or power_config["max_tokens"],
            "temperature": request.temperature or power_config["temperature"],
            "stream": request.stream,
            "user": user_id,  # For usage tracking
            "metadata": {
                "user_id": user_id,
                "power_level": power_level,
                "task_type": request.task_type,
                "privacy_required": request.privacy_required,
                "user_tier": user_tier
            }
        }

        # Add model if specified
        if request.model:
            proxy_request["model"] = request.model

        # Determine API endpoint and headers based on BYOK or system key
        if using_byok:
            # User is using their own API key
            logger.info(f"Using BYOK for {user_id} with provider {detected_provider}")

            # Get provider config
            provider_config = PROVIDER_CONFIGS.get(detected_provider, PROVIDER_CONFIGS['openrouter'])
            base_url = provider_config['base_url']
            api_key = user_byok_key
            provider_name = detected_provider.title()

            # Build headers
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                **provider_config['default_headers']
            }

        else:
            # Using system OpenRouter key (charge credits)
            logger.info(f"Using system OpenRouter key for {user_id}")

            # Get system key manager
            system_key_manager = SystemKeyManager(credit_system.db_pool, BYOK_ENCRYPTION_KEY)

            # Get provider info from database for direct API call
            async with credit_system.db_pool.acquire() as conn:
                # Get OpenRouter provider (or first enabled provider)
                provider = await conn.fetchrow("""
                    SELECT id, name, type, api_key_encrypted, config
                    FROM llm_providers
                    WHERE enabled = true AND type = 'openrouter'
                    ORDER BY priority DESC
                    LIMIT 1
                """)

                if not provider:
                    raise HTTPException(
                        status_code=503,
                        detail="No LLM providers configured. Please configure OpenRouter in Platform Settings."
                    )

                # Get provider config (handle both dict and JSON string)
                provider_db_config = provider['config'] or {}
                if isinstance(provider_db_config, str):
                    import json
                    provider_db_config = json.loads(provider_db_config)

                base_url = provider_db_config.get('base_url', 'https://openrouter.ai/api/v1')
                provider_name = provider['name']

                # Get system API key (prefer database over environment)
                api_key = await system_key_manager.get_system_key(provider['id'])
                if not api_key:
                    # Fallback to old method (plain text in db)
                    api_key = provider['api_key_encrypted']
                    if not api_key:
                        raise HTTPException(
                            status_code=503,
                            detail="No API key configured for system provider. Please configure in Platform Settings."
                        )

            # Build headers for OpenRouter
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://unicorncommander.ai",  # Required by OpenRouter
                "X-Title": "UC-1 Pro Ops Center"  # Required by OpenRouter
            }

        # Call provider API directly
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=proxy_request,
                headers=headers
            )

            if response.status_code != 200:
                logger.error(f"OpenRouter API error: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"LLM provider error: {response.text}"
                )

            response_data = response.json()

        # Extract usage information
        usage = response_data.get('usage', {})
        tokens_used = usage.get('total_tokens', estimated_tokens)
        provider_used = response_data.get('model', 'unknown')

        # Calculate actual cost
        actual_cost = credit_system.calculate_cost(
            tokens_used=tokens_used,
            model=provider_used,
            power_level=power_level,
            user_tier=user_tier
        )

        # Debit credits (skip if using BYOK - user pays provider directly)
        if using_byok:
            # User is using their own API key - no credit charge
            new_balance = await credit_system.get_user_credits(user_id)
            transaction_id = None
            actual_cost = 0.0  # No cost to user's credit balance
            logger.info(f"BYOK request for {user_id} - no credits charged")
        elif user_tier != 'free' or actual_cost > 0:
            # Using system key - charge credits
            new_balance, transaction_id = await credit_system.debit_credits(
                user_id=user_id,
                amount=actual_cost,
                metadata={
                    'provider': provider_used,
                    'model': provider_used,
                    'tokens_used': tokens_used,
                    'power_level': power_level,
                    'task_type': request.task_type,
                    'cost': actual_cost
                }
            )
        else:
            # Free tier with free model
            new_balance = await credit_system.get_user_credits(user_id)
            transaction_id = None

        # Track usage event (Epic 1.8: Usage Metering)
        try:
            await usage_meter.track_usage(
                user_id=user_id,
                service="litellm",
                model=provider_used,
                tokens=tokens_used,
                cost=actual_cost,
                is_free=(user_tier == 'free' and actual_cost == 0),
                metadata={
                    'power_level': power_level,
                    'task_type': request.task_type,
                    'privacy_required': request.privacy_required,
                    'provider': provider_used,
                    'transaction_id': transaction_id
                }
            )
        except Exception as usage_error:
            # Log error but don't fail the request
            logger.error(f"Failed to track usage: {usage_error}")

        # Add custom headers to response
        response_data['_metadata'] = {
            'provider_used': provider_used,
            'cost_incurred': actual_cost,
            'credits_remaining': new_balance,
            'transaction_id': transaction_id,
            'power_level': power_level,
            'user_tier': user_tier,
            'using_byok': using_byok,
            'byok_provider': detected_provider if using_byok else None
        }

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat completion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ============================================================================
# Credit Management Endpoints
# ============================================================================

@router.get("/credits", response_model=CreditResponse)
async def get_credits(
    user_id: str = Depends(get_user_id),
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """Get current credit balance"""
    try:
        balance = await credit_system.get_user_credits(user_id)
        tier = await credit_system.get_user_tier(user_id)

        return {
            'user_id': user_id,
            'credits_remaining': balance,
            'tier': tier,
            'monthly_cap': None  # TODO: fetch from database
        }

    except Exception as e:
        logger.error(f"Error getting credits: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve credits")


@router.post("/credits/purchase")
async def purchase_credits(
    purchase: CreditPurchaseRequest,
    user_id: str = Depends(get_user_id),
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    Purchase credits via Stripe

    Credit packages:
    - $10 = 10,000 credits
    - $50 = 55,000 credits (10% bonus)
    - $100 = 120,000 credits (20% bonus)
    """
    try:
        # Validate amount
        valid_amounts = {10.0: 10000, 50.0: 55000, 100.0: 120000}

        if purchase.amount not in valid_amounts:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid amount. Valid amounts: {list(valid_amounts.keys())}"
            )

        credits_to_add = valid_amounts[purchase.amount]

        # Create Stripe charge
        try:
            charge = stripe.Charge.create(
                amount=int(purchase.amount * 100),  # Convert to cents
                currency='usd',
                source=purchase.stripe_token,
                description=f"Credit purchase: {credits_to_add} credits",
                metadata={
                    'user_id': user_id,
                    'credits': credits_to_add
                }
            )

            if charge.status != 'succeeded':
                raise HTTPException(status_code=402, detail="Payment failed")

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {e}")
            raise HTTPException(status_code=402, detail=f"Payment error: {str(e)}")

        # Add credits to account
        new_balance = await credit_system.credit_credits(
            user_id=user_id,
            amount=credits_to_add,
            reason="purchase"
        )

        return {
            'success': True,
            'credits_added': credits_to_add,
            'new_balance': new_balance,
            'transaction_id': charge.id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Purchase error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Purchase failed")


@router.get("/credits/history")
async def get_credit_history(
    limit: int = 100,
    offset: int = 0,
    user_id: str = Depends(get_user_id),
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """Get credit transaction history"""
    try:
        history = await credit_system.get_credit_history(
            user_id=user_id,
            limit=min(limit, 1000),  # Cap at 1000
            offset=offset
        )

        return {
            'transactions': history,
            'total': len(history),
            'limit': limit,
            'offset': offset
        }

    except Exception as e:
        logger.error(f"Error getting history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve history")


# ============================================================================
# Model & Usage Endpoints
# ============================================================================

@router.get("/models")
async def list_models(
    user_id: str = Depends(get_user_id),
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    List available models based on user tier

    Returns OpenAI-compatible model list
    """
    try:
        tier = await credit_system.get_user_tier(user_id)

        # Define models by tier
        models_by_tier = {
            'free': [
                {'id': 'llama3-8b-local', 'object': 'model', 'owned_by': 'local', 'tier': 'free'},
                {'id': 'qwen-32b-local', 'object': 'model', 'owned_by': 'local', 'tier': 'free'},
                {'id': 'llama3-70b-groq', 'object': 'model', 'owned_by': 'groq', 'tier': 'free'},
                {'id': 'mixtral-8x7b-hf', 'object': 'model', 'owned_by': 'huggingface', 'tier': 'free'},
            ],
            'starter': [
                {'id': 'mixtral-8x22b-together', 'object': 'model', 'owned_by': 'together', 'tier': 'starter'},
                {'id': 'llama3-70b-deepinfra', 'object': 'model', 'owned_by': 'deepinfra', 'tier': 'starter'},
                {'id': 'qwen-72b-fireworks', 'object': 'model', 'owned_by': 'fireworks', 'tier': 'starter'},
            ],
            'professional': [
                {'id': 'claude-3.5-sonnet-openrouter', 'object': 'model', 'owned_by': 'openrouter', 'tier': 'professional'},
                {'id': 'gpt-4o-openrouter', 'object': 'model', 'owned_by': 'openrouter', 'tier': 'professional'},
            ],
            'enterprise': [
                {'id': 'claude-3.5-sonnet', 'object': 'model', 'owned_by': 'anthropic', 'tier': 'enterprise'},
                {'id': 'gpt-4o', 'object': 'model', 'owned_by': 'openai', 'tier': 'enterprise'},
            ]
        }

        # Collect all models up to user's tier
        tier_order = ['free', 'starter', 'professional', 'enterprise']
        user_tier_index = tier_order.index(tier) if tier in tier_order else 0

        available_models = []
        for i in range(user_tier_index + 1):
            available_models.extend(models_by_tier.get(tier_order[i], []))

        return {
            'object': 'list',
            'data': available_models
        }

    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail="Failed to list models")


@router.get("/usage", response_model=UsageStats)
async def get_usage_stats(
    days: int = 30,
    user_id: str = Depends(get_user_id),
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """Get usage statistics"""
    try:
        stats = await credit_system.get_usage_stats(user_id, days=days)
        return stats

    except Exception as e:
        logger.error(f"Error getting usage stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve usage statistics")


# ============================================================================
# BYOK Endpoints
# ============================================================================

@router.post("/byok/keys")
async def add_byok_key(
    request: AddBYOKKeyRequest,
    user_id: str = Depends(get_user_id),
    byok_manager: BYOKManager = Depends(get_byok_manager)
):
    """
    Add or update a BYOK key

    This endpoint validates the API key format and optionally tests it
    against the provider's API before storing.

    Args:
        request: BYOK key information (provider, api_key, metadata)

    Returns:
        Success message with key ID and test results

    Raises:
        400: Invalid provider or key format
        503: API test failed (warning only, still stores key)
    """
    try:
        # Validate key format
        is_valid = await byok_manager.validate_api_key(
            user_id=user_id,
            provider=request.provider,
            api_key=request.api_key
        )

        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid API key format for {request.provider}"
            )

        # Optional: Test key before storing (recommended but non-blocking)
        test_result = None
        try:
            test_result = await test_provider_api_key(request.provider, request.api_key)
            if not test_result.get('success'):
                logger.warning(
                    f"BYOK test failed for {user_id}/{request.provider}: {test_result.get('message')}"
                )
                # Store anyway but include warning in response
        except Exception as test_error:
            logger.warning(f"BYOK test error for {user_id}/{request.provider}: {test_error}")
            # Continue storing even if test fails

        # Store key
        key_id = await byok_manager.store_user_api_key(
            user_id=user_id,
            provider=request.provider,
            api_key=request.api_key,
            metadata=request.metadata
        )

        logger.info(f"User {user_id} added/updated BYOK key for {request.provider}")

        return {
            'success': True,
            'key_id': key_id,
            'provider': request.provider,
            'message': 'API key stored successfully',
            'test_result': test_result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding BYOK key for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add API key")


@router.get("/byok/keys")
async def list_byok_keys(
    user_id: str = Depends(get_user_id),
    byok_manager: BYOKManager = Depends(get_byok_manager)
):
    """List user's stored provider keys (masked)"""
    try:
        providers = await byok_manager.list_user_providers(user_id)
        return {'providers': providers}

    except Exception as e:
        logger.error(f"Error listing BYOK keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to list keys")


@router.delete("/byok/keys/{provider}")
async def delete_byok_key(
    provider: str,
    user_id: str = Depends(get_user_id),
    byok_manager: BYOKManager = Depends(get_byok_manager)
):
    """Delete user's API key for a provider"""
    try:
        deleted = await byok_manager.delete_user_api_key(user_id, provider)

        if not deleted:
            raise HTTPException(status_code=404, detail="Provider key not found")

        return {'success': True, 'provider': provider}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting BYOK key: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete key")


@router.post("/byok/keys/{provider}/toggle")
async def toggle_byok_key(
    provider: str,
    request: ToggleBYOKRequest,
    user_id: str = Depends(get_user_id),
    byok_manager: BYOKManager = Depends(get_byok_manager)
):
    """
    Enable or disable a BYOK key

    Args:
        provider: Provider name
        request: Toggle request (enabled: true/false)

    Returns:
        New enabled status

    Raises:
        404: Key not found
    """
    try:
        updated = await byok_manager.toggle_provider(user_id, provider, request.enabled)

        if not updated:
            raise HTTPException(
                status_code=404,
                detail=f"No API key found for provider '{provider}'"
            )

        action = "enabled" if request.enabled else "disabled"
        logger.info(f"User {user_id} {action} BYOK key for {provider}")

        return {
            'success': True,
            'provider': provider,
            'enabled': request.enabled,
            'message': f'API key for {provider} {action} successfully'
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling BYOK key: {e}")
        raise HTTPException(status_code=500, detail="Failed to toggle API key")


# Rate limiting for test endpoint (simple in-memory tracker)
from collections import defaultdict
from time import time as current_time

_test_rate_limits = defaultdict(list)
TEST_RATE_LIMIT = 5  # Max 5 tests per minute
TEST_RATE_WINDOW = 60  # 60 seconds


def check_test_rate_limit(user_id: str) -> bool:
    """Check if user is within rate limit for testing"""
    now = current_time()

    # Clean old timestamps
    _test_rate_limits[user_id] = [
        ts for ts in _test_rate_limits[user_id]
        if now - ts < TEST_RATE_WINDOW
    ]

    # Check limit
    if len(_test_rate_limits[user_id]) >= TEST_RATE_LIMIT:
        return False

    # Add new timestamp
    _test_rate_limits[user_id].append(now)
    return True


async def test_provider_api_key(provider: str, api_key: str) -> Dict:
    """Test API key against provider's API"""

    # Normalize provider name to lowercase for comparison
    provider_lower = provider.lower()

    if provider_lower == 'openrouter':
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    'https://openrouter.ai/api/v1/models',
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'HTTP-Referer': 'https://unicorncommander.ai',
                        'X-Title': 'UC-1 Pro Ops Center'
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    model_count = len(data.get('data', []))
                    return {
                        'success': True,
                        'message': f'Valid OpenRouter key. {model_count} models available.',
                        'model_count': model_count
                    }
                elif response.status_code == 401:
                    return {'success': False, 'message': 'Invalid API key'}
                elif response.status_code == 403:
                    return {'success': False, 'message': 'API key lacks permissions'}
                else:
                    return {'success': False, 'message': f'API error: {response.status_code}'}

        except httpx.TimeoutException:
            return {'success': False, 'message': 'Request timeout'}
        except Exception as e:
            return {'success': False, 'message': f'Test failed: {str(e)}'}

    elif provider_lower == 'openai':
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    'https://api.openai.com/v1/models',
                    headers={'Authorization': f'Bearer {api_key}'}
                )

                if response.status_code == 200:
                    data = response.json()
                    model_count = len(data.get('data', []))
                    return {
                        'success': True,
                        'message': f'Valid OpenAI key. {model_count} models available.',
                        'model_count': model_count
                    }
                elif response.status_code == 401:
                    return {'success': False, 'message': 'Invalid API key'}
                else:
                    return {'success': False, 'message': f'API error: {response.status_code}'}

        except Exception as e:
            return {'success': False, 'message': f'Test failed: {str(e)}'}

    elif provider_lower == 'anthropic':
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    'https://api.anthropic.com/v1/messages',
                    headers={
                        'x-api-key': api_key,
                        'anthropic-version': '2023-06-01',
                        'content-type': 'application/json'
                    },
                    json={
                        'model': 'claude-3-haiku-20240307',
                        'max_tokens': 1,
                        'messages': [{'role': 'user', 'content': 'Hi'}]
                    }
                )

                if response.status_code == 200:
                    return {
                        'success': True,
                        'message': 'Valid Anthropic API key.',
                        'model': 'claude-3-haiku-20240307'
                    }
                elif response.status_code == 401:
                    return {'success': False, 'message': 'Invalid API key'}
                else:
                    return {'success': False, 'message': f'API error: {response.status_code}'}

        except Exception as e:
            return {'success': False, 'message': f'Test failed: {str(e)}'}

    elif provider_lower == 'google':
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}'
                )

                if response.status_code == 200:
                    data = response.json()
                    model_count = len(data.get('models', []))
                    return {
                        'success': True,
                        'message': f'Valid Google API key. {model_count} models available.',
                        'model_count': model_count
                    }
                elif response.status_code == 400:
                    return {'success': False, 'message': 'Invalid API key'}
                else:
                    return {'success': False, 'message': f'API error: {response.status_code}'}

        except Exception as e:
            return {'success': False, 'message': f'Test failed: {str(e)}'}

    else:
        return {'success': False, 'message': f'Testing not supported for provider: {provider}'}


@router.post("/byok/keys/{provider}/test")
async def test_byok_key(
    provider: str,
    user_id: str = Depends(get_user_id),
    byok_manager: BYOKManager = Depends(get_byok_manager)
):
    """
    Test a BYOK key against provider API

    Rate Limited: 5 tests per minute per user

    Args:
        provider: Provider name to test

    Returns:
        Test results with success status and details
    """
    try:
        # Check rate limit
        if not check_test_rate_limit(user_id):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Maximum 5 tests per minute."
            )

        # Get decrypted key
        api_key = await byok_manager.get_user_api_key(user_id, provider)

        if not api_key:
            raise HTTPException(
                status_code=404,
                detail=f"No API key found for provider '{provider}'"
            )

        # Test key
        test_result = await test_provider_api_key(provider, api_key)

        logger.info(f"User {user_id} tested BYOK key for {provider}: {test_result.get('success')}")

        return {
            'success': test_result.get('success'),
            'provider': provider,
            'message': test_result.get('message'),
            'details': {k: v for k, v in test_result.items() if k not in ['success', 'message']}
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing BYOK key: {e}")
        raise HTTPException(status_code=500, detail="Failed to test API key")


@router.get("/byok/keys/{provider}/usage")
async def get_byok_usage(
    provider: str,
    user_id: str = Depends(get_user_id),
    byok_manager: BYOKManager = Depends(get_byok_manager)
):
    """
    Get usage statistics for a BYOK key

    NOTE: Placeholder for Phase 2 - usage tracking integration

    Args:
        provider: Provider name

    Returns:
        Usage statistics
    """
    try:
        # Verify key exists
        providers = await byok_manager.list_user_providers(user_id)
        provider_exists = any(p['provider'] == provider for p in providers)

        if not provider_exists:
            raise HTTPException(
                status_code=404,
                detail=f"No API key found for provider '{provider}'"
            )

        # TODO: Query usage_metering table for BYOK requests
        # For now, return placeholder

        return {
            'provider': provider,
            'total_requests': 0,
            'total_tokens': 0,
            'total_cost': 0.0,
            'last_used': None,
            'message': 'Usage tracking integration coming in Phase 2'
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting BYOK usage: {e}")
        raise HTTPException(status_code=500, detail="Failed to get usage statistics")


@router.get("/byok/providers")
async def list_supported_providers():
    """
    List all supported BYOK providers

    Returns:
        List of provider configurations with details
    """
    return {
        'providers': [
            {
                'name': 'openrouter',
                'display_name': 'OpenRouter',
                'description': 'Universal LLM proxy - 200+ models including GPT-4o, Claude 3.5 Sonnet, Gemini 2.0',
                'key_format': 'sk-or-v1-...',
                'signup_url': 'https://openrouter.ai',
                'docs_url': 'https://openrouter.ai/docs',
                'supports_test': True
            },
            {
                'name': 'openai',
                'display_name': 'OpenAI',
                'description': 'GPT-4o, GPT-4o-mini, GPT-4-turbo, o1-preview, o1-mini, DALL-E 3',
                'key_format': 'sk-proj-...',
                'signup_url': 'https://platform.openai.com',
                'docs_url': 'https://platform.openai.com/docs',
                'supports_test': True
            },
            {
                'name': 'anthropic',
                'display_name': 'Anthropic',
                'description': 'Claude 3.5 Sonnet (latest), Claude 3 Opus/Sonnet/Haiku',
                'key_format': 'sk-ant-...',
                'signup_url': 'https://console.anthropic.com',
                'docs_url': 'https://docs.anthropic.com',
                'supports_test': True
            },
            {
                'name': 'google',
                'display_name': 'Google AI',
                'description': 'Gemini 2.0 Flash, Gemini 1.5 Pro/Flash (up to 2M context)',
                'key_format': 'AIza...',
                'signup_url': 'https://aistudio.google.com/apikey',
                'docs_url': 'https://ai.google.dev/docs',
                'supports_test': True
            }
        ]
    }


# ============================================================================
# System Provider Keys (Admin Only)
# ============================================================================

@router.get("/admin/system-keys")
async def get_system_provider_keys(
    request: Request,
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    Get all providers with system key status (admin only)

    Authentication: Uses session cookie (same as other admin endpoints)

    Returns:
        List of providers with key configuration status
    """
    try:
        # Check admin role from session
        user = await require_admin_from_session(request)
        user_id = user.get("email", user.get("username", "unknown"))

        # Get system key manager
        system_key_manager = SystemKeyManager(credit_system.db_pool, BYOK_ENCRYPTION_KEY)
        providers = await system_key_manager.get_all_providers_with_keys()

        logger.info(f"Admin {user_id} retrieved system provider keys")

        return {'providers': providers}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting system keys: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve system keys")


@router.put("/admin/system-keys/{provider_id}")
async def set_system_provider_key(
    provider_id: str,
    request_obj: Request,
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    Set system API key for a provider (admin only)

    Authentication: Uses session cookie (same as other admin endpoints)

    Args:
        provider_id: Provider UUID
        request_obj: FastAPI request (contains session cookie)
        Body: {"api_key": "sk-..."}

    Returns:
        Success message
    """
    try:
        # Check admin role from session
        user = await require_admin_from_session(request_obj)
        user_id = user.get("email", user.get("username", "unknown"))

        # Parse request body
        body = await request_obj.json()
        api_key = body.get('api_key')
        if not api_key or len(api_key) < 10:
            raise HTTPException(status_code=400, detail="Invalid API key")

        # Store system key
        system_key_manager = SystemKeyManager(credit_system.db_pool, BYOK_ENCRYPTION_KEY)
        await system_key_manager.set_system_key(provider_id, api_key, 'database')

        logger.info(f"Admin {user_id} updated system key for provider {provider_id}")

        return {
            'success': True,
            'message': 'System key updated successfully',
            'provider_id': provider_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting system key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to set system key")


@router.delete("/admin/system-keys/{provider_id}")
async def delete_system_provider_key(
    provider_id: str,
    request: Request,
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    Delete system API key (falls back to environment) (admin only)

    Authentication: Uses session cookie (same as other admin endpoints)

    Args:
        provider_id: Provider UUID
        request: FastAPI request (contains session cookie)

    Returns:
        Success message
    """
    try:
        # Check admin role from session
        user = await require_admin_from_session(request)
        user_id = user.get("email", user.get("username", "unknown"))

        # Delete system key
        system_key_manager = SystemKeyManager(credit_system.db_pool, BYOK_ENCRYPTION_KEY)
        await system_key_manager.delete_system_key(provider_id)

        logger.info(f"Admin {user_id} deleted system key for provider {provider_id}")

        return {
            'success': True,
            'message': 'System key deleted (will fall back to environment variable)',
            'provider_id': provider_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting system key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete system key")


@router.post("/admin/system-keys/{provider_id}/test")
async def test_system_provider_key(
    provider_id: str,
    request: Request,
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    Test system API key connection (admin only)

    Authentication: Uses session cookie (same as other admin endpoints)
    Rate Limited: 5 tests per minute per user

    Args:
        provider_id: Provider UUID
        request: FastAPI request (contains session cookie)

    Returns:
        Test results with success status and details
    """
    try:
        # Check admin role from session
        user = await require_admin_from_session(request)
        user_id = user.get("email", user.get("username", "unknown"))

        # Check rate limit
        if not check_test_rate_limit(user_id):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Maximum 5 tests per minute."
            )

        # Get system key manager
        system_key_manager = SystemKeyManager(credit_system.db_pool, BYOK_ENCRYPTION_KEY)

        # Get provider info
        async with credit_system.db_pool.acquire() as conn:
            provider = await conn.fetchrow("""
                SELECT name, type as provider_type FROM llm_providers WHERE id = $1
            """, provider_id)

            if not provider:
                raise HTTPException(status_code=404, detail="Provider not found")

        # Get system key
        api_key = await system_key_manager.get_system_key(provider_id)
        if not api_key:
            raise HTTPException(status_code=400, detail="No API key configured")

        # Test using existing test function
        test_result = await test_provider_api_key(provider['name'], api_key)

        # Update test status in database
        async with credit_system.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE llm_providers
                SET api_key_last_tested = NOW(),
                    api_key_test_status = $1
                WHERE id = $2
            """, 'success' if test_result['success'] else 'failed', provider_id)

        logger.info(f"Admin {user_id} tested system key for provider {provider_id}: {test_result.get('success')}")

        return {
            'success': test_result.get('success'),
            'provider_id': provider_id,
            'provider_name': provider['name'],
            'message': test_result.get('message'),
            'details': {k: v for k, v in test_result.items() if k not in ['success', 'message']}
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing system key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to test system key")


# ============================================================================
# Health Check
# ============================================================================

@router.get("/admin/models/openrouter")
async def get_openrouter_models(
    request: Request,
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    Fetch all models from OpenRouter API and merge with database status

    Returns:
        List of models with pricing, capabilities, and enable/disable status
    """
    try:
        # Check admin permission
        user = await require_admin_from_session(request)
        user_id = user.get("email", user.get("username", "unknown"))

        logger.info(f"Admin {user_id} requesting OpenRouter model catalog")

        # Get OpenRouter API key from database
        async with credit_system.db_pool.acquire() as conn:
            # Get OpenRouter provider
            provider = await conn.fetchrow("""
                SELECT id, name, api_key_encrypted
                FROM llm_providers
                WHERE LOWER(name) = 'openrouter'
            """)

            if not provider or not provider['api_key_encrypted']:
                raise HTTPException(status_code=404, detail="OpenRouter system key not configured")

            # Decrypt API key
            cipher = Fernet(BYOK_ENCRYPTION_KEY.encode())
            api_key = cipher.decrypt(provider['api_key_encrypted'].encode()).decode()

            # Fetch models from OpenRouter
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    'https://openrouter.ai/api/v1/models',
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'HTTP-Referer': 'https://unicorncommander.ai',
                        'X-Title': 'UC-1 Pro Ops Center'
                    }
                )

                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"OpenRouter API error: {response.text}"
                    )

                openrouter_models = response.json().get('data', [])

            # Get enabled/disabled status from our database
            db_models = await conn.fetch("""
                SELECT name, enabled
                FROM llm_models
                WHERE provider_id = $1
            """, provider['id'])

            # Create a lookup dict for database models
            db_models_dict = {m['name']: m for m in db_models}

        # Merge OpenRouter data with our database status
        enriched_models = []
        for model in openrouter_models:
            model_id = model.get('id')
            # Try to match by model ID (which OpenRouter uses as the name)
            db_model = db_models_dict.get(model_id, {})

            # Extract pricing info
            pricing = model.get('pricing', {})
            prompt_cost = float(pricing.get('prompt', 0))
            completion_cost = float(pricing.get('completion', 0))

            # Extract provider name from top_provider object (with null safety)
            top_provider = model.get('top_provider') or {}
            provider_name = top_provider.get('name', 'OpenRouter') if isinstance(top_provider, dict) else 'OpenRouter'

            # Extract performance metrics (if available from OpenRouter) - with null safety
            per_request_limits = model.get('per_request_limits') or {}
            architecture = model.get('architecture') or {}

            enriched_models.append({
                'id': model_id,
                'name': model_id,  # Model ID (e.g., "openai/gpt-4")
                'display_name': model.get('name', model_id),  # Human-readable name
                'provider_name': provider_name,  # Extracted from top_provider
                'description': model.get('description', ''),
                'context_length': model.get('context_length', 0),
                'architecture': architecture.get('modality', 'text') if isinstance(architecture, dict) else 'text',
                # Flatten pricing for frontend compatibility
                'cost_per_1m_input': prompt_cost * 1_000_000,  # Per 1M tokens
                'cost_per_1m_output': completion_cost * 1_000_000,  # Per 1M tokens
                # Keep nested pricing for backward compatibility
                'pricing': {
                    'prompt': prompt_cost,  # Per token
                    'completion': completion_cost,  # Per token
                    'prompt_per_1m': prompt_cost * 1_000_000,
                    'completion_per_1m': completion_cost * 1_000_000
                },
                'top_provider': top_provider if isinstance(top_provider, dict) else {},  # Full provider object
                'enabled': db_model.get('enabled', False),  # Renamed from is_active
                # Performance metrics (null-safe)
                'rating': model.get('rating'),  # Model quality rating (if available)
                'latency_ms': top_provider.get('max_completion_tokens') if isinstance(top_provider, dict) else None,
                'throughput': per_request_limits.get('prompt_tokens') if isinstance(per_request_limits, dict) else None,
                # Capabilities (null-safe)
                'supports_streaming': True,  # OpenRouter supports streaming
                'supports_function_calling': 'tool' in architecture.get('modality', '').lower() if isinstance(architecture, dict) else False,
                'supports_vision': 'vision' in architecture.get('modality', '').lower() if isinstance(architecture, dict) else False
            })

        logger.info(f"Returning {len(enriched_models)} OpenRouter models to admin {user_id}")

        return {
            'success': True,
            'total_models': len(enriched_models),
            'models': enriched_models,
            'provider': {
                'id': provider['id'],
                'name': provider['name']
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching OpenRouter models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch models: {str(e)}")


@router.post("/admin/models/bulk-update")
async def bulk_update_models(
    request: Request,
    update_request: dict,
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    Bulk enable/disable models or update their settings

    Request body:
    {
        "model_ids": ["openai/gpt-4", "anthropic/claude-3"],
        "action": "enable" | "disable" | "update",
        "updates": {  // Only for "update" action
            "enabled": true/false,
            // ... other fields
        }
    }
    """
    try:
        user = await require_admin_from_session(request)
        user_id = user.get("email", user.get("username", "unknown"))

        model_ids = update_request.get('model_ids', [])
        action = update_request.get('action', 'update')
        updates = update_request.get('updates', {})

        if not model_ids or not isinstance(model_ids, list):
            raise HTTPException(status_code=400, detail="model_ids must be a non-empty list")

        logger.info(f"Admin {user_id} bulk updating {len(model_ids)} models: action={action}")

        # Get OpenRouter provider
        async with credit_system.db_pool.acquire() as conn:
            provider = await conn.fetchrow("""
                SELECT id, name
                FROM llm_providers
                WHERE LOWER(name) = 'openrouter'
            """)

            if not provider:
                raise HTTPException(status_code=404, detail="OpenRouter provider not found")

            provider_id = provider['id']

            # Determine enabled status based on action
            if action == 'enable':
                enabled = True
            elif action == 'disable':
                enabled = False
            elif action == 'update':
                enabled = updates.get('enabled', True)
            else:
                raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

            # Upsert models (insert if not exists, update if exists)
            updated_count = 0
            for model_id in model_ids:
                result = await conn.execute("""
                    INSERT INTO llm_models (name, provider_id, enabled, created_at, updated_at)
                    VALUES ($1, $2, $3, NOW(), NOW())
                    ON CONFLICT (name, provider_id)
                    DO UPDATE SET
                        enabled = $3,
                        updated_at = NOW()
                """, model_id, provider_id, enabled)
                updated_count += 1

        logger.info(f"Admin {user_id} bulk updated {updated_count} models to enabled={enabled}")

        return {
            'success': True,
            'updated_count': updated_count,
            'action': action,
            'enabled': enabled,
            'model_ids': model_ids
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk updating models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to bulk update models: {str(e)}")


@router.put("/admin/models/{model_id}/toggle")
async def toggle_model_status(
    model_id: str,
    request: Request,
    credit_system: CreditSystem = Depends(get_credit_system)
):
    """
    Enable or disable a specific model

    Args:
        model_id: Model identifier (e.g., "openai/gpt-4")

    Returns:
        Updated model status
    """
    try:
        # Check admin permission
        user = await require_admin_from_session(request)
        user_id = user.get("email", user.get("username", "unknown"))

        logger.info(f"Admin {user_id} toggling model {model_id}")

        async with credit_system.db_pool.acquire() as conn:
            # Check if model exists
            existing_model = await conn.fetchrow("""
                SELECT id, enabled, provider_id
                FROM llm_models
                WHERE name = $1
            """, model_id)

            if existing_model:
                # Toggle existing model
                new_status = not existing_model['enabled']
                await conn.execute("""
                    UPDATE llm_models
                    SET enabled = $1, updated_at = NOW()
                    WHERE name = $2
                """, new_status, model_id)

                logger.info(f"Admin {user_id} set model {model_id} to {'enabled' if new_status else 'disabled'}")

                return {
                    'success': True,
                    'model_id': model_id,
                    'is_active': new_status,
                    'message': f"Model {'enabled' if new_status else 'disabled'} successfully"
                }
            else:
                # Model doesn't exist in DB yet, create it as enabled
                # First, get the OpenRouter provider ID
                provider = await conn.fetchrow("""
                    SELECT id FROM llm_providers
                    WHERE LOWER(name) = 'openrouter'
                """)

                if not provider:
                    raise HTTPException(status_code=404, detail="OpenRouter provider not found")

                # Insert new model as enabled
                await conn.execute("""
                    INSERT INTO llm_models (
                        provider_id, name, display_name,
                        enabled, created_at, updated_at
                    )
                    VALUES ($1, $2, $2, TRUE, NOW(), NOW())
                """, provider['id'], model_id)

                logger.info(f"Admin {user_id} enabled new model {model_id}")

                return {
                    'success': True,
                    'model_id': model_id,
                    'is_active': True,
                    'message': 'Model enabled successfully'
                }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling model {model_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to toggle model: {str(e)}")


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test LiteLLM proxy connection
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{LITELLM_PROXY_URL}/health")
            litellm_healthy = response.status_code == 200

        return {
            'status': 'healthy' if litellm_healthy else 'degraded',
            'litellm_proxy': 'up' if litellm_healthy else 'down',
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            'status': 'degraded',
            'litellm_proxy': 'down',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }
