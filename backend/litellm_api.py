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

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# Router
router = APIRouter(prefix="/api/v1/llm", tags=["LLM"])

# LiteLLM proxy URL
LITELLM_PROXY_URL = os.getenv('LITELLM_PROXY_URL', 'http://unicorn-litellm-wilmer:4000')


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

        # Check credits BEFORE making request (except free tier)
        if user_tier != 'free':
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

        # Call LiteLLM proxy
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{LITELLM_PROXY_URL}/chat/completions",
                json=proxy_request,
                headers={
                    "Authorization": f"Bearer {os.getenv('LITELLM_MASTER_KEY')}",
                    "Content-Type": "application/json"
                }
            )

            if response.status_code != 200:
                logger.error(f"LiteLLM proxy error: {response.text}")
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

        # Debit credits (except free tier with free models)
        if user_tier != 'free' or actual_cost > 0:
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
            new_balance = await credit_system.get_user_credits(user_id)
            transaction_id = None

        # Add custom headers to response
        response_data['_metadata'] = {
            'provider_used': provider_used,
            'cost_incurred': actual_cost,
            'credits_remaining': new_balance,
            'transaction_id': transaction_id,
            'power_level': power_level,
            'user_tier': user_tier
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
    provider: str,
    api_key: str,
    user_id: str = Depends(get_user_id),
    byok_manager: BYOKManager = Depends(get_byok_manager)
):
    """Add/update user's own API key for a provider"""
    try:
        # Validate key format
        is_valid = await byok_manager.validate_api_key(user_id, provider, api_key)
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid API key format")

        # Store key
        key_id = await byok_manager.store_user_api_key(
            user_id=user_id,
            provider=provider,
            api_key=api_key
        )

        return {
            'success': True,
            'key_id': key_id,
            'provider': provider,
            'message': 'API key stored successfully'
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding BYOK key: {e}")
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
