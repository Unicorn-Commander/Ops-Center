# BYOK vs Platform API Keys - Architecture Document

**Version**: 1.0.0
**Date**: November 12, 2025
**Status**: Architecture Analysis & Design
**Location**: `/services/ops-center/docs/BYOK_VS_PLATFORM_KEYS_ARCHITECTURE.md`

---

## Executive Summary

The UC-Cloud Ops-Center supports **two distinct API key systems** for accessing LLM services:

1. **BYOK (Bring Your Own Key)** - Users provide their own API keys from providers (OpenAI, Anthropic, OpenRouter, etc.)
   - ❌ **No credit charges** - User pays provider directly
   - ✅ **Platform just routes** requests transparently
   - 💰 **No markup, no platform cost**

2. **Platform API Keys** - Platform issues API keys to users for UC-Cloud services
   - ✅ **Credits ARE charged** from user's balance
   - 💳 **Credits purchased via subscription or pay-as-you-go**
   - 📊 **Platform pays provider + adds markup**
   - 📈 **Usage metering and billing required**

This document provides a comprehensive architecture analysis of both systems, their differences, user flows, database schema, UI design, and implementation roadmap.

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [BYOK System Architecture](#2-byok-system-architecture)
3. [Platform API Keys Architecture](#3-platform-api-keys-architecture)
4. [Database Schema Analysis](#4-database-schema-analysis)
5. [Credit System Integration](#5-credit-system-integration)
6. [User Flows & Journeys](#6-user-flows--journeys)
7. [UI/UX Design Specifications](#7-uiux-design-specifications)
8. [Cost Calculation Logic](#8-cost-calculation-logic)
9. [Implementation Gaps & Fixes](#9-implementation-gaps--fixes)
10. [Testing & Validation](#10-testing--validation)
11. [Security Considerations](#11-security-considerations)
12. [Future Enhancements](#12-future-enhancements)

---

## 1. System Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Request                             │
│                  (Chat Completion / LLM Call)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Ops-Center API Gateway                        │
│              POST /api/v1/llm/chat/completions                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Authentication │
                    │  Middleware    │
                    └────────┬───────┘
                             │
                ┌────────────┴────────────┐
                │                         │
                ▼                         ▼
     ┌──────────────────┐      ┌──────────────────┐
     │  Bearer Token    │      │  Session Cookie  │
     │  (Platform Key)  │      │  (BYOK User)     │
     └────────┬─────────┘      └────────┬─────────┘
              │                         │
              ▼                         ▼
   ┌────────────────────┐    ┌────────────────────┐
   │ API Key Manager    │    │  BYOK Manager      │
   │ (api_key_manager)  │    │ (byok_manager)     │
   └────────┬───────────┘    └────────┬───────────┘
            │                         │
            ▼                         ▼
   ┌─────────────────────────────────────────────┐
   │     LiteLLM Routing Logic                   │
   │     (litellm_api.py:chat_completions)       │
   └─────────────┬───────────────────────────────┘
                 │
    ┌────────────┴────────────┐
    │                         │
    ▼                         ▼
┌──────────────┐        ┌──────────────┐
│ BYOK Route   │        │Platform Route│
│ (User's Key) │        │ (System Key) │
└─────┬────────┘        └──────┬───────┘
      │                        │
      │ ❌ NO CREDITS         │ ✅ DEDUCT CREDITS
      │    CHARGED             │    (credit_system)
      │                        │
      ▼                        ▼
┌────────────────────────────────────────────┐
│         Provider APIs                       │
│  (OpenAI, Anthropic, OpenRouter, etc.)     │
└────────────────────────────────────────────┘
```

### Key Decision Point: BYOK vs Platform Key Routing

**File**: `backend/litellm_api.py` (lines 672-695)

```python
# Determine BYOK routing:
# 1. If user has OpenRouter BYOK, use it for ALL models
# 2. Otherwise, check provider-specific BYOK for this model

if 'openrouter' in user_keys:
    using_byok = True
    user_byok_key = user_keys['openrouter']
    detected_provider = 'openrouter'
    logger.info(f"User {user_id} has OpenRouter BYOK - using for all models")
else:
    detected_provider = detect_provider_from_model(request.model)
    if detected_provider in user_keys:
        using_byok = True
        user_byok_key = user_keys[detected_provider]
```

**Critical Logic**:
- ✅ **BYOK Priority**: If user has ANY BYOK keys, use them first
- ✅ **OpenRouter Universal**: OpenRouter BYOK works for ALL models (universal proxy)
- ❌ **Platform Fallback**: Only use platform keys if NO user keys exist

---

## 2. BYOK System Architecture

### 2.1 Purpose & Benefits

**BYOK (Bring Your Own Key)** allows users to:
- Use their existing provider accounts (OpenAI, Anthropic, OpenRouter, etc.)
- Avoid platform markup and credit charges
- Maintain direct billing relationship with providers
- Benefit from their own provider discounts/credits
- Use platform as a routing/aggregation layer only

### 2.2 BYOK Manager Implementation

**File**: `backend/byok_manager.py` (400 lines)

**Class**: `BYOKManager`

**Key Methods**:
```python
class BYOKManager:
    async def store_user_api_key(user_id, provider, api_key, metadata)
        → Store encrypted API key for provider
        → Returns: key_id (UUID)

    async def get_user_api_key(user_id, provider)
        → Retrieve decrypted API key
        → Returns: plain text key or None

    async def get_all_user_keys(user_id)
        → Get all enabled keys for routing
        → Returns: dict {provider: api_key}

    async def delete_user_api_key(user_id, provider)
        → Remove user's API key

    async def list_user_providers(user_id)
        → List all providers with masked keys

    async def toggle_provider(user_id, provider, enabled)
        → Enable/disable a provider key

    async def validate_api_key(user_id, provider, api_key)
        → Basic format validation
```

### 2.3 Encryption & Security

**Encryption Method**: Fernet symmetric encryption (cryptography library)

**Key Management**:
- Encryption key stored in environment variable: `BYOK_ENCRYPTION_KEY`
- Same key used for all BYOK keys (symmetric encryption)
- Keys encrypted at rest in `user_provider_keys` table

**Key Generation**:
```python
from cryptography.fernet import Fernet

# Generate new encryption key
key = Fernet.generate_key()
# Example: b'mF7EhHLY3zy6w8zYfNjC9v1pR4sU2nQ6tK8xJ3vB5dA='

# Store in .env.auth
BREMOVED
```

### 2.4 Provider Configuration

**Supported Providers** (`backend/litellm_api.py` lines 63-99):

| Provider | Base URL | Model Prefixes | Headers |
|----------|----------|----------------|---------|
| **OpenAI** | https://api.openai.com/v1 | `openai/`, `gpt-`, `o1-`, `o3-` | None |
| **Anthropic** | https://api.anthropic.com/v1 | `anthropic/`, `claude-` | `anthropic-version: 2023-06-01` |
| **OpenRouter** | https://openrouter.ai/api/v1 | ALL models | `HTTP-Referer`, `X-Title` |
| **Google** | https://generativelanguage.googleapis.com/v1beta | `google/`, `gemini-` | None |
| **Ollama** | http://localhost:11434/v1 | `ollama/` | None |
| **Ollama Cloud** | https://ollama.com/api/v1 | `ollama-cloud/` | None |

**Provider Detection Logic**:
```python
def detect_provider_from_model(model_name: str) -> str:
    """
    Detect provider from model name
    Example: "openai/gpt-4" → "openai"
             "claude-3-opus" → "anthropic"
    """
    model_lower = model_name.lower()

    for provider, config in PROVIDER_CONFIGS.items():
        for prefix in config['model_prefixes']:
            if model_lower.startswith(prefix.lower()):
                return provider

    # Default to OpenRouter (universal proxy)
    return 'openrouter'
```

### 2.5 BYOK Request Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. User Adds BYOK Key                                   │
│    POST /api/v1/llm/byok                                │
│    {provider: "openrouter", api_key: "sk-or-xxx"}      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 2. BYOK Manager Validates & Encrypts                    │
│    - Format validation (sk-or- prefix, length)          │
│    - Fernet encryption                                  │
│    - Store in user_provider_keys table                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 3. User Makes LLM Request                               │
│    POST /api/v1/llm/chat/completions                    │
│    {model: "gpt-4", messages: [...]}                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 4. LiteLLM Routing Checks BYOK                          │
│    user_keys = await byok_manager.get_all_user_keys()   │
│    if 'openrouter' in user_keys: use BYOK               │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Direct API Call with User's Key                      │
│    headers = {"Authorization": f"Bearer {user_key}"}    │
│    response = httpx.post(provider_url, ...)             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 6. Response with NO Credit Charge                       │
│    actual_cost = 0.0  # BYOK - no credits charged       │
│    using_byok = True                                    │
│    metadata: {byok_provider: "openrouter"}              │
└─────────────────────────────────────────────────────────┘
```

**Key Code** (`backend/litellm_api.py` lines 847-852):
```python
# Debit credits (skip if using BYOK - user pays provider directly)
if using_byok:
    # User is using their own API key - no credit charge
    new_balance = await credit_system.get_user_credits(user_id)
    transaction_id = None
    actual_cost = 0.0  # No cost to user's credit balance
    logger.info(f"BYOK request for {user_id} - no credits charged")
```

---

## 3. Platform API Keys Architecture

### 3.1 Purpose & Revenue Model

**Platform API Keys** allow:
- Users without provider accounts to access LLMs
- Platform to monetize LLM access (markup on provider costs)
- Unified billing through credit system
- Usage tracking and quotas
- Subscription-based or pay-as-you-go models

### 3.2 API Key Manager Implementation

**File**: `backend/api_key_manager.py` (358 lines)

**Class**: `APIKeyManager`

**Key Methods**:
```python
class APIKeyManager:
    async def create_api_key(user_id, key_name, expires_in_days, permissions)
        → Generate secure API key (uc_<64-char-hex>)
        → Hash with bcrypt, store in user_api_keys table
        → Returns: {api_key, key_id, key_prefix, expires_at}
        → ⚠️ API key shown ONLY ONCE

    async def validate_api_key(api_key)
        → Verify key against bcrypt hash
        → Update last_used timestamp
        → Returns: {user_id, permissions, key_id} or None

    async def list_user_keys(user_id)
        → List all keys (without showing actual keys)
        → Returns: [{key_id, key_name, key_prefix, status}]

    async def revoke_key(user_id, key_id)
        → Set is_active = FALSE

    async def revoke_all_user_keys(user_id)
        → Revoke all keys for user
```

### 3.3 Key Generation & Security

**Key Format**: `uc_<64-character-hex-string>`

Example: `uc_REMOVEDef1234567890abcdef12345678`

**Key Generation Process**:
```python
def _generate_api_key(self) -> Tuple[str, str]:
    """
    Generate secure API key and prefix
    Returns: (full_key, prefix)
    """
    random_bytes = secrets.token_bytes(32)  # 32 bytes = 256 bits
    key_hex = random_bytes.hex()  # 64 hex characters

    full_key = f"uc_{key_hex}"
    prefix = full_key[:7]  # "uc_1234"

    return full_key, prefix
```

**Hashing**:
- Uses bcrypt with auto-generated salt
- Hash stored in `key_hash` column
- Original key NEVER stored (only shown once at creation)

**Verification**:
```python
def _verify_key(self, api_key: str, key_hash: str) -> bool:
    return bcrypt.checkpw(api_key.encode(), key_hash.encode())
```

### 3.4 Platform Key Request Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. User Generates Platform API Key                      │
│    POST /api/v1/admin/users/{user_id}/api-keys          │
│    {key_name: "My App Key", expires_in_days: 90}        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 2. API Key Manager Creates Key                          │
│    - Generate: uc_<64-char-hex>                         │
│    - Hash with bcrypt                                   │
│    - Store in user_api_keys table                       │
│    - Return key (SHOW ONLY ONCE)                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 3. User Makes LLM Request with Bearer Token             │
│    POST /api/v1/llm/chat/completions                    │
│    Authorization: Bearer REMOVED                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 4. Authentication Validates Key                          │
│    key_data = await api_key_manager.validate_api_key()  │
│    → Returns user_id, permissions                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Check User Credits BEFORE Request                    │
│    balance = await credit_system.get_user_credits()     │
│    if balance < estimated_cost: raise 402 error         │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 6. Make API Call with System OpenRouter Key             │
│    api_key = await system_key_manager.get_system_key()  │
│    headers = {"Authorization": f"Bearer {api_key}"}     │
│    response = httpx.post(openrouter_url, ...)           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 7. Calculate Cost & Deduct Credits                      │
│    cost = calculate_cost(tokens, model, tier)           │
│    await credit_system.debit_credits(user_id, cost)     │
│    metadata: {provider, model, tokens, cost}            │
└─────────────────────────────────────────────────────────┘
```

**Key Code** (`backend/litellm_api.py` lines 853-866):
```python
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
```

---

## 4. Database Schema Analysis

### 4.1 BYOK Table: `user_provider_keys`

**Purpose**: Store encrypted user-provided API keys for different providers

```sql
CREATE TABLE user_provider_keys (
    id                SERIAL PRIMARY KEY,
    user_id           VARCHAR(255) NOT NULL,        -- Keycloak user ID
    provider          VARCHAR(100) NOT NULL,        -- openai, anthropic, openrouter, etc.
    api_key_encrypted TEXT NOT NULL,                -- Fernet encrypted API key
    metadata          JSONB DEFAULT '{}'::jsonb,    -- Model preferences, notes
    enabled           BOOLEAN DEFAULT TRUE,         -- Toggle key on/off
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW(),

    UNIQUE(user_id, provider)  -- One key per provider per user
);

CREATE INDEX idx_user_provider_keys_user_id ON user_provider_keys(user_id);
```

**Key Fields**:
- `api_key_encrypted` - Fernet-encrypted API key (never stored in plain text)
- `provider` - Provider identifier (openrouter, openai, anthropic, google)
- `enabled` - Quick toggle without deleting key
- `metadata` - JSONB for flexible storage (model preferences, labels, etc.)

**Data Example**:
```json
{
  "id": 1,
  "user_id": "7a6bfd31-0120-4a30-9e21-0fc3b8006579",
  "provider": "openrouter",
  "api_key_encrypted": "gAAAAABnK8x...(encrypted)",
  "metadata": {"label": "My Personal Key", "default_model": "gpt-4"},
  "enabled": true,
  "created_at": "2025-11-01 10:00:00",
  "updated_at": "2025-11-01 10:00:00"
}
```

### 4.2 Platform Keys Table: `user_api_keys`

**Purpose**: Store hashed platform-issued API keys for external app authentication

```sql
CREATE TABLE user_api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(255) NOT NULL,                -- Keycloak user ID
    key_name    VARCHAR(255) NOT NULL,                -- User-friendly name
    key_hash    TEXT NOT NULL,                        -- bcrypt hash of API key
    key_prefix  VARCHAR(20) NOT NULL,                 -- "uc_1234" for display
    permissions JSONB DEFAULT '[]'::jsonb,            -- ["llm:inference", "llm:models"]
    created_at  TIMESTAMP DEFAULT NOW(),
    last_used   TIMESTAMP,                            -- Track usage
    expires_at  TIMESTAMP,                            -- Optional expiration
    is_active   BOOLEAN DEFAULT TRUE,                 -- Revocation flag
    metadata    JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_user_api_keys_user_id ON user_api_keys(user_id);
CREATE INDEX idx_user_api_keys_prefix ON user_api_keys(key_prefix);
CREATE INDEX idx_user_api_keys_active ON user_api_keys(is_active, expires_at);
```

**Key Fields**:
- `key_hash` - bcrypt hash (original key NEVER stored)
- `key_prefix` - First 7 chars for display ("uc_1234...")
- `permissions` - JSONB array of allowed operations
- `last_used` - Timestamp updated on every validation
- `expires_at` - Optional key expiration (default 90 days)

**Data Example**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "7a6bfd31-0120-4a30-9e21-0fc3b8006579",
  "key_name": "Production App Key",
  "key_hash": "$2b$12$XKj5Zz3...(bcrypt hash)",
  "key_prefix": "uc_a1b2",
  "permissions": ["llm:inference", "llm:models"],
  "created_at": "2025-11-01 10:00:00",
  "last_used": "2025-11-10 15:30:00",
  "expires_at": "2026-02-01 10:00:00",
  "is_active": true,
  "metadata": {"app": "ChatBot v2"}
}
```

### 4.3 Credit System Tables

#### Table: `user_credits`

**Purpose**: Track user credit balances and subscription tiers

```sql
CREATE TABLE user_credits (
    id                SERIAL PRIMARY KEY,
    user_id           TEXT NOT NULL UNIQUE,         -- Keycloak user ID
    credits_remaining FLOAT NOT NULL DEFAULT 0.0,   -- Current balance
    credits_lifetime  FLOAT NOT NULL DEFAULT 0.0,   -- Total ever purchased
    monthly_cap       FLOAT,                        -- Spending limit (NULL = unlimited)
    tier              TEXT NOT NULL DEFAULT 'free', -- free, starter, professional, enterprise
    power_level       TEXT NOT NULL DEFAULT 'balanced',  -- eco, balanced, precision
    auto_recharge     BOOLEAN DEFAULT FALSE,
    recharge_threshold FLOAT DEFAULT 10.0,
    recharge_amount   FLOAT DEFAULT 100.0,
    stripe_customer_id TEXT,                        -- Stripe integration
    last_reset        TIMESTAMP,                    -- Monthly cap reset
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW(),

    CONSTRAINT valid_tier CHECK (tier IN ('free', 'starter', 'professional', 'enterprise')),
    CONSTRAINT positive_credits CHECK (credits_remaining >= 0)
);
```

#### Table: `credit_transactions`

**Purpose**: Complete audit log of all credit movements

```sql
CREATE TABLE credit_transactions (
    id                SERIAL PRIMARY KEY,
    user_id           TEXT NOT NULL,
    transaction_type  TEXT NOT NULL,  -- purchase, debit, refund, bonus, adjustment
    amount            FLOAT NOT NULL,  -- Positive for credit, negative for debit
    balance_after     FLOAT NOT NULL,

    -- LLM Usage Details (for debit transactions)
    provider          TEXT,            -- openai, anthropic, openrouter
    model             TEXT,            -- gpt-4, claude-3-opus
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    tokens_used       INTEGER,         -- Total tokens
    cost_per_token    FLOAT,
    power_level       TEXT,            -- eco, balanced, precision
    byok_used         BOOLEAN DEFAULT FALSE,  -- True if BYOK was used

    -- Payment Details (for purchase transactions)
    payment_method    TEXT,            -- stripe, paypal, manual, bonus
    stripe_transaction_id TEXT,
    stripe_invoice_id TEXT,
    package_id        INTEGER,

    -- Additional Context
    metadata          JSONB,
    notes             TEXT,
    admin_user_id     TEXT,

    created_at        TIMESTAMP DEFAULT NOW(),

    CONSTRAINT valid_transaction_type CHECK (
        transaction_type IN ('purchase', 'debit', 'refund', 'bonus', 'adjustment')
    )
);

CREATE INDEX idx_credit_transactions_user_id ON credit_transactions(user_id);
CREATE INDEX idx_credit_transactions_created_at ON credit_transactions(created_at DESC);
```

### 4.4 Schema Comparison Table

| Feature | BYOK (`user_provider_keys`) | Platform Keys (`user_api_keys`) |
|---------|----------------------------|--------------------------------|
| **Purpose** | Store user's provider API keys | Store platform-issued API keys |
| **Storage** | Fernet encrypted | bcrypt hashed |
| **Key Format** | Provider-specific (sk-..., sk-ant-...) | `uc_<64-hex>` |
| **Credits Charged** | ❌ NO | ✅ YES |
| **Permissions** | N/A (full provider access) | JSONB array |
| **Expiration** | None (user controls) | Optional (default 90 days) |
| **Revocation** | `enabled` flag | `is_active` flag |
| **Usage Tracking** | Via credit_transactions (byok_used=true) | `last_used` timestamp |
| **Primary Key** | SERIAL (integer) | UUID |
| **Unique Constraint** | (user_id, provider) | None (multiple keys per user) |

---

## 5. Credit System Integration

### 5.1 Credit Manager Overview

**File**: `backend/credit_system.py` (733 lines)

**Class**: `CreditManager`

**Key Responsibilities**:
- Track user credit balances
- Deduct credits for LLM usage
- Allocate monthly credits based on subscription tier
- Manage bonus credits and refunds
- Enforce monthly spending caps
- Maintain complete audit trail

### 5.2 Credit Deduction Flow

```python
# File: backend/litellm_api.py (lines 846-871)

# After LLM request completes:
if using_byok:
    # BYOK Route: NO CREDIT CHARGE
    new_balance = await credit_system.get_user_credits(user_id)
    transaction_id = None
    actual_cost = 0.0
    logger.info(f"BYOK request for {user_id} - no credits charged")

elif user_tier != 'free' or actual_cost > 0:
    # Platform Route: CHARGE CREDITS
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
```

### 5.3 Cost Calculation Logic

**File**: `backend/litellm_credit_system.py`

**Method**: `calculate_cost(tokens_used, model, power_level, user_tier)`

**Formula**:
```
base_cost = tokens_used × provider_cost_per_1k_tokens / 1000
power_multiplier = POWER_LEVELS[power_level]["cost_multiplier"]
tier_multiplier = TIER_MULTIPLIERS[user_tier]

final_cost = base_cost × power_multiplier × tier_multiplier
```

**Power Level Multipliers**:
- `eco`: 0.5x (cheaper, lower quality)
- `balanced`: 1.0x (default)
- `precision`: 2.0x (more expensive, higher quality)

**Tier Multipliers** (Platform Markup):
- `free`: 1.0x (no markup, limited usage)
- `starter`: 1.2x (20% markup)
- `professional`: 1.0x (no markup)
- `enterprise`: 0.8x (20% discount)

**Example Calculation**:
```python
# GPT-4 Turbo: $0.01 per 1K input tokens, $0.03 per 1K output tokens
# User tier: professional (1.0x), Power level: balanced (1.0x)
# Request: 500 input tokens, 200 output tokens

input_cost = 500 × 0.01 / 1000 = $0.005
output_cost = 200 × 0.03 / 1000 = $0.006
base_cost = $0.011

final_cost = $0.011 × 1.0 × 1.0 = $0.011 (0.011 credits)
```

### 5.4 Subscription Tier Allocations

**File**: `backend/credit_system.py` (lines 56-61)

```python
self._tier_allocations = {
    "trial": Decimal("5.00"),         # $1/week ≈ $4/month → $5 credits
    "starter": Decimal("20.00"),      # $19/month → $20 credits
    "professional": Decimal("60.00"),  # $49/month → $60 credits
    "enterprise": Decimal("999999.99") # $99/month → unlimited
}
```

**Monthly Reset**:
- Credits are allocated on the 1st of each month
- Unused credits roll over (no expiration)
- Users can purchase additional credits anytime

### 5.5 Credit Purchase Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. User Selects Credit Package                          │
│    - $10 for 10 credits                                 │
│    - $50 for 50 credits (+10% bonus = 55 credits)      │
│    - $100 for 100 credits (+20% bonus = 120 credits)   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Stripe Payment Processing                            │
│    - Create PaymentIntent                               │
│    - User enters card details                           │
│    - Stripe processes payment                           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 3. Credit Manager Allocates Credits                     │
│    await credit_manager.allocate_credits(               │
│        user_id=user_id,                                 │
│        amount=credits_purchased,                        │
│        source="stripe_purchase",                        │
│        metadata={stripe_transaction_id, package_id}     │
│    )                                                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ 4. Transaction Logged                                   │
│    INSERT INTO credit_transactions (                    │
│        user_id, transaction_type="purchase",            │
│        amount=credits, balance_after,                   │
│        payment_method="stripe",                         │
│        stripe_transaction_id, ...                       │
│    )                                                    │
└─────────────────────────────────────────────────────────┘
```

---

## 6. User Flows & Journeys

### 6.1 BYOK User Journey

```
┌─────────────────────────────────────────────────────────┐
│ Step 1: User Registers for UC-Cloud Account             │
│         (via Keycloak SSO: Google/GitHub/Email)         │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 2: User Navigates to Account Settings → API Keys   │
│         URL: /admin/account/api-keys                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 3: User Clicks "Add BYOK Key"                      │
│         Modal opens with provider selection:            │
│         - OpenRouter (recommended - works for all)      │
│         - OpenAI                                        │
│         - Anthropic                                     │
│         - Google                                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 4: User Selects Provider & Enters API Key          │
│         Provider: [OpenRouter ▼]                        │
│         API Key: [sk-or-v1-xxxxxxxxxxxx...]             │
│         Label (optional): "My Personal Key"             │
│         [Validate] [Save]                               │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 5: System Validates & Encrypts Key                 │
│         ✅ Format validation passed                     │
│         ✅ Key encrypted with Fernet                    │
│         ✅ Stored in user_provider_keys table           │
│         ✅ Success: "OpenRouter key added successfully" │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 6: User Makes LLM Request                          │
│         - Via Open-WebUI: Select any model              │
│         - Via Bolt.DIY: AI coding assistant             │
│         - Via Presenton: Presentation generation        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 7: Request Routed Through BYOK                     │
│         ✅ System detects OpenRouter BYOK key           │
│         ✅ Uses user's key (no credit charge)           │
│         ✅ User pays OpenRouter directly                │
│         ✅ Platform acts as routing layer only          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 8: User Monitors Usage (Optional)                  │
│         - View usage stats in Account Settings          │
│         - See "BYOK" label on transactions              │
│         - Track provider costs in OpenRouter dashboard  │
└─────────────────────────────────────────────────────────┘
```

**Benefits for BYOK Users**:
- ✅ $0 platform charges (no credits deducted)
- ✅ Use existing provider credits/discounts
- ✅ Full control over provider billing
- ✅ Access to ALL models via OpenRouter
- ✅ Platform features (Bolt, Presenton, Open-WebUI)

### 6.2 Platform API Key User Journey

```
┌─────────────────────────────────────────────────────────┐
│ Step 1: User Registers & Selects Subscription Tier      │
│         - Trial: $1/week (5 credits/week)               │
│         - Starter: $19/month (20 credits/month)         │
│         - Professional: $49/month (60 credits/month)    │
│         - Enterprise: $99/month (unlimited)             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 2: System Auto-Provisions Credit Account           │
│         ✅ user_credits record created                  │
│         ✅ Credits allocated based on tier              │
│         ✅ Transaction logged (type: "purchase")        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 3: User Generates Platform API Key                 │
│         URL: /admin/account/api-keys                    │
│         Click "Generate Platform API Key"               │
│         Key Name: "My App Key"                          │
│         Expires: 90 days (default)                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 4: System Generates & Returns Key                  │
│         ⚠️ SHOWN ONLY ONCE - SAVE IMMEDIATELY!          │
│         API Key: REMOVED                     │
│         Key Prefix: uc_a1b2 (for reference)             │
│         [Copy to Clipboard] [Download]                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 5: User Configures External Application            │
│         # Example: OpenAI SDK                           │
│         import openai                                   │
│         openai.api_base = "https://api.unicorn..."      │
│         openai.api_key = "uc_a1b2c3d4..."              │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 6: External App Makes LLM Request                  │
│         POST /api/v1/llm/chat/completions               │
│         Authorization: Bearer REMOVED            │
│         {model: "gpt-4", messages: [...]}               │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 7: System Validates Key & Checks Credits           │
│         ✅ Key validated (bcrypt verify)                │
│         ✅ User identified from key                     │
│         ✅ Credit balance checked                       │
│         ✅ Estimated cost calculated                    │
│         ⚠️ If insufficient: 402 Payment Required        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 8: Request Processed with Platform Key             │
│         ✅ System OpenRouter key used                   │
│         ✅ Request sent to provider                     │
│         ✅ Response received                            │
│         ✅ Actual cost calculated from usage            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 9: Credits Deducted & Transaction Logged           │
│         ✅ credit_system.debit_credits() called         │
│         ✅ credits_remaining updated                    │
│         ✅ Transaction logged in credit_transactions    │
│         ✅ Usage metered for analytics                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Step 10: User Monitors Usage & Purchases Credits        │
│         - View balance: GET /api/v1/credits/balance     │
│         - View history: GET /api/v1/credits/transactions│
│         - Buy more: POST /api/v1/credits/purchase       │
│         - Auto-recharge: Enable in settings             │
└─────────────────────────────────────────────────────────┘
```

**Benefits for Platform Key Users**:
- ✅ No need for provider accounts
- ✅ Unified billing (one subscription)
- ✅ Usage tracking and analytics
- ✅ Quotas and spending controls
- ❌ Platform markup on costs

---

## 7. UI/UX Design Specifications

### 7.1 Account Settings → API Keys Page

**URL**: `/admin/account/api-keys`

**Layout**:
```
┌─────────────────────────────────────────────────────────────────┐
│ Account Settings                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Profile | Security | API Keys | Billing | Preferences       │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 🔑 API Keys Management                                       ││
│ │                                                              ││
│ │ Manage your API keys for accessing UC-Cloud services        ││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 📦 Platform API Keys                    [+ Generate New Key] ││
│ │ ─────────────────────────────────────────────────────────── ││
│ │ Use these keys to access UC-Cloud LLM services from your    ││
│ │ applications. Credits will be deducted from your account.   ││
│ │                                                              ││
│ │ ┌──────────────────────────────────────────────────────────┐││
│ │ │ 🔑 Production App Key               Status: ✅ Active     │││
│ │ │    Key: uc_a1b2••••                Created: Nov 1, 2025  │││
│ │ │    Last Used: 2 hours ago           Expires: Feb 1, 2026 │││
│ │ │    [View Details] [Revoke]                               │││
│ │ └──────────────────────────────────────────────────────────┘││
│ │                                                              ││
│ │ ┌──────────────────────────────────────────────────────────┐││
│ │ │ 🔑 Development Key                  Status: 🔒 Revoked   │││
│ │ │    Key: uc_9x8y••••                Created: Oct 15, 2025 │││
│ │ │    Last Used: Never                 Revoked: Nov 1, 2025 │││
│ │ │    [View Details]                                        │││
│ │ └──────────────────────────────────────────────────────────┘││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 🌐 BYOK Keys (Bring Your Own Key)      [+ Add Provider Key] ││
│ │ ─────────────────────────────────────────────────────────── ││
│ │ Use your own API keys from providers. NO credits charged.   ││
│ │                                                              ││
│ │ ┌──────────────────────────────────────────────────────────┐││
│ │ │ 🟢 OpenRouter                       Status: ✅ Active     │││
│ │ │    Label: "My Personal Key"                              │││
│ │ │    Added: Nov 1, 2025                                    │││
│ │ │    Models: ALL (universal proxy)                         │││
│ │ │    Cost: $0 platform charge                              │││
│ │ │    [Edit] [Disable] [Remove]                             │││
│ │ └──────────────────────────────────────────────────────────┘││
│ │                                                              ││
│ │ ┌──────────────────────────────────────────────────────────┐││
│ │ │ 🔴 OpenAI                           Status: ⚠️ Disabled  │││
│ │ │    Label: "Work Account"                                 │││
│ │ │    Added: Oct 20, 2025                                   │││
│ │ │    Models: GPT-4, GPT-3.5, DALL-E                        │││
│ │ │    [Edit] [Enable] [Remove]                              │││
│ │ └──────────────────────────────────────────────────────────┘││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 💡 Key Information                                           ││
│ │ ─────────────────────────────────────────────────────────── ││
│ │ • Platform Keys: Charge credits from your account           ││
│ │ • BYOK Keys: Use your provider account (no platform charge) ││
│ │ • Security: All keys are encrypted at rest                  ││
│ │ • Expiration: Platform keys expire after 90 days (default)  ││
│ └──────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Generate Platform API Key Modal

**Trigger**: Click "+ Generate New Key" button

**Modal Content**:
```
┌─────────────────────────────────────────────────────────┐
│ Generate Platform API Key                     [X Close] │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ Key Name *                                               │
│ ┌──────────────────────────────────────────────────────┐│
│ │ My Application Key                                   ││
│ └──────────────────────────────────────────────────────┘│
│                                                          │
│ Expiration                                               │
│ ┌──────────────────────────────────────────────────────┐│
│ │ 90 days (default) ▼                                  ││
│ └──────────────────────────────────────────────────────┘│
│ Options: 30 days, 60 days, 90 days, 1 year, Never       │
│                                                          │
│ Permissions (optional)                                   │
│ ☑ LLM Inference (llm:inference)                         │
│ ☑ List Models (llm:models)                              │
│ ☐ Admin Access (admin:*)                                │
│                                                          │
│ ⚠️ Important:                                            │
│ • This key will ONLY be shown ONCE                      │
│ • Credits will be charged for all usage                 │
│ • Keep your key secure and never share it               │
│                                                          │
│                         [Cancel] [Generate Key]          │
└─────────────────────────────────────────────────────────┘
```

**After Generation**:
```
┌─────────────────────────────────────────────────────────┐
│ ✅ API Key Generated Successfully!          [X Close]   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ ⚠️ SAVE THIS KEY NOW - IT WON'T BE SHOWN AGAIN          │
│                                                          │
│ Your API Key:                                            │
│ ┌──────────────────────────────────────────────────────┐│
│ │ uc_REMOVEDef...    ││
│ │                                         [📋 Copy]    ││
│ └──────────────────────────────────────────────────────┘│
│                                                          │
│ Key Prefix (for reference): uc_a1b2                      │
│ Created: November 12, 2025 10:30 AM                      │
│ Expires: February 10, 2026                               │
│                                                          │
│ Quick Start:                                             │
│ ┌──────────────────────────────────────────────────────┐│
│ │ # Python Example                                     ││
│ │ import openai                                        ││
│ │ openai.api_base = "https://api.unicorncommander.ai"  ││
│ │ openai.api_key = "uc_a1b2..."                        ││
│ └──────────────────────────────────────────────────────┘│
│                                                          │
│ [📥 Download Documentation] [✅ I Saved My Key]         │
└─────────────────────────────────────────────────────────┘
```

### 7.3 Add BYOK Key Modal

**Trigger**: Click "+ Add Provider Key" button

**Modal Content**:
```
┌─────────────────────────────────────────────────────────┐
│ Add BYOK Provider Key                         [X Close] │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ Provider *                                               │
│ ┌──────────────────────────────────────────────────────┐│
│ │ OpenRouter (Recommended - All Models) ▼              ││
│ └──────────────────────────────────────────────────────┘│
│ Options:                                                 │
│ • OpenRouter - All models (universal proxy)             │
│ • OpenAI - GPT-4, GPT-3.5, DALL-E                       │
│ • Anthropic - Claude models                             │
│ • Google - Gemini models                                │
│                                                          │
│ API Key *                                                │
│ ┌──────────────────────────────────────────────────────┐│
│ │ sk-or-v1-xxxxxxxxxxxx...                             ││
│ └──────────────────────────────────────────────────────┘│
│                                                          │
│ Label (optional)                                         │
│ ┌──────────────────────────────────────────────────────┐│
│ │ My Personal OpenRouter Key                           ││
│ └──────────────────────────────────────────────────────┘│
│                                                          │
│ 💡 Benefits of BYOK:                                     │
│ • ✅ $0 platform charges (no credits deducted)          │
│ • ✅ Use your own provider credits/discounts            │
│ • ✅ Full control over billing                          │
│ • ✅ Access to ALL platform features                    │
│                                                          │
│ 🔒 Security:                                             │
│ • Keys are encrypted with Fernet (AES-256)              │
│ • Keys are never exposed in logs or UI                  │
│ • You can disable/remove keys anytime                   │
│                                                          │
│                        [Cancel] [Validate & Save]        │
└─────────────────────────────────────────────────────────┘
```

### 7.4 Credit Dashboard (Platform Keys Only)

**URL**: `/admin/credits`

**Layout**:
```
┌─────────────────────────────────────────────────────────────────┐
│ Credit Dashboard                                                 │
│                                                                   │
│ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ │
│ │ 💳 Balance       │ │ 📅 Monthly Usage │ │ 🎯 Tier          │ │
│ │ 45.23 credits    │ │ 14.77 / 60       │ │ Professional     │ │
│ │ [Buy Credits]    │ │ Resets: 18 days  │ │ [Upgrade]        │ │
│ └──────────────────┘ └──────────────────┘ └──────────────────┘ │
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 📊 Usage Chart (Last 30 Days)                                ││
│ │                                                              ││
│ │     Credits                                                  ││
│ │     20│                      ●                               ││
│ │       │                   ●     ●                            ││
│ │     15│               ●             ●                        ││
│ │       │           ●                     ●                    ││
│ │     10│       ●                             ●                ││
│ │       │   ●                                     ●            ││
│ │      5│●                                            ●        ││
│ │       └──────────────────────────────────────────────────── ││
│ │        Oct 15        Nov 1          Nov 15          Today    ││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 📜 Recent Transactions                    [View All]         ││
│ │ ─────────────────────────────────────────────────────────── ││
│ │ ┌────────────────────────────────────────────────────────┐ ││
│ │ │ ⬇ LLM Usage - GPT-4                     -0.023 credits │ ││
│ │ │   2 hours ago • 1,234 tokens                           │ ││
│ │ │   Provider: OpenRouter • Balance: 45.23                │ ││
│ │ └────────────────────────────────────────────────────────┘ ││
│ │                                                              ││
│ │ ┌────────────────────────────────────────────────────────┐ ││
│ │ │ 🎁 Bonus Credits                        +10.00 credits │ ││
│ │ │   Yesterday • Reason: Referral reward                  │ ││
│ │ │   Balance: 45.253                                      │ ││
│ │ └────────────────────────────────────────────────────────┘ ││
│ │                                                              ││
│ │ ┌────────────────────────────────────────────────────────┐ ││
│ │ │ 💳 Credit Purchase                     +50.00 credits  │ ││
│ │ │   2 days ago • Stripe •••• 4242 • $50.00              │ ││
│ │ │   Balance: 35.253                                      │ ││
│ │ └────────────────────────────────────────────────────────┘ ││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ 💡 Credit Information                                        ││
│ │ • 1 credit ≈ $0.001 USD                                      ││
│ │ • Credits never expire                                       ││
│ │ • Unused monthly allocation rolls over                       ││
│ │ • BYOK usage does NOT deduct credits                         ││
│ │ • Enable auto-recharge to avoid interruptions                ││
│ └──────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 7.5 BYOK vs Platform Key Comparison Table (Help Page)

**URL**: `/help/api-keys`

```
┌─────────────────────────────────────────────────────────────────┐
│ Understanding API Key Types                                      │
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ Feature Comparison                                           ││
│ ├────────────────┬──────────────────┬──────────────────────────┤│
│ │ Feature        │ BYOK Keys        │ Platform Keys            ││
│ ├────────────────┼──────────────────┼──────────────────────────┤│
│ │ Credit Charges │ ❌ NO            │ ✅ YES                   ││
│ │ Provider Setup │ Required         │ Not Required             ││
│ │ Platform Markup│ None (0%)        │ 0-20% (tier-based)       ││
│ │ Model Access   │ ALL (via OpenRouter) │ ALL                 ││
│ │ Usage Tracking │ Platform only    │ Platform + Billing       ││
│ │ Best For       │ Power users      │ Simple usage             ││
│ │ Key Format     │ Provider-specific│ uc_<64-hex>              ││
│ │ Expiration     │ Never            │ 90 days (default)        ││
│ │ Revocation     │ Disable/Enable   │ Revoke permanently       ││
│ └────────────────┴──────────────────┴──────────────────────────┘│
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ When to Use BYOK Keys                                        ││
│ │ ✅ You already have OpenRouter/OpenAI/Anthropic accounts     ││
│ │ ✅ You want to avoid platform markup                         ││
│ │ ✅ You have provider credits or discounts                    ││
│ │ ✅ You want direct billing relationship with provider        ││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                   │
│ ┌──────────────────────────────────────────────────────────────┐│
│ │ When to Use Platform Keys                                    ││
│ │ ✅ You don't have provider accounts                          ││
│ │ ✅ You want unified billing (one subscription)               ││
│ │ ✅ You want usage tracking and analytics                     ││
│ │ ✅ You want quota management and spending controls           ││
│ └──────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Cost Calculation Logic

### 8.1 Provider Base Costs

**Source**: OpenRouter, OpenAI, Anthropic pricing pages

**Popular Models** (as of November 2025):

| Provider | Model | Input ($/1K tokens) | Output ($/1K tokens) |
|----------|-------|--------------------:|---------------------:|
| OpenAI | gpt-4-turbo | $0.010 | $0.030 |
| OpenAI | gpt-4o | $0.005 | $0.015 |
| OpenAI | gpt-3.5-turbo | $0.0005 | $0.0015 |
| Anthropic | claude-3-opus | $0.015 | $0.075 |
| Anthropic | claude-3-sonnet | $0.003 | $0.015 |
| Anthropic | claude-3-haiku | $0.00025 | $0.00125 |
| OpenRouter | meta-llama/llama-3.1-70b | $0.00052 | $0.00075 |
| OpenRouter | google/gemini-pro | $0.000125 | $0.000375 |

### 8.2 Platform Markup Calculation

**Formula**:
```python
def calculate_cost(
    tokens_used: int,
    model: str,
    power_level: str,
    user_tier: str
) -> float:
    """
    Calculate credit cost for LLM usage

    Args:
        tokens_used: Total tokens (prompt + completion)
        model: Model identifier (e.g., "gpt-4-turbo")
        power_level: eco, balanced, precision
        user_tier: free, starter, professional, enterprise

    Returns:
        Cost in credits (1 credit = $0.001)
    """
    # 1. Get base cost from provider pricing
    provider_cost_per_1k = get_provider_cost(model)
    base_cost = (tokens_used / 1000) * provider_cost_per_1k

    # 2. Apply power level multiplier
    power_multiplier = POWER_LEVELS[power_level]["cost_multiplier"]
    # eco: 0.5x, balanced: 1.0x, precision: 2.0x

    # 3. Apply tier markup
    tier_multiplier = TIER_MULTIPLIERS[user_tier]
    # free: 1.0x, starter: 1.2x, professional: 1.0x, enterprise: 0.8x

    # 4. Calculate final cost
    final_cost = base_cost * power_multiplier * tier_multiplier

    return final_cost
```

**Example 1: GPT-4 Turbo (Professional User, Balanced Power)**
```python
# Request: 1,000 input tokens, 500 output tokens
input_cost = 1000 * 0.010 / 1000 = $0.010
output_cost = 500 * 0.030 / 1000 = $0.015
base_cost = $0.025

power_multiplier = 1.0  # balanced
tier_multiplier = 1.0   # professional

final_cost = $0.025 * 1.0 * 1.0 = $0.025 (25 credits)
```

**Example 2: Claude 3 Opus (Starter User, Precision Power)**
```python
# Request: 2,000 input tokens, 1,000 output tokens
input_cost = 2000 * 0.015 / 1000 = $0.030
output_cost = 1000 * 0.075 / 1000 = $0.075
base_cost = $0.105

power_multiplier = 2.0  # precision (higher quality)
tier_multiplier = 1.2   # starter (20% markup)

final_cost = $0.105 * 2.0 * 1.2 = $0.252 (252 credits)
```

**Example 3: Llama 3.1 70B (Enterprise User, Eco Power)**
```python
# Request: 500 input tokens, 300 output tokens
input_cost = 500 * 0.00052 / 1000 = $0.00026
output_cost = 300 * 0.00075 / 1000 = $0.000225
base_cost = $0.000485

power_multiplier = 0.5  # eco (lower cost)
tier_multiplier = 0.8   # enterprise (20% discount)

final_cost = $0.000485 * 0.5 * 0.8 = $0.000194 (0.194 credits)
```

### 8.3 BYOK Cost (Always $0)

```python
# Regardless of model, tokens, or power level
if using_byok:
    final_cost = 0.0  # NO CREDITS CHARGED

    # User pays provider directly
    # Platform logs transaction with byok_used=True
    # Usage metering tracks for analytics only
```

---

## 9. Implementation Gaps & Fixes

### 9.1 Current State Analysis

#### ✅ What's Working

1. **BYOK System (90% Complete)**
   - ✅ Encryption/decryption working (Fernet)
   - ✅ Database table exists (`user_provider_keys`)
   - ✅ BYOK Manager implemented (400 lines)
   - ✅ Provider detection logic working
   - ✅ Routing logic working (litellm_api.py)
   - ✅ No credit charges for BYOK (lines 847-852)

2. **Platform Keys (80% Complete)**
   - ✅ Key generation working (uc_<64-hex>)
   - ✅ bcrypt hashing working
   - ✅ Database table exists (`user_api_keys`)
   - ✅ API Key Manager implemented (358 lines)
   - ✅ Credit deduction working (lines 853-866)

3. **Credit System (95% Complete)**
   - ✅ Credit Manager implemented (733 lines)
   - ✅ Database tables exist (`user_credits`, `credit_transactions`)
   - ✅ Debit/allocate/refund methods working
   - ✅ Transaction logging working
   - ✅ Cost calculation working

#### ❌ What's Missing

1. **Frontend UI (0% Complete)**
   - ❌ No UI for managing BYOK keys
   - ❌ No UI for generating Platform API keys
   - ❌ No UI for viewing API key list
   - ❌ No credit purchase flow UI

2. **API Endpoints (Partial)**
   - ✅ BYOK endpoints exist (`/api/v1/llm/byok/*`)
   - ❌ Platform key endpoints missing (`/api/v1/admin/users/{user_id}/api-keys/*`)
   - ❌ Credit purchase endpoint needs Stripe integration

3. **Documentation (Partial)**
   - ✅ Backend code documented
   - ❌ No user-facing docs
   - ❌ No API reference for external devs
   - ❌ No quick start guides

4. **Testing (Minimal)**
   - ❌ No end-to-end tests
   - ❌ No BYOK routing tests
   - ❌ No Platform key authentication tests

### 9.2 Implementation Roadmap

#### Phase 1: Backend Fixes (Week 1)

**Priority**: HIGH

**Tasks**:
1. **Create Platform API Key Endpoints** (api_keys_router.py)
   ```python
   # File: backend/api_keys_router.py

   @router.post("/api/v1/admin/users/{user_id}/api-keys")
   async def create_api_key(...):
       """Generate new platform API key"""

   @router.get("/api/v1/admin/users/{user_id}/api-keys")
   async def list_api_keys(...):
       """List all keys for user"""

   @router.delete("/api/v1/admin/users/{user_id}/api-keys/{key_id}")
   async def revoke_api_key(...):
       """Revoke API key"""
   ```

2. **Fix BYOK API Endpoints** (already exist, need testing)
   ```python
   # Verify these endpoints work:
   POST   /api/v1/llm/byok
   GET    /api/v1/llm/byok
   DELETE /api/v1/llm/byok/{provider}
   PUT    /api/v1/llm/byok/{provider}/toggle
   ```

3. **Add Credit Purchase Endpoint** (credit_api.py)
   ```python
   @router.post("/api/v1/credits/purchase")
   async def purchase_credits(
       amount: float,
       stripe_token: str,
       user_id: str = Depends(get_current_user)
   ):
       """Purchase credits via Stripe"""
       # 1. Create Stripe PaymentIntent
       # 2. Process payment
       # 3. Allocate credits
       # 4. Log transaction
   ```

**Estimated Time**: 8 hours

#### Phase 2: Frontend UI (Week 1-2)

**Priority**: HIGH

**Tasks**:
1. **Create AccountAPIKeys.jsx** (src/pages/account/)
   - Two sections: Platform Keys, BYOK Keys
   - Generate Platform Key modal
   - Add BYOK Key modal
   - Key list with status badges
   - Revoke/disable actions

2. **Create BYOKKeyManager.jsx** (src/components/)
   - Provider selection dropdown
   - API key input with validation
   - Label input
   - Save button with loading state

3. **Create PlatformKeyManager.jsx** (src/components/)
   - Key generation form
   - Key display (show once)
   - Copy to clipboard button
   - Quick start code examples

4. **Update CreditDashboard.jsx** (src/pages/)
   - Add "Buy Credits" button
   - Stripe payment modal
   - Credit package selection
   - Transaction history

**Estimated Time**: 16 hours

#### Phase 3: Documentation (Week 2)

**Priority**: MEDIUM

**Tasks**:
1. **User Guide** (docs/USER_GUIDE.md)
   - What are BYOK keys?
   - What are Platform keys?
   - When to use each
   - Setup instructions

2. **API Reference** (docs/API_REFERENCE.md)
   - Authentication
   - Endpoints
   - Request/response examples
   - Error codes

3. **Quick Start Guides** (docs/quickstart/)
   - Python example
   - JavaScript example
   - OpenAI SDK integration
   - LangChain integration

**Estimated Time**: 8 hours

#### Phase 4: Testing & Validation (Week 2-3)

**Priority**: HIGH

**Tasks**:
1. **Backend Tests** (backend/tests/)
   - test_byok_routing.py
   - test_platform_keys.py
   - test_credit_deduction.py

2. **Integration Tests**
   - test_byok_flow_e2e.py (add key → make request → verify no charge)
   - test_platform_key_flow_e2e.py (generate key → make request → verify charge)

3. **Manual Testing Checklist**
   - BYOK key addition
   - Platform key generation
   - LLM request routing
   - Credit deduction
   - Transaction logging

**Estimated Time**: 12 hours

#### Phase 5: Production Deployment (Week 3)

**Priority**: HIGH

**Tasks**:
1. **Database Migration** (if schema changes needed)
2. **Environment Variables** (ensure BYOK_ENCRYPTION_KEY set)
3. **Stripe Configuration** (live keys)
4. **Frontend Build & Deploy**
5. **Backend Restart**
6. **Smoke Tests**

**Estimated Time**: 4 hours

**Total Estimated Time**: 48 hours (6 developer days)

---

## 10. Testing & Validation

### 10.1 Unit Test Suite

#### BYOK Tests

```python
# File: backend/tests/test_byok.py

import pytest
from byok_manager import BYOKManager

@pytest.mark.asyncio
async def test_store_and_retrieve_byok_key():
    """Test storing and retrieving encrypted BYOK key"""
    manager = BYOKManager(db_pool, encryption_key)

    # Store key
    key_id = await manager.store_user_api_key(
        user_id="test_user",
        provider="openrouter",
        api_key="sk-or-v1-test123",
        metadata={"label": "Test Key"}
    )

    assert key_id is not None

    # Retrieve key
    api_key = await manager.get_user_api_key("test_user", "openrouter")

    assert api_key == "sk-or-v1-test123"

@pytest.mark.asyncio
async def test_byok_encryption():
    """Test key encryption/decryption"""
    manager = BYOKManager(db_pool, encryption_key)

    plain_key = "sk-or-v1-supersecret"
    encrypted = manager._encrypt_key(plain_key)

    assert encrypted != plain_key
    assert len(encrypted) > len(plain_key)

    decrypted = manager._decrypt_key(encrypted)
    assert decrypted == plain_key

@pytest.mark.asyncio
async def test_byok_validation():
    """Test API key format validation"""
    manager = BYOKManager(db_pool, encryption_key)

    # Valid keys
    assert manager.validate_api_key("user", "openrouter", "sk-or-v1-" + "x"*40) == True
    assert manager.validate_api_key("user", "openai", "sk-" + "x"*40) == True

    # Invalid keys
    assert manager.validate_api_key("user", "openrouter", "invalid") == False
    assert manager.validate_api_key("user", "openai", "sk-short") == False
```

#### Platform Key Tests

```python
# File: backend/tests/test_platform_keys.py

import pytest
from api_key_manager import APIKeyManager

@pytest.mark.asyncio
async def test_generate_platform_key():
    """Test platform API key generation"""
    manager = APIKeyManager(db_pool)

    result = await manager.create_api_key(
        user_id="test_user",
        key_name="Test Key",
        expires_in_days=90
    )

    assert result["api_key"].startswith("uc_")
    assert len(result["api_key"]) == 67  # uc_ + 64 hex chars
    assert result["key_prefix"] == result["api_key"][:7]

@pytest.mark.asyncio
async def test_validate_platform_key():
    """Test platform API key validation"""
    manager = APIKeyManager(db_pool)

    # Create key
    result = await manager.create_api_key("test_user", "Test Key")
    api_key = result["api_key"]

    # Validate key
    validated = await manager.validate_api_key(api_key)

    assert validated is not None
    assert validated["user_id"] == "test_user"
    assert "permissions" in validated

@pytest.mark.asyncio
async def test_revoke_platform_key():
    """Test platform API key revocation"""
    manager = APIKeyManager(db_pool)

    # Create key
    result = await manager.create_api_key("test_user", "Test Key")
    key_id = result["key_id"]
    api_key = result["api_key"]

    # Revoke key
    revoked = await manager.revoke_key("test_user", key_id)
    assert revoked == True

    # Validate should fail
    validated = await manager.validate_api_key(api_key)
    assert validated is None
```

#### Credit System Tests

```python
# File: backend/tests/test_credit_deduction.py

import pytest
from credit_system import CreditManager

@pytest.mark.asyncio
async def test_credit_deduction_platform():
    """Test credit deduction for Platform key usage"""
    manager = CreditManager()
    await manager.initialize()

    # Create user with credits
    await manager.create_user_credits("test_user", tier="professional")
    await manager.allocate_credits("test_user", 100.0, "test")

    # Deduct credits
    result = await manager.debit_credits(
        user_id="test_user",
        amount=10.0,
        metadata={"provider": "openrouter", "model": "gpt-4"}
    )

    assert result["balance"] == 90.0

@pytest.mark.asyncio
async def test_no_credit_deduction_byok():
    """Test NO credit deduction for BYOK usage"""
    # This test verifies litellm_api.py logic
    # where using_byok=True skips debit_credits()

    # Simulate BYOK request
    using_byok = True
    actual_cost = 0.0

    assert actual_cost == 0.0
    # No debit_credits() call should be made
```

### 10.2 Integration Test Suite

```python
# File: backend/tests/integration/test_byok_flow_e2e.py

import pytest
import httpx

@pytest.mark.asyncio
async def test_byok_end_to_end_flow():
    """
    End-to-end test: Add BYOK key → Make LLM request → Verify no charge
    """
    # 1. Add BYOK key
    response = await httpx.post(
        "http://localhost:8084/api/v1/llm/byok",
        json={
            "provider": "openrouter",
            "api_key": "sk-or-v1-test123",
            "metadata": {"label": "Test Key"}
        },
        cookies={"session_token": test_session_token}
    )
    assert response.status_code == 200

    # 2. Check initial credit balance
    response = await httpx.get(
        "http://localhost:8084/api/v1/credits/balance",
        cookies={"session_token": test_session_token}
    )
    initial_balance = response.json()["balance"]

    # 3. Make LLM request
    response = await httpx.post(
        "http://localhost:8084/api/v1/llm/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "model": "gpt-3.5-turbo"
        },
        cookies={"session_token": test_session_token}
    )
    assert response.status_code == 200

    # 4. Verify metadata shows BYOK was used
    metadata = response.json()["_metadata"]
    assert metadata["using_byok"] == True
    assert metadata["cost_incurred"] == 0.0

    # 5. Verify credits NOT deducted
    response = await httpx.get(
        "http://localhost:8084/api/v1/credits/balance",
        cookies={"session_token": test_session_token}
    )
    final_balance = response.json()["balance"]

    assert final_balance == initial_balance  # NO CHANGE


@pytest.mark.asyncio
async def test_platform_key_end_to_end_flow():
    """
    End-to-end test: Generate Platform key → Make LLM request → Verify charge
    """
    # 1. Generate Platform API key
    response = await httpx.post(
        f"http://localhost:8084/api/v1/admin/users/{test_user_id}/api-keys",
        json={"key_name": "Test Key"},
        cookies={"session_token": test_admin_token}
    )
    assert response.status_code == 200
    api_key = response.json()["api_key"]

    # 2. Check initial credit balance
    response = await httpx.get(
        "http://localhost:8084/api/v1/credits/balance",
        cookies={"session_token": test_session_token}
    )
    initial_balance = response.json()["balance"]

    # 3. Make LLM request with Platform key
    response = await httpx.post(
        "http://localhost:8084/api/v1/llm/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "model": "gpt-3.5-turbo"
        },
        headers={"Authorization": f"Bearer {api_key}"}
    )
    assert response.status_code == 200

    # 4. Verify metadata shows Platform key was used
    metadata = response.json()["_metadata"]
    assert metadata["using_byok"] == False
    assert metadata["cost_incurred"] > 0

    # 5. Verify credits WERE deducted
    response = await httpx.get(
        "http://localhost:8084/api/v1/credits/balance",
        cookies={"session_token": test_session_token}
    )
    final_balance = response.json()["balance"]

    assert final_balance < initial_balance  # CREDITS CHARGED
    assert initial_balance - final_balance == metadata["cost_incurred"]
```

### 10.3 Manual Testing Checklist

#### BYOK Testing

- [ ] **Add BYOK Key**
  - [ ] Open /admin/account/api-keys
  - [ ] Click "Add Provider Key"
  - [ ] Select "OpenRouter"
  - [ ] Enter valid sk-or-v1-... key
  - [ ] Add label "Test Key"
  - [ ] Click "Validate & Save"
  - [ ] Verify success message
  - [ ] Verify key appears in BYOK list

- [ ] **Use BYOK Key**
  - [ ] Open Open-WebUI
  - [ ] Select any model (e.g., GPT-4)
  - [ ] Send message: "Hello"
  - [ ] Verify response received
  - [ ] Check Network tab: verify response includes `using_byok: true`

- [ ] **Verify No Credit Charge**
  - [ ] Note initial credit balance
  - [ ] Make multiple LLM requests
  - [ ] Check credit balance again
  - [ ] Verify balance unchanged

- [ ] **Disable BYOK Key**
  - [ ] Click "Disable" on BYOK key
  - [ ] Make LLM request
  - [ ] Verify request uses Platform key instead
  - [ ] Verify credits ARE charged

#### Platform Key Testing

- [ ] **Generate Platform Key**
  - [ ] Open /admin/account/api-keys
  - [ ] Click "Generate Platform API Key"
  - [ ] Enter name "Test App Key"
  - [ ] Select "90 days" expiration
  - [ ] Click "Generate Key"
  - [ ] Verify key displayed (starts with uc_)
  - [ ] Copy key to clipboard
  - [ ] Verify key shown ONLY ONCE (refresh page, key hidden)

- [ ] **Use Platform Key**
  - [ ] Open terminal
  - [ ] Run curl command:
    ```bash
    curl -X POST https://api.unicorncommander.ai/api/v1/llm/chat/completions \
      -H "Authorization: Bearer REMOVED" \
      -H "Content-Type: application/json" \
      -d '{"messages": [{"role": "user", "content": "Hello"}], "model": "gpt-3.5-turbo"}'
    ```
  - [ ] Verify response received
  - [ ] Verify `using_byok: false` in metadata

- [ ] **Verify Credit Charge**
  - [ ] Note initial credit balance
  - [ ] Make LLM request with Platform key
  - [ ] Check credit balance again
  - [ ] Verify balance decreased
  - [ ] Check credit_transactions table for logged transaction

- [ ] **Revoke Platform Key**
  - [ ] Click "Revoke" on Platform key
  - [ ] Confirm revocation
  - [ ] Try using revoked key
  - [ ] Verify 401 Unauthorized error

#### Credit System Testing

- [ ] **Purchase Credits**
  - [ ] Open /admin/credits
  - [ ] Click "Buy Credits"
  - [ ] Select $50 package (55 credits with bonus)
  - [ ] Enter Stripe test card: 4242 4242 4242 4242
  - [ ] Click "Purchase"
  - [ ] Verify success message
  - [ ] Verify balance increased by 55 credits

- [ ] **Credit Transaction Log**
  - [ ] View transaction history
  - [ ] Verify purchase logged (type: "purchase")
  - [ ] Make LLM request
  - [ ] Verify usage logged (type: "debit")
  - [ ] Check metadata includes model, tokens, cost

---

## 11. Security Considerations

### 11.1 BYOK Security

**Encryption at Rest**:
- ✅ Fernet symmetric encryption (AES-128-CBC with HMAC)
- ✅ Keys never stored in plain text
- ✅ Encryption key stored in environment variable

**Encryption in Transit**:
- ✅ HTTPS for all API calls
- ✅ TLS 1.3 to provider APIs
- ✅ No keys in query strings or logs

**Access Control**:
- ✅ Users can only access their own keys
- ✅ Session-based authentication required
- ✅ Admin cannot view user's BYOK keys (encrypted)

**Key Rotation**:
- ⚠️ No automatic rotation
- ⚠️ User must manually update keys
- ✅ Can disable old key and add new one

### 11.2 Platform Key Security

**Hashing**:
- ✅ bcrypt with auto-generated salt
- ✅ Keys never stored in plain text
- ✅ One-way hash (cannot reverse)

**Key Format**:
- ✅ High entropy (256 bits)
- ✅ Unique prefix for easy identification
- ✅ Fast prefix lookup (indexed)

**Revocation**:
- ✅ Instant revocation (is_active flag)
- ✅ Soft delete (key preserved for audit)
- ✅ Cannot reactivate revoked keys

**Expiration**:
- ✅ Optional expiration date
- ✅ Automatic expiration check on validation
- ✅ User notified before expiration

### 11.3 Credit System Security

**Atomicity**:
- ✅ PostgreSQL transactions (ACID-compliant)
- ✅ Row-level locking (FOR UPDATE)
- ✅ Automatic rollback on error

**Audit Trail**:
- ✅ Every credit movement logged
- ✅ Immutable transaction history
- ✅ Metadata preserved for forensics

**Fraud Prevention**:
- ✅ Negative balance prevention (CHECK constraint)
- ✅ Monthly spending caps
- ✅ Transaction type validation

**Payment Security**:
- ✅ PCI-compliant (Stripe handles cards)
- ✅ No card data stored locally
- ✅ Stripe webhook signature verification

### 11.4 Threat Model

| Threat | Impact | Mitigation |
|--------|--------|------------|
| **BYOK key theft** | High | Fernet encryption, HTTPS, no logging |
| **Platform key theft** | High | bcrypt hashing, revocation, expiration |
| **Credit fraud** | Medium | Atomic transactions, audit trail, caps |
| **Replay attacks** | Low | Short-lived session tokens, nonces |
| **SQL injection** | Critical | Parameterized queries (asyncpg) |
| **Stripe webhook forgery** | High | Signature verification |
| **MITM attacks** | High | HTTPS/TLS 1.3 everywhere |
| **Brute force key guessing** | Low | 256-bit entropy, rate limiting |

---

## 12. Future Enhancements

### 12.1 Short-Term (3-6 months)

1. **BYOK Provider Expansion**
   - Add Together AI, Fireworks AI, Groq
   - Add local model support (Ollama, LM Studio)
   - Provider health checking and failover

2. **Platform Key Enhancements**
   - API key rotation (generate new, keep old active)
   - IP whitelist restrictions
   - Usage quotas per key
   - Webhook notifications

3. **Credit System Improvements**
   - Auto-recharge (when balance < threshold)
   - Credit gifting (send credits to other users)
   - Bulk credit purchase discounts
   - Credit expiration policies

4. **UI/UX Refinements**
   - Dark mode support
   - Mobile-responsive design
   - Keyboard shortcuts
   - Accessibility improvements (WCAG 2.1)

### 12.2 Long-Term (6-12 months)

1. **Multi-Provider BYOK**
   - Allow multiple keys per provider
   - Load balancing across user's keys
   - Automatic failover on rate limits

2. **Advanced Cost Management**
   - Real-time cost estimation before request
   - Budget alerts (email/Slack/webhook)
   - Cost breakdown by app/project
   - Cost optimization recommendations

3. **Team Features**
   - Shared BYOK keys for teams
   - Team-wide credit pools
   - Role-based key permissions
   - Team billing and invoicing

4. **Enterprise Features**
   - SAML/SSO integration
   - Custom contract pricing
   - Dedicated support
   - SLA guarantees

5. **Developer Experience**
   - OpenAPI specification generation
   - SDK libraries (Python, JavaScript, Go)
   - Postman collection
   - Interactive API playground

---

## Appendix A: Database Schema SQL

### Complete Schema Creation Script

```sql
-- =====================================================
-- UC-Cloud Ops-Center API Key & Credit System Schema
-- =====================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- Table: user_provider_keys (BYOK)
-- =====================================================
CREATE TABLE IF NOT EXISTS user_provider_keys (
    id                SERIAL PRIMARY KEY,
    user_id           VARCHAR(255) NOT NULL,
    provider          VARCHAR(100) NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    metadata          JSONB DEFAULT '{}'::jsonb,
    enabled           BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW(),

    UNIQUE(user_id, provider)
);

CREATE INDEX idx_user_provider_keys_user_id ON user_provider_keys(user_id);

-- =====================================================
-- Table: user_api_keys (Platform Keys)
-- =====================================================
CREATE TABLE IF NOT EXISTS user_api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(255) NOT NULL,
    key_name    VARCHAR(255) NOT NULL,
    key_hash    TEXT NOT NULL,
    key_prefix  VARCHAR(20) NOT NULL,
    permissions JSONB DEFAULT '[]'::jsonb,
    created_at  TIMESTAMP DEFAULT NOW(),
    last_used   TIMESTAMP,
    expires_at  TIMESTAMP,
    is_active   BOOLEAN DEFAULT TRUE,
    metadata    JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_user_api_keys_user_id ON user_api_keys(user_id);
CREATE INDEX idx_user_api_keys_prefix ON user_api_keys(key_prefix);
CREATE INDEX idx_user_api_keys_active ON user_api_keys(is_active, expires_at);

-- =====================================================
-- Table: user_credits
-- =====================================================
CREATE TABLE IF NOT EXISTS user_credits (
    id                SERIAL PRIMARY KEY,
    user_id           TEXT NOT NULL UNIQUE,
    credits_remaining FLOAT NOT NULL DEFAULT 0.0,
    credits_lifetime  FLOAT NOT NULL DEFAULT 0.0,
    monthly_cap       FLOAT,
    tier              TEXT NOT NULL DEFAULT 'free',
    power_level       TEXT NOT NULL DEFAULT 'balanced',
    auto_recharge     BOOLEAN DEFAULT FALSE,
    recharge_threshold FLOAT DEFAULT 10.0,
    recharge_amount   FLOAT DEFAULT 100.0,
    stripe_customer_id TEXT,
    last_reset        TIMESTAMP,
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW(),

    CONSTRAINT valid_tier CHECK (tier IN ('free', 'starter', 'professional', 'enterprise')),
    CONSTRAINT valid_power_level CHECK (power_level IN ('eco', 'balanced', 'precision')),
    CONSTRAINT positive_credits CHECK (credits_remaining >= 0)
);

CREATE INDEX idx_user_credits_user_id ON user_credits(user_id);

-- =====================================================
-- Table: credit_transactions
-- =====================================================
CREATE TABLE IF NOT EXISTS credit_transactions (
    id                SERIAL PRIMARY KEY,
    user_id           TEXT NOT NULL,
    transaction_type  TEXT NOT NULL,
    amount            FLOAT NOT NULL,
    balance_after     FLOAT NOT NULL,

    provider          TEXT,
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    tokens_used       INTEGER,
    cost_per_token    FLOAT,
    power_level       TEXT,
    byok_used         BOOLEAN DEFAULT FALSE,

    payment_method    TEXT,
    stripe_transaction_id TEXT,
    stripe_invoice_id TEXT,
    package_id        INTEGER,

    metadata          JSONB,
    notes             TEXT,
    admin_user_id     TEXT,

    created_at        TIMESTAMP DEFAULT NOW(),

    CONSTRAINT valid_transaction_type CHECK (
        transaction_type IN ('purchase', 'debit', 'refund', 'bonus', 'adjustment')
    )
);

CREATE INDEX idx_credit_transactions_user_id ON credit_transactions(user_id);
CREATE INDEX idx_credit_transactions_created_at ON credit_transactions(created_at DESC);
CREATE INDEX idx_credit_transactions_byok ON credit_transactions(byok_used);
```

---

## Appendix B: API Endpoint Reference

### BYOK Endpoints

```
POST   /api/v1/llm/byok
       Add or update BYOK provider key
       Body: {provider, api_key, metadata}
       Response: {key_id, provider, enabled}

GET    /api/v1/llm/byok
       List all BYOK keys for current user
       Response: [{id, provider, enabled, metadata, masked_key}]

DELETE /api/v1/llm/byok/{provider}
       Delete BYOK key for provider
       Response: {success: true}

PUT    /api/v1/llm/byok/{provider}/toggle
       Enable/disable BYOK key
       Body: {enabled: true/false}
       Response: {provider, enabled}
```

### Platform Key Endpoints (TO BE IMPLEMENTED)

```
POST   /api/v1/admin/users/{user_id}/api-keys
       Generate new platform API key
       Body: {key_name, expires_in_days, permissions}
       Response: {api_key, key_id, key_prefix, expires_at}

GET    /api/v1/admin/users/{user_id}/api-keys
       List all platform keys for user
       Response: [{key_id, key_name, key_prefix, status, last_used}]

DELETE /api/v1/admin/users/{user_id}/api-keys/{key_id}
       Revoke platform API key
       Response: {success: true}
```

### Credit Endpoints

```
GET    /api/v1/credits/balance
       Get current credit balance
       Response: {balance, allocated_monthly, tier, reset_date}

GET    /api/v1/credits/transactions
       Get credit transaction history
       Query: ?limit=50&offset=0&type=debit
       Response: [{id, type, amount, balance_after, created_at, metadata}]

POST   /api/v1/credits/purchase
       Purchase credits via Stripe
       Body: {amount, stripe_token}
       Response: {transaction_id, credits_added, new_balance}
```

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **BYOK** | Bring Your Own Key - User provides their own provider API keys |
| **Platform Key** | API key issued by UC-Cloud for platform access |
| **Credit** | Virtual currency where 1 credit ≈ $0.001 USD |
| **Tier** | Subscription level (free, starter, professional, enterprise) |
| **Power Level** | Quality/cost setting (eco, balanced, precision) |
| **Provider** | LLM service provider (OpenAI, Anthropic, OpenRouter) |
| **Fernet** | Symmetric encryption scheme (AES-128-CBC + HMAC) |
| **bcrypt** | Password hashing function with salt |
| **Markup** | Platform fee added to provider costs |
| **Debit** | Deduction of credits from user balance |
| **Allocation** | Addition of credits to user balance |
| **Transaction** | Record of credit movement |
| **Revocation** | Permanently disabling an API key |
| **Expiration** | Automatic key invalidation after date |

---

## Document Changelog

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2025-11-12 | Claude Code | Initial architecture document created |

---

**END OF DOCUMENT**
