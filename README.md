# Ops-Center - UC-Cloud Management Dashboard

**The central management hub for the UC-Cloud ecosystem**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/react-%2320232a.svg?logo=react&logoColor=%2361DAFB)](https://reactjs.org/)

## Overview

Ops-Center is the **AWS Console equivalent** for UC-Cloud - a comprehensive administrative interface for managing users, billing, services, organizations, and LLM infrastructure.

**Primary URL**: https://unicorncommander.ai

## Features

### Core Capabilities
- 👥 **User Management** - Advanced filtering, bulk operations, role management, 6-tab detailed user profiles
- 💳 **Billing Integration** - Lago + Stripe subscription management with 4 tiers (Trial → Enterprise)
- 💰 **Credit System** - Usage-based billing with credit tracking and LLM cost management
- 🔑 **BYOK (Bring Your Own Key)** - Users can add their own OpenRouter, OpenAI, Anthropic API keys
- 🏢 **Organization Management** - Multi-tenant organization control with team hierarchies
- 🤖 **LLM Provider Management** - 100+ models via LiteLLM proxy with centralized cost tracking
- 🎨 **Image Generation** - DALL-E 2/3, Stable Diffusion XL/3 via OpenAI-compatible API
- 📦 **App Management** - Tier-based app assignment system (formerly "Feature Management")
- 🔐 **Keycloak SSO** - Google, GitHub, Microsoft authentication in uchub realm
- 📊 **Analytics Dashboard** - Real-time metrics, usage tracking, and activity timelines
- 🔧 **API Key Management** - User API key generation with bcrypt hashing
- 👤 **User Impersonation** - Admin "login as user" capability with 24hr sessions

### Recent Updates

#### November 17, 2025 - Billing Chain Integration ✅
**Status**: 🟢 PRODUCTION READY - All components operational

Complete integration of Lago billing system with LLM credit tracking:

- ✅ **Database-Driven Pricing**: Credit costs calculated from `subscription_tiers.llm_markup_percentage`
  - No more hardcoded tier markup values
  - Admins adjust pricing via database without code deployment
  - Current values: VIP Founder (0%), BYOK (10%), Managed (25%)

- ✅ **Lago Metering Events**: Automatic usage events sent to Lago after every credit deduction
  - Non-blocking design (failures don't block users)
  - Enables accurate month-end invoicing
  - Tracks org_id, model, tokens, cost, transaction_id

- ✅ **OpenRouter Pricing Integration**: 1,000+ models now have pricing data
  - Fixed authentication using correct `OPENROUTER_API_KEY`
  - Pricing available in `/api/v1/llm/models/categorized` endpoint
  - Display format: "5.5/11.0 credits per 1K tokens"

**Integration Benefits**:
- **For Users**: Transparent pricing, accurate billing, detailed invoices
- **For Admins**: Dynamic pricing, usage analytics, automated invoicing

**Documentation**: `/tmp/BILLING_CHAIN_FIX_COMPLETE.md` (1,500+ lines)

#### v2.3.0 - Feature → App Refactoring
- 🔄 **Feature → App Refactoring**: Renamed all "feature" terminology to "app" for clarity
  - Eliminates confusion between tier properties and user-facing applications
  - Backward-compatible views maintain old API endpoints during transition
  - Database: `app_definitions`, `tier_apps` (formerly `feature_definitions`, `tier_features`)
  - API: `/api/v1/admin/apps` (formerly `/api/v1/admin/features`)
  - UI: App Management page at `/admin/system/app-management`

### Technical Stack
- **Backend**: FastAPI (Python 3.10+)
- **Frontend**: React 18 + Vite + Material-UI
- **Authentication**: Keycloak (uchub realm)
- **Database**: PostgreSQL
- **Cache**: Redis
- **Billing**: Lago + Stripe
- **Deployment**: Docker + Traefik

## Quick Start

### As Part of UC-Cloud (Recommended)

Ops-Center is designed to work as part of the UC-Cloud ecosystem:

\`\`\`bash
# Clone UC-Cloud with submodules
git clone --recurse-submodules https://git.unicorncommander.ai/UnicornCommander/UC-Cloud.git
cd UC-Cloud

# Ops-Center will be at services/ops-center/
docker compose up -d

# Access at https://unicorncommander.ai (with Traefik SSL)
# Or http://localhost:8084 (direct access)
\`\`\`

### Standalone Deployment

\`\`\`bash
# Clone repository
git clone https://git.unicorncommander.ai/UnicornCommander/Ops-Center.git
cd Ops-Center

# Configure environment
cp .env.auth.template .env.auth
# Edit .env.auth with your settings

# Build and run
docker compose -f docker-compose.direct.yml up -d

# Access at http://localhost:8084
\`\`\`

## Configuration

See \`.env.auth.template\` for all configuration options.

**Key Variables**:
- \`KEYCLOAK_URL\` - Keycloak authentication server
- \`POSTGRES_HOST\` - PostgreSQL database
- \`REDIS_URL\` - Redis cache
- \`LAGO_API_KEY\` - Lago billing API key (optional)
- \`STRIPE_SECRET_KEY\` - Stripe payment processing (optional)

## Development

\`\`\`bash
# Install frontend dependencies
npm install

# Run frontend dev server
npm run dev  # Port 5173

# Run backend
cd backend
pip install -r requirements.txt
uvicorn server:app --reload --port 8084
\`\`\`

## Key Features in Detail

### BYOK (Bring Your Own Key) System

Users can add their own API keys for multiple LLM providers:
- **Supported Providers**: OpenRouter, OpenAI, Anthropic, Google AI, Cohere, Groq
- **Encrypted Storage**: Fernet encryption (256-bit) in PostgreSQL
- **Key Testing**: Built-in validation to test keys before use
- **Usage Tracking**: Monitor API usage per provider
- **Access**: `/admin/account/api-keys`

**What's Working** ✅:
- Add/remove API keys through intuitive GUI
- Automatic key encryption before database storage
- Test connection to verify key validity
- View all configured keys with masked previews
- Stats showing configured, tested, and valid providers

### Credit System

Usage-based billing with flexible credit allocation:
- **Credit Dashboard**: Real-time credit balance and usage tracking
- **Transaction History**: Detailed log of all credit operations
- **Tier-Based Credits**: Different credit allocations per subscription tier
- **LLM Cost Tracking**: Automatic deduction based on model usage
- **OpenRouter Integration**: Seamless API call routing with cost tracking
- **Access**: `/admin/credits` (Admin) or Dashboard stats (Users)

### User Management

Advanced user administration with enterprise-grade features:
- **Bulk Operations**: CSV import/export, bulk role changes, bulk suspend/delete
- **Advanced Filtering**: 10+ filters (tier, role, status, org, date ranges, BYOK status)
- **User Detail Page**: 6-tab comprehensive view (Overview, Activity, API Keys, Sessions, Permissions, Audit)
- **Role Management**: Visual permission matrix with hierarchical roles
- **Activity Timeline**: Color-coded audit log with expandable details
- **Impersonation**: Admin can "login as user" for troubleshooting

### Billing & Subscriptions

Complete subscription lifecycle management:
- **4 Subscription Tiers**: Trial ($1/week), Starter ($19/mo), Professional ($49/mo), Enterprise ($99/mo)
- **Stripe Integration**: Secure payment processing with webhook support
- **Lago Billing**: Advanced usage metering and invoice generation
- **Self-Service Portal**: Users can upgrade/downgrade their own plans
- **Invoice History**: Automatic invoice generation and payment tracking

## API Endpoints

### Public API (For Developers)

**Base URL**: `https://api.unicorncommander.ai`

**LLM Inference** (OpenAI-compatible):
```
POST https://api.unicorncommander.ai/v1/llm/chat/completions
GET  https://api.unicorncommander.ai/v1/llm/models
```

**Quick Start**:
```bash
curl -X POST https://api.unicorncommander.ai/v1/llm/chat/completions \
  -H "Authorization: Bearer REMOVED" \
  -H "Content-Type: application/json" \
  -d '{"model": "openai/gpt-4", "messages": [{"role": "user", "content": "Hello!"}]}'
```

📚 **Complete API Documentation**: See [`docs/API_INTEGRATION_GUIDE.md`](docs/API_INTEGRATION_GUIDE.md)

### Internal APIs

**BYOK API**:
```
GET  /api/v1/byok/keys              # List user's API keys
POST /api/v1/byok/keys/add          # Add new API key
POST /api/v1/byok/keys/test/{provider}  # Test API key
GET  /api/v1/byok/stats             # BYOK statistics
```

**Credit API**:
```
GET  /api/v1/credits/balance        # Get user credit balance
GET  /api/v1/credits/transactions   # Credit transaction history
POST /api/v1/credits/allocate       # Allocate credits (admin)
```

**User Management API**:
```
GET    /api/v1/admin/users                  # List users (with filtering)
POST   /api/v1/admin/users/comprehensive    # Create user
GET    /api/v1/admin/users/{id}             # Get user details
PUT    /api/v1/admin/users/{id}             # Update user
DELETE /api/v1/admin/users/{id}             # Delete user
POST   /api/v1/admin/users/bulk/import      # Bulk import from CSV
```

## Documentation

- **API Integration Guide**: See [`docs/API_INTEGRATION_GUIDE.md`](docs/API_INTEGRATION_GUIDE.md) - Complete API reference for developers
- **Complete Guide**: See \`CLAUDE.md\` for comprehensive documentation
- **Admin Guide**: \`ADMIN_QUICKSTART.md\` for admin operations
- **Billing Setup**: \`BILLING_QUICK_START.md\` for Lago + Stripe configuration
- **BYOK Documentation**: `/tmp/BYOK_FINAL_FIX.md` for BYOK system details
- **Credit System**: `/tmp/CREDIT_BALANCE_EXPLAINED.md` for credit management

## Architecture

Think of Ops-Center as your **infrastructure control panel**:

- **Ops-Center** = AWS Console (infrastructure management)
- **Brigade** = GitHub (agent repository)
- **Open-WebUI** = VS Code (where you work)
- **Center-Deep** = Google Search (research tool)

## License

MIT License - see LICENSE file for details

## Part of UC-Cloud

This repository is part of the larger **UC-Cloud ecosystem**. For the complete system, see:
https://git.unicorncommander.ai/UnicornCommander/UC-Cloud

### Git Repository

**Forgejo**: https://git.unicorncommander.ai/UnicornCommander/Ops-Center
**Issues**: https://git.unicorncommander.ai/UnicornCommander/Ops-Center/issues
**Pull Requests**: https://git.unicorncommander.ai/UnicornCommander/Ops-Center/pulls

---

**Magic Unicorn Unconventional Technology & Stuff Inc** | https://unicorncommander.ai
