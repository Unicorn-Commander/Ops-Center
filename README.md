# 🦄 Ops-Center - UC-Cloud Command & Control

<div align="center">

![Version](https://img.shields.io/badge/version-3.12.0-blue.svg)
![Status](https://img.shields.io/badge/status-production-green.svg)
![License](https://img.shields.io/badge/license-MIT-purple.svg)
![Python](https://img.shields.io/badge/python-3.10+-yellow.svg)
![React](https://img.shields.io/badge/react-18-61dafb.svg)
![Inference](https://img.shields.io/badge/inference-local--first-ff69b4.svg)
![Fallback](https://img.shields.io/badge/failover-local→local→cloud-orange.svg)
![Security](https://img.shields.io/badge/security-zero--trust-red.svg)

**Run your own AI cloud.** Ops-Center is the command deck for a **local-first, federated inference mesh** — your GPUs do the work, a single public gateway fronts it with **automatic local→local→cloud failover**, and every token is **authenticated, metered, and billed** across your entire app suite. One pane of glass for users, orgs, subscriptions, models, billing, and the multi-node GPU fabric underneath.

[Why it's different](#-what-makes-it-different) • [Features](#-key-features) • [The Gateway](#-the-smart-inference-gateway) • [Quick Start](#-quick-start) • [API](#-api-reference)

</div>

---

## 🎯 What is Ops-Center?

Ops-Center is the **centralized management dashboard** for the UC-Cloud ecosystem - your single pane of glass for managing users, organizations, subscriptions, LLM infrastructure, and federated AI services across your entire platform.

**Think of it like:**
- 🏢 **AWS Console** - Infrastructure management at scale
- 👥 **Auth0 Dashboard** - Complete user and authentication control
- 💰 **Stripe Dashboard** - Subscription and billing management
- 🤖 **LiteLLM Proxy** - Multi-provider LLM orchestration
- 🌐 **Kubernetes Federation** - Multi-node inference mesh with cloud GPU bursting
- 📊 **Grafana** - Real-time analytics and monitoring

**All in one beautiful, unified interface with zero-trust security.**

---

## 🔥 What Makes It Different

Most "LLM gateways" are a thin proxy in front of someone else's cloud. Ops-Center is the opposite — **you are the cloud.**

- **🏠 Local-first economics.** Inference runs on *your* GPUs (marginal cost ≈ electricity). 3rd-party APIs (DeepSeek, OpenAI, OpenRouter) are **invisible insurance**, not the product — customers only ever touch them when your hardware is overwhelmed or down, and only within their plan's allowance. The margin lives on your own iron.
- **🛟 Failover nobody else has.** One model alias, four rungs: **local GPU-A → local GPU-B → cheap cloud → premium cloud.** A box dies mid-request and the caller never notices. (Verified: kill the primary, the response still lands.)
- **🔌 One ingress, one key, every modality.** Chat, embeddings, reranking, and STT/TTS all ride a single public, key-authed, OpenAI-compatible endpoint — metered to Lago, gated by budget, no VPN or raw GPU ports exposed.
- **🧩 Built for a whole app suite.** Per-org keys, per-app metering, and a unified credit/billing rail designed so one subscription's allowance can span Meeting-Ops, Center-Deep, Brigade, and the rest.
- **🔐 Zero-trust by construction.** Headscale/WireGuard mesh, per-node signed JWTs, per-service ACLs, CSRF + budget gates, full audit trail. The gateway is the *only* tailnet boundary-crosser; backends stay private.

> **The pitch in one line:** the cost structure of self-hosting, the reliability of a managed cloud, and the billing of a SaaS — fused.

---

## ⚡ Key Features

### 👥 User Management
- **Advanced Filtering**: 10+ filter options (tier, role, status, org, date ranges)
- **Bulk Operations**: CSV import/export, bulk role assignment, bulk actions
- **User Detail Pages**: 6-tab comprehensive profile view with charts
- **Role Management**: Visual permission matrix with hierarchical roles
- **API Key Management**: Full CRUD for user API keys with bcrypt hashing
- **User Impersonation**: Admin "login as user" feature with 24hr sessions
- **Activity Timeline**: Color-coded audit log with expandable details

### 💰 Billing & Subscriptions
- **4 Subscription Tiers**: Trial ($1/week), Starter ($19/mo), Professional ($49/mo), Enterprise ($99/mo)
- **Usage Tracking**: Real-time API call tracking with quota management
- **Stripe Integration**: Payment processing, invoices, webhooks
- **Lago Billing**: Advanced metering, usage-based billing
- **Self-Service**: Users can upgrade/downgrade/cancel their plans
- **Payment Methods**: Manage cards, billing address, upcoming invoices

### 🏢 Organization Management
- **Multi-Tenancy**: Organizations with team management
- **Role-Based Access**: Custom roles and permissions per organization
- **Team Collaboration**: Invite members, manage roles, audit trails
- **Resource Quotas**: Per-organization limits (API calls, storage, seats)
- **Billing**: Organization-level subscription and payment management

### 🤖 LLM Management
- **100+ Models**: OpenAI, Anthropic, Google, Meta, and more via LiteLLM
- **BYOK Support**: Bring Your Own Key - use your API keys, no platform markup
- **Credit System**: Usage-based billing with automatic credit tracking
- **Model Catalog**: Curated lists per app (Bolt.diy, Presenton, Open-WebUI)
- **Image Generation**: DALL-E, Stable Diffusion, Imagen support
- **Provider Routing**: Smart routing to cheapest/fastest providers

### 🎨 Apps Marketplace
- **Dynamic Tier-Based Access**: Apps appear/disappear based on subscription tier
- **12 Integrated Services**: Chat, Search, TTS, STT, Git, Brigade, Bolt, Presentations, Email Marketing, Social Media, Analytics, Partner Management
- **Single Sign-On**: Keycloak SSO across all apps
- **Feature Management**: Admin control over which tiers get which apps

### 🎖️ The Colonel - AI Server Management
- **Claude Code-Caliber AI**: GPU-accelerated AI agent for server management via chat
- **18 Built-in Skills**: Docker, system status, GPU monitoring, Traefik, PostgreSQL, backups, file ops, git, bash, and more
- **Brigade Delegation**: Seamlessly delegate to 17 specialist agents (finance, legal, research, coding, DevOps, data science)
- **SKILL.md Format**: Extensible skill system with YAML-defined tools
- **WebSocket Streaming**: Real-time streaming responses with tool execution visibility
- **Persistent Sessions**: PostgreSQL-backed sessions with Redis caching

### 🌐 Federation Inference Mesh
- **4-Node WireGuard Mesh**: Encrypted peer-to-peer mesh via Headscale/Tailscale (`unicorncommander.net` MagicDNS)
- **13 Services Auto-Discovered**: LLM (30 models), embeddings, reranker, search (4 tools), extraction, image/music gen, agents
- **3 Federated Nodes**: Home GPU server (magicunicorn), VPS gateway (commander), Search server (centerdeep) + Mac Studio
- **Service Auto-Discovery**: Per-deployment profiles (`home`, `vps`, `centerdeep`, `custom`) with Docker health checks every 30s
- **Smart Routing**: Tier-aware, constraint-based routing to the best available inference backend
- **Cloud GPU Bursting**: On-demand Lambda Labs GPU provisioning with auto-shutdown on idle
- **Zero Trust Security**: WireGuard encryption for internal traffic, per-node signed JWTs, per-service ACLs, circuit breakers
- **Brigade Agent Federation**: Cross-node agent discovery and delegation

### 📊 Analytics & Monitoring
- **Real-Time Dashboards**: User growth, API usage, revenue trends
- **Service Health**: Monitor all services in real-time
- **Usage Analytics**: API calls, credits consumed, costs per service
- **Audit Logs**: Complete activity tracking across all operations
- **Federation Audit**: Routing decision log with candidates, constraints, and scoring

---

## 🛰️ The Smart Inference Gateway

A single public, OpenAI-compatible endpoint (`llm.unicorncommander.ai`) fronts the entire GPU mesh. Consumers — your apps, the customer node, external products — hold **one per-org key** and call it like any AI provider. Behind it, the gateway authenticates, rate-limits, **meters every call to Lago**, and routes with automatic multi-tier failover.

```
   app / customer node / external          one key  ▸ Authorization: Bearer REMOVED…
                  │
       HTTPS :443 │  (Cloudflare → Traefik)
                  ▼
        ┌───────────────────────────────────────────────┐
        │  LiteLLM gateway  —  authn · RPM/TPM · Lago     │
        │  /v1/chat · /v1/embeddings · /v1/rerank · STT   │
        └───────────────┬───────────────────────────────┘
                        │   model: uc/chat-default
        ┌───────────────┴───────────────────────────────────────────┐
        ▼                ▼                 ▼                ▼
   ① local 3090     ② local P40       ③ DeepSeek V4     ④ OpenRouter
   (primary, free)  (redundancy, free) Flash (cheap)     (premium)
        └──────── automatic failover, left → right, caller never knows ────────┘

   Metering:  LLM + embeddings → ai_api_call (cost × plan)   |   STT/TTS → unit metrics
   Gating:    per-org key max_budget — local is $0 (unlimited), cloud counts against the allowance
```

**Why this matters:** rungs ① and ② are *your* GPUs — free and fast. Only a full local outage spills to ③/④, and even then a free-tier org is **fail-closed** (local-only) while paid orgs draw down their bundled cloud allowance. You get managed-cloud reliability on self-hosted economics, billed like a SaaS.

| Capability | How |
|---|---|
| **Local→local→cloud failover** | LiteLLM model-group + ordered `fallbacks` (verified live) |
| **Per-org metering** | `success_callback: [lago]`, `external_subscription_id = org_id` |
| **Budget gating** | per-key `max_budget`; local = $0 so it never depletes, cloud does |
| **Non-LLM compute** | STT/TTS report unit metrics (audio-seconds / characters) via a service-key bridge — audio never transits the gateway |
| **Cloud-GPU burst** | Lambda Labs auto-provision + idle-shutdown for sustained overflow (privacy-preserving — your models on rented iron) |

---

## 🚀 Quick Start

### Prerequisites

- **Docker** & **Docker Compose**
- **PostgreSQL** (shared database)
- **Redis** (shared cache)
- **Keycloak** (SSO authentication)
- **Node.js 20+** (for frontend development)
- **Python 3.10+** (for backend development)

### 1. Clone the Repository

```bash
git clone https://git.unicorncommander.ai/UnicornCommander/Ops-Center.git
cd Ops-Center
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env.auth

# Edit configuration
vim .env.auth
```

**Key Variables**:
```bash
# Keycloak SSO
KEYCLOAK_URL=http://uchub-keycloak:8080
KEYCLOAK_REALM=uchub
KEYCLOAK_CLIENT_ID=ops-center
KEYCLOAK_CLIENT_SECRET=<your-secret>

# Database
POSTGRES_HOST=unicorn-postgresql
POSTGRES_DB=unicorn_db

# Billing
LAGO_API_KEY=<your-lago-key>
STRIPE_SECRET_KEY=<your-stripe-key>

# Billing Mode (Optional)
BILLING_ENABLED=true                    # Set "false" to disable all billing
CREDIT_EXEMPT_TIERS=free,admin,internal # Tiers exempt from charges (or "*" for all)
```

> **Tip**: For personal or internal servers, set `BILLING_ENABLED=false` to skip all credit checks.

### 3. Start the Services

```bash
# Start with Docker Compose
docker compose -f docker-compose.direct.yml up -d

# Check status
docker ps | grep ops-center
```

### 4. Access the Dashboard

```bash
# Local development
http://localhost:8084

# Production
https://unicorncommander.ai
```

**Default Admin**: Navigate to Keycloak and create your first admin user

---

## 📁 Project Structure

```
ops-center/
├── backend/                      # FastAPI backend
│   ├── server.py                 # Main application
│   ├── colonel/                  # The Colonel AI agent system
│   │   ├── skill_executor.py     # 67 tool executors (Docker, git, Brigade, etc.)
│   │   ├── skill_loader.py       # SKILL.md parser → OpenAI tool definitions
│   │   ├── models.py             # Session, config, WebSocket frame models
│   │   └── skills/               # 18 skill definitions (.skill.md files)
│   ├── federation/               # Federation inference mesh
│   │   ├── node_registry.py      # Peer node registration & heartbeat
│   │   ├── inference_router.py   # Tier-aware, constraint-based routing
│   │   ├── hardware_detector.py  # Auto-detect GPUs & services
│   │   ├── cloud_provisioner.py  # Lambda Labs GPU provisioning
│   │   ├── pipeline_engine.py    # Multi-step inference pipelines
│   │   ├── auth.py               # Per-node signed JWTs (v3.1)
│   │   ├── resilience.py         # Circuit breakers & audit log (v3.1)
│   │   └── access_control.py     # Per-service ACL (v3.1)
│   ├── routers/federation.py     # 20+ federation API endpoints
│   ├── user_management_api.py    # User CRUD + bulk ops
│   ├── billing_analytics_api.py  # Billing & subscriptions
│   ├── org_api.py                # Organization management
│   ├── litellm_api.py            # LLM proxy + credit system
│   ├── my_apps_api.py            # Tier-based app access
│   ├── model_list_api.py         # Model catalog management
│   ├── landing_page_settings_api.py  # Landing page config
│   ├── pricing_packages_api.py   # Public pricing API
│   ├── keycloak_integration.py   # SSO integration
│   ├── lago_integration.py       # Billing system
│   └── dependencies.py           # Dependency injection
│
├── src/                          # React frontend
│   ├── App.jsx                   # Main app + routing
│   ├── pages/
│   │   ├── Dashboard.jsx         # Main dashboard
│   │   ├── UserManagement.jsx    # User list + filters
│   │   ├── UserDetail.jsx        # User profile (6 tabs)
│   │   ├── AppsMarketplace.jsx   # Tier-based apps
│   │   ├── BillingDashboard.jsx  # Admin billing
│   │   ├── admin/
│   │   │   ├── ModelListManagement.jsx  # Model catalogs
│   │   │   └── FeatureManagement.jsx    # Feature flags
│   │   ├── subscription/         # User subscription pages
│   │   └── organization/         # Org management pages
│   ├── components/               # Reusable components
│   └── contexts/                 # React contexts
│
├── public/                       # Static assets + built files
├── docker-compose.direct.yml     # Docker configuration
├── package.json                  # Frontend dependencies
├── requirements.txt              # Backend dependencies
└── CLAUDE.md                     # Complete documentation
```

---

## 🛠️ Technology Stack

### Backend
- **Framework**: FastAPI (async Python)
- **Database**: PostgreSQL + asyncpg
- **Cache**: Redis
- **Authentication**: Keycloak SSO (OpenID Connect)
- **Billing**: Lago + Stripe
- **LLM Proxy**: LiteLLM (100+ models)

### Frontend
- **Framework**: React 18
- **Build Tool**: Vite
- **UI Library**: Material-UI (MUI v5)
- **Routing**: React Router v6
- **State**: React Context API
- **Charts**: Chart.js + react-chartjs-2
- **HTTP**: Axios

### Infrastructure
- **Containers**: Docker + Docker Compose
- **Reverse Proxy**: Traefik (SSL/TLS)
- **Networks**: Multi-network architecture
- **Orchestration**: Docker Compose
- **Federation**: 4-node WireGuard mesh via Headscale with 13 auto-discovered services
- **Cloud GPU**: Auto-provisioning with persistent S3 model cache and idle auto-shutdown
- **Mesh Network**: Headscale coordination at `headscale.unicorncommander.ai`, MagicDNS via `unicorncommander.net`

---

## 🎨 Screenshots

### Admin Dashboard — infrastructure at a glance
GPU status, service health, hosted sites, billing, and the federation mesh in one view.

![Admin Dashboard](public/logos/Admin-Dashboard.png)

### AI Model Management — the whole catalog + gateway
Curate models, route providers, and manage the inference gateway.

![AI Model Management](public/logos/AI-Model-Management.png)

### Service Management & System Monitoring

| Services | Monitoring |
|---|---|
| ![Service Management](public/logos/Service%20Management.png) | ![System Monitoring](public/logos/System%20Monitoring.png) |

### User Dashboard — credits, usage, plan
Per-user view of allowance, spend, models used, and quick actions.

![User Dashboard](public/logos/User%20Dashboard-Homepage.png)

> _Screenshots reflect recent builds; the daylight theme + gateway/billing surfaces are continually refreshed._

---

## 📚 Documentation

### For Users
- **[Quick Start Guide](docs/QUICK_START.md)** - Get up and running in 5 minutes
- **[User Guide](docs/USER_GUIDE.md)** - Complete feature walkthrough
- **[FAQ](docs/FAQ.md)** - Common questions and answers

### For Developers
- **CLAUDE.md** - Complete technical documentation (production context)
- **[API Reference](docs/API_REFERENCE.md)** - REST API endpoints
- **[Development Guide](docs/DEVELOPMENT.md)** - Local development setup
- **[Architecture](docs/ARCHITECTURE.md)** - System design and architecture

### For Admins
- **[Admin Guide](docs/ADMIN_OPERATIONS_HANDBOOK.md)** - Administrative operations
- **[Deployment Guide](docs/DEPLOYMENT.md)** - Production deployment
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions

---

## 🔌 API Reference

### Base URL
```
https://unicorncommander.ai/api/v1
http://localhost:8084/api/v1  # Local development
```

### Authentication
All admin endpoints require Keycloak SSO authentication via session cookies or Bearer tokens. Federation endpoints use per-node HMAC-SHA256 signed JWTs.

### Key Endpoints

#### User Management
```bash
GET    /admin/users                    # List users (with filters)
GET    /admin/users/{id}               # Get user details
POST   /admin/users/comprehensive      # Create user
PUT    /admin/users/{id}               # Update user
DELETE /admin/users/{id}               # Delete user
POST   /admin/users/bulk/import        # Import CSV
GET    /admin/users/export             # Export CSV
```

#### Organization Management
```bash
GET    /organizations                  # List organizations
POST   /organizations                  # Create organization
GET    /organizations/{id}             # Get organization
PUT    /organizations/{id}             # Update organization
GET    /organizations/{id}/members     # List members
POST   /organizations/{id}/invite      # Invite member
```

#### LLM & Credits
```bash
POST   /llm/chat/completions           # Chat completion (OpenAI-compatible)
POST   /llm/image/generations          # Image generation (DALL-E, SD)
GET    /llm/models                     # List available models
GET    /llm/models/categorized         # Models by BYOK vs Platform
GET    /llm/usage                      # Usage statistics
```

#### Billing & Subscriptions
```bash
GET    /billing/plans                  # List subscription plans
GET    /billing/subscriptions/current  # Current subscription
POST   /billing/subscriptions/create   # Create subscription
POST   /billing/subscriptions/upgrade  # Upgrade tier
POST   /billing/subscriptions/cancel   # Cancel subscription
GET    /billing/invoices               # Invoice history
```

#### Apps Marketplace
```bash
GET    /my-apps/authorized             # Apps user can access (tier-filtered)
GET    /my-apps/marketplace            # Apps available for purchase
```

#### Federation Mesh
```bash
GET    /federation/health              # Public health check (no auth)
POST   /federation/register            # Node self-registration
POST   /federation/heartbeat           # Node heartbeat with load/capacity
GET    /federation/nodes               # List all federated nodes
GET    /federation/services            # Unified service catalog
GET    /federation/topology            # Federation map
POST   /federation/route               # Find best inference backend
POST   /federation/pipelines/execute   # Execute multi-step workflow
GET    /federation/agents              # Cross-node agent discovery
GET    /federation/audit               # Routing decision audit log (admin)
GET    /federation/circuits            # Circuit breaker status (admin)
POST   /federation/cloud/provision     # Provision cloud GPU on demand
```

**Complete API documentation**: [docs/API_REFERENCE.md](docs/API_REFERENCE.md)

---

## 🧪 Development

### Local Development Setup

```bash
# Install frontend dependencies
npm install

# Install backend dependencies
pip install -r backend/requirements.txt

# Start development server (frontend)
npm run dev  # http://localhost:5173

# Start backend (via Docker)
docker compose -f docker-compose.direct.yml up -d

# Watch logs
docker logs ops-center-direct -f
```

### Build Frontend

```bash
# Production build
npm run build

# Deploy to public/
cp -r dist/* public/

# Restart backend to serve new files
docker restart ops-center-direct
```

### Run Tests

```bash
# Backend tests (if available)
cd backend && pytest

# Frontend tests
npm test

# E2E tests
npm run test:e2e
```

### Code Quality

```bash
# Frontend linting
npm run lint

# Backend linting
ruff check backend/

# Type checking
mypy backend/
```

---

## 🌟 Recent Updates

### v3.11.0 (June 2026) — Public Inference Gateway, Smart Failover & Metered Billing
- **Public, key-authed gateway** for the whole GPU mesh: chat + **embeddings + reranking** now ride one OpenAI-compatible endpoint, authed per-org and metered to Lago.
- **4-tier automatic failover**: `local 3090 → local P40 → DeepSeek V4 Flash → OpenRouter` under a single model alias — verified live (kill the primary, the response still lands).
- **Direct providers wired**: DeepSeek V4 (flash/pro) + OpenAI, keys in secure env (never the committed config).
- **Usage-based pricing across every modality** (LLM / embeddings / rerank / STT / TTS), with per-tier **budget gating** — free = local-only fail-closed, paid = bundled cloud allowance.
- **Non-LLM metering bridge**: STT/TTS report unit metrics (audio-seconds / characters) without audio ever transiting the gateway.
- **Account assistant ("The Guide")** gained confirm-gated API-key lifecycle (create/revoke/rotate); **notification preferences** rebuilt with real persistence.

### v3.3.0 (March 22, 2026) - Mesh Network + Service Auto-Discovery
- **4-Node WireGuard Mesh**: Encrypted peer-to-peer mesh via Headscale/Tailscale with MagicDNS (`unicorncommander.net`)
- **13 Services Auto-Discovered**: Docker health-check-based discovery across 3 federated nodes
- **Per-Deployment Profiles**: `FEDERATION_SERVICE_PROFILE` env var (home, vps, centerdeep, custom) for multi-site compose
- **New Service Types**: `search` (CenterDeep tools) and `extraction` (Granite, Tika)
- **Compose Parameterization**: `${VAR:-default}` substitution — git pulls no longer clobber deployment config
- **Infrastructure**: `join-federation-network.sh`, Docker log rotation, Forgejo Actions CI runner

### v3.1.0 (March 21, 2026) - Zero Trust Security + Resilience
- **Per-Node Signed JWTs**: HMAC-SHA256 tokens with replay prevention replace shared API keys for federation auth
- **Circuit Breakers**: Per-peer failure isolation prevents cascading failures across the federation mesh
- **Per-Service ACLs**: Tier-based access control per inference service type (e.g., trial users blocked from music/image gen)
- **Routing Audit Trail**: Every federation routing decision logged to PostgreSQL with full scoring details
- **Brigade Agent Federation**: Cross-node agent discovery via `GET /federation/agents`
- **Distributed Locking**: Redis-based locks prevent duplicate cloud GPU provisioning

### v3.0.0 (March 21, 2026) - Federation Inference Mesh
- **Peer-to-Peer Mesh**: ~9,000 lines across 29 files — federated inference across home servers, cloud GPUs, and API providers
- **Smart Routing**: Tier-aware, constraint-based routing to the best available inference backend
- **Cloud GPU Bursting**: Lambda Labs auto-provisioning with idle shutdown and persistent S3 model cache
- **4 Admin Pages**: Federation settings, node management, visual topology, unified service catalog
- **Multi-Step Pipelines**: Chain inference steps across nodes (e.g., music generation + artwork)
- **No single competing platform** covers all 8 requirements (heterogeneous hardware, multi-modal, hybrid cloud routing, idle GPU management, federated auth, billing, service discovery, multi-instance)

### v2.5.2 (February 27, 2026) - Colonel + Brigade A2A
- **Colonel → Brigade Delegation**: One-way A2A delegation to 17 specialist agents for research, coding, finance, legal, medical, and more

### v2.5.0 (January 31, 2026) - Org Features + User Dashboard
- Organization-level feature grants, user dashboard, service API keys management, configurable billing

**[Complete Changelog](CHANGELOG.md)**

---

## 🤝 Integration

### UC-Cloud Ecosystem

Ops-Center integrates seamlessly with the entire UC-Cloud platform:

- **🎖️ Unicorn Brigade** - AI agent platform (17 production agents) — Colonel delegates tasks via A2A
- **💬 Open-WebUI** - AI chat interface
- **🔍 Center-Deep** - AI metasearch engine (70+ search engines)
- **🎤 Unicorn Orator** - Professional TTS service
- **🎧 Unicorn Amanuensis** - Professional STT service
- **⚡ Bolt.diy** - AI development environment
- **📊 Presenton** - AI presentation generation
- **🔐 Keycloak** - Enterprise SSO (uchub realm)
- **💳 Lago + Stripe** - Advanced billing system
- **🐙 Forgejo** - Self-hosted Git server
- **📧 Listmonk** - Email marketing platform
- **📱 Postiz** - Social media scheduling

All services share:
- ✅ Single Sign-On (Keycloak)
- ✅ Unified billing (Lago + Stripe)
- ✅ Centralized LLM routing
- ✅ Cross-service authentication
- ✅ Shared database and cache

---

## 🔒 Security — Zero Trust / Defense-in-Depth

- **🔐 SSO Authentication**: Keycloak with Google, GitHub, Microsoft providers
- **🔑 API Key Management**: Bcrypt hashing, secure storage
- **👮 Role-Based Access**: 5-tier role hierarchy (admin → viewer) + per-service ACLs
- **📝 Audit Logging**: Complete activity tracking + federation routing audit trail
- **🛡️ Input Validation**: Pydantic models, SQL injection protection
- **🔒 HTTPS/TLS**: SSL certificates via Traefik
- **💰 PCI Compliance**: Stripe handles all card data
- **🌐 Federation Security**: Per-node HMAC-SHA256 signed JWTs with replay prevention (JTI + 60s expiry)
- **🔗 WireGuard Mesh**: All internal federation traffic encrypted via WireGuard tunnels (no Cloudflare for heartbeats)
- **🔄 Circuit Breakers**: Per-peer failure isolation (3 failures → 30s cooldown → half-open test)
- **🔐 Credential Encryption**: Fernet encryption for stored secrets, CSRF protection, rate limiting

---

## 📊 Performance

- **⚡ API Response Times**: 2-8ms average (38x faster than Stripe API)
- **💾 Database Queries**: <1ms execution time
- **🎯 Container Resources**: 0.66% memory, 0.20% CPU
- **📦 Bundle Size**: Frontend optimized for production
- **🚀 Zero Downtime**: Rolling deployments supported

---

## 🛠️ Troubleshooting

### Common Issues

**❓ Metrics showing 0**
```bash
# Populate Keycloak user attributes
docker exec ops-center-direct python3 /app/scripts/quick_populate_users.py
```

**❓ Build errors**
```bash
# Install dependencies
npm install

# Rebuild
npm run build && cp -r dist/* public/
```

**❓ API 401/403 errors**
```bash
# Check Keycloak
docker ps | grep keycloak

# Re-login via SSO
# https://unicorncommander.ai/auth/login
```

**❓ Database connection errors**
```bash
# Check PostgreSQL
docker ps | grep postgresql

# Test connection
docker exec unicorn-postgresql psql -U unicorn -d unicorn_db -c "SELECT 1;"
```

**[Complete Troubleshooting Guide](docs/TROUBLESHOOTING.md)**

---

## 📈 Roadmap

### Phase 2: Enhanced Analytics (Complete ✅)
- ✅ User growth charts and dashboards
- ✅ Usage tracking with API metering
- ✅ Revenue tracking via Lago + Stripe
- ✅ Organization-level feature grants
- ✅ User Dashboard with credit/usage overview

### Phase 3: Federation Inference Mesh (Complete ✅)
- ✅ Peer-to-peer federated inference across multiple servers
- ✅ Cloud GPU auto-provisioning (Lambda Labs)
- ✅ Zero trust security (signed JWTs, circuit breakers, ACLs)
- ✅ Full routing audit trail
- ✅ Brigade agent federation

### Phase 4: Advanced Organization Management (In Progress)
- 🏢 Team hierarchies and nested teams
- 🎭 Custom roles per organization
- 📦 Resource quotas and limits
- 🔐 Per-organization SSO providers

### Phase 5: Self-Service & Automation
- 🤖 Automated provisioning on signup
- 📈 Usage-based tier upgrades
- 💬 AI-powered chatbot support
- 📚 Built-in API documentation portal

**[Complete Roadmap](docs/ROADMAP.md)**

---

## 🧑‍💻 Contributing

We welcome contributions! Here's how to get started:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes** (follow our coding standards)
4. **Run tests**: `npm test && pytest`
5. **Commit**: `git commit -m 'feat: Add amazing feature'`
6. **Push**: `git push origin feature/amazing-feature`
7. **Open a Pull Request**

**[Contributing Guidelines](CONTRIBUTING.md)**

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

Copyright (c) 2025 Magic Unicorn Unconventional Technology & Stuff Inc

---

## 🙏 Acknowledgments

Built with ❤️ by the UC-Cloud team using:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [React](https://reactjs.org/) - UI library
- [Material-UI](https://mui.com/) - Component library
- [Keycloak](https://www.keycloak.org/) - Identity and access management
- [Lago](https://www.getlago.com/) - Open-source billing platform
- [LiteLLM](https://litellm.ai/) - LLM proxy and routing

---

## 📞 Support

- **📧 Email**: support@magicunicorn.tech
- **💬 Discord**: [Join our community](https://discord.gg/unicorn-commander)
- **🐛 Issues**: [GitHub Issues](https://git.unicorncommander.ai/UnicornCommander/Ops-Center/issues)
- **📚 Docs**: [Complete Documentation](https://docs.unicorncommander.ai)

---

<div align="center">

**⭐ Star us on GitHub** • **🐦 Follow on Twitter** • **💼 Connect on LinkedIn**

Made with 🦄 by [Magic Unicorn Tech](https://magicunicorn.tech)

</div>
