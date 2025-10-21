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
- 👥 **User Management** - Advanced filtering, bulk operations, role management
- 💳 **Billing Integration** - Lago + Stripe subscription management
- 🏢 **Organization Management** - Multi-tenant organization control
- 🤖 **LLM Provider Management** - 100+ models via LiteLLM proxy
- 🔐 **Keycloak SSO** - Google, GitHub, Microsoft authentication
- 📊 **Analytics Dashboard** - Real-time metrics and usage tracking
- 🔑 **API Key Management** - User API key generation and management
- 👤 **User Impersonation** - Admin "login as user" capability

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
git clone --recurse-submodules https://github.com/Unicorn-Commander/UC-Cloud.git
cd UC-Cloud

# Ops-Center will be at services/ops-center/
docker compose up -d
\`\`\`

### Standalone Deployment

\`\`\`bash
# Clone repository
git clone https://github.com/Unicorn-Commander/Ops-Center.git
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

## Documentation

- **Complete Guide**: See \`CLAUDE.md\` for comprehensive documentation
- **Admin Guide**: \`ADMIN_QUICKSTART.md\` for admin operations
- **Billing Setup**: \`BILLING_QUICK_START.md\` for Lago + Stripe

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
https://github.com/Unicorn-Commander/UC-Cloud

---

**Magic Unicorn Unconventional Technology & Stuff Inc** | https://unicorncommander.ai
