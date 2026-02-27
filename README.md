# 🦄 Ops-Center - UC-Cloud Command & Control

<div align="center">

![Version](https://img.shields.io/badge/version-2.5.2-blue.svg)
![Status](https://img.shields.io/badge/status-production-green.svg)
![License](https://img.shields.io/badge/license-MIT-purple.svg)
![Python](https://img.shields.io/badge/python-3.10+-yellow.svg)
![React](https://img.shields.io/badge/react-18-61dafb.svg)

**The Central Hub for Managing Your Entire AI Infrastructure**

[Features](#-features) • [Quick Start](#-quick-start) • [Documentation](#-documentation) • [API Reference](#-api-reference)

</div>

---

## 🎯 What is Ops-Center?

Ops-Center is the **centralized management dashboard** for the UC-Cloud ecosystem - your single pane of glass for managing users, organizations, subscriptions, LLM infrastructure, and services across your entire AI platform.

**Think of it like:**
- 🏢 **AWS Console** - Infrastructure management at scale
- 👥 **Auth0 Dashboard** - Complete user and authentication control
- 💰 **Stripe Dashboard** - Subscription and billing management
- 🤖 **LiteLLM Proxy** - Multi-provider LLM orchestration
- 📊 **Grafana** - Real-time analytics and monitoring

**All in one beautiful, unified interface.**

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
- **8 Integrated Services**: Chat, Search, TTS, STT, Git, Brigade, Bolt, Presentations
- **Single Sign-On**: Keycloak SSO across all apps
- **Feature Management**: Admin control over which tiers get which apps

### 🎖️ The Colonel - AI Server Management
- **Claude Code-Caliber AI**: GPU-accelerated AI agent for server management via chat
- **18 Built-in Skills**: Docker, system status, GPU monitoring, Traefik, PostgreSQL, backups, file ops, git, bash, and more
- **Brigade Delegation**: Seamlessly delegate to 17 specialist agents (finance, legal, research, coding, DevOps, data science)
- **SKILL.md Format**: Extensible skill system with YAML-defined tools
- **WebSocket Streaming**: Real-time streaming responses with tool execution visibility
- **Persistent Sessions**: PostgreSQL-backed sessions with Redis caching

### 📊 Analytics & Monitoring
- **Real-Time Dashboards**: User growth, API usage, revenue trends
- **Service Health**: Monitor all services in real-time
- **Usage Analytics**: API calls, credits consumed, costs per service
- **Audit Logs**: Complete activity tracking across all operations

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
cd /home/muut/Production/UC-Cloud/services/ops-center
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

---

## 🎨 Screenshots

### Dashboard Overview
Beautiful, modern interface with real-time metrics and service status.

### User Management
Advanced filtering, bulk operations, and detailed user profiles.

### Apps Marketplace
Dynamic tier-based app access with single sign-on across all services.

### Billing Dashboard
Complete subscription management, usage tracking, and payment processing.

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
All admin endpoints require Keycloak SSO authentication via session cookies or Bearer tokens.

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

### v2.5.2 (February 27, 2026)
- **Colonel → Brigade Delegation**: One-way A2A delegation to 17 specialist agents for research, coding, finance, legal, medical, and more
- **Service-to-Service Auth**: Secure BRIGADE_ADMIN_KEY authentication between Colonel and Brigade
- **18 Skills Total**: brigade-delegation added to Colonel's skill repertoire

### v2.5.1 (February 22, 2026)
- **Frontend Quality Audit**: 108 files fixed - dead code removal, credentials sweep (232 fetch calls), monitoring persistence, SPA routing fixes
- **SSO Cookie Fix**: All API fetch calls now include `credentials: 'include'` for proper cross-domain authentication
- **Monitoring Persistence**: Umami, Grafana, and Prometheus config pages now save settings to localStorage
- **Dead Code Cleanup**: 3 unused files deleted, unused imports removed across 10 files

### v2.4.0 (November 29, 2025) - Image Generation + P0 Fixes

**Added**:
- ✨ OpenAI GPT Image 1 & Image 1 Mini models
- ✨ Google Gemini Imagen 3 & Gemini 2.5 Flash Image
- ✨ Ollama Cloud provider support
- ✨ OpenRouter image generation support
- 📊 Model categorization by BYOK vs Platform
- 🎨 Image category badges (pink #e91e63)

**Fixed**:
- 🐛 Image generation routing (DALL-E→OpenAI, Imagen→Gemini, SD→OpenRouter)
- 🐛 Service auth UUID mapping (using database UUIDs)
- 🐛 API get_db_pool() parameter errors
- 🐛 Missing database tables (app_definitions, landing_page_settings, features)
- 🐛 Log errors (eliminated app_definitions errors)

**Performance**:
- ⚡ 100% test pass rate (17/17 tests)
- ⚡ All P0 bugs fixed
- ⚡ API response times: 2-8ms (38x faster than Stripe)

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

All services share:
- ✅ Single Sign-On (Keycloak)
- ✅ Unified billing (Lago + Stripe)
- ✅ Centralized LLM routing
- ✅ Cross-service authentication
- ✅ Shared database and cache

---

## 🔒 Security

- **🔐 SSO Authentication**: Keycloak with Google, GitHub, Microsoft providers
- **🔑 API Key Management**: Bcrypt hashing, secure storage
- **👮 Role-Based Access**: 5-tier role hierarchy (admin → viewer)
- **📝 Audit Logging**: Complete activity tracking
- **🛡️ Input Validation**: Pydantic models, SQL injection protection
- **🔒 HTTPS/TLS**: SSL certificates via Traefik
- **💰 PCI Compliance**: Stripe handles all card data

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

### Phase 2: Enhanced Analytics (In Progress)
- 📊 User growth charts and heatmaps
- 📉 Churn analysis and retention metrics
- 💰 Revenue forecasting and LTV calculations
- ⚠️ Real-time alerts and notifications

### Phase 3: Advanced Organization Management
- 🏢 Team hierarchies and nested teams
- 🎭 Custom roles per organization
- 📦 Resource quotas and limits
- 🔐 Per-organization SSO providers

### Phase 4: Self-Service & Automation
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
- **🐛 Issues**: [GitHub Issues](https://github.com/Unicorn-Commander/Ops-Center/issues)
- **📚 Docs**: [Complete Documentation](https://docs.unicorncommander.ai)

---

<div align="center">

**⭐ Star us on GitHub** • **🐦 Follow on Twitter** • **💼 Connect on LinkedIn**

Made with 🦄 by [Magic Unicorn Tech](https://magicunicorn.tech)

</div>
