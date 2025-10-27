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

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# Router
router = APIRouter(prefix="/api/v1/llm", tags=["LLM"])

# LiteLLM proxy URL
LITELLM_PROXY_URL = os.getenv('LITELLM_PROXY_URL', 'http://unicorn-litellm-wilmer:4000')


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
# Dependency Injection
# ============================================================================

async def get_credit_system(request: Request) -> CreditSystem:
    """Get credit system from app state"""
    return request.app.state.credit_system


async def get_byok_manager(request: Request) -> BYOKManager:
    """Get BYOK manager from app state"""
    return request.app.state.byok_manager


async def get_user_id(authorization: Optional[str] = Header(None)) -> str:
    """Extract user ID from authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    if not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    # Extract token and decode (simplified - replace with real JWT validation)
    token = authorization[7:]

    # TODO: Validate JWT token and extract user_id
    # For now, use token as user_id (development only)
    user_id = token

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user_id


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
                api_key = provider['api_key_encrypted']  # Stored as plain text for now
                provider_name = provider['name']

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

    if provider == 'openrouter':
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

    elif provider == 'openai':
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

    elif provider == 'anthropic':
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

    elif provider == 'google':
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
                'description': 'Universal LLM proxy supporting 100+ models',
                'key_format': 'sk-or-v1-...',
                'signup_url': 'https://openrouter.ai',
                'docs_url': 'https://openrouter.ai/docs',
                'supports_test': True
            },
            {
                'name': 'openai',
                'display_name': 'OpenAI',
                'description': 'GPT-4, GPT-3.5, and other OpenAI models',
                'key_format': 'sk-...',
                'signup_url': 'https://platform.openai.com',
                'docs_url': 'https://platform.openai.com/docs',
                'supports_test': True
            },
            {
                'name': 'anthropic',
                'display_name': 'Anthropic',
                'description': 'Claude 3 models (Opus, Sonnet, Haiku)',
                'key_format': 'sk-ant-...',
                'signup_url': 'https://console.anthropic.com',
                'docs_url': 'https://docs.anthropic.com',
                'supports_test': True
            },
            {
                'name': 'google',
                'display_name': 'Google AI',
                'description': 'Gemini and PaLM models',
                'key_format': '39-character alphanumeric',
                'signup_url': 'https://makersuite.google.com',
                'docs_url': 'https://ai.google.dev/docs',
                'supports_test': True
            }
        ]
    }


# ============================================================================
# Health Check
# ============================================================================

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
