# Changelog

All notable changes to Ops-Center will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.6.0] - 2026-06-13

Federation monetization complete + inference cost-recovery substrate. (Tracked in
Project-Ops P-00067. Full detail: `~/Documents/federation-build-report.md` and
`~/Documents/UC-Inference-Cost-Recovery-Design.md`.)

### Added
- **Federation reconciliation**: trust modes (full/scoped/consumer/publisher/isolated)
  now ENFORCED at `/services`, `/agents`, `/route` with deny-by-default
  (`FEDERATION_DEFAULT_TRUST_MODE`, platform_settings-overridable). The per-org gateway
  key (`user_id == org_id`) now survives the federation hop (`X-Federation-Org-Id`), so
  the single billable Lago `ai_api_call` event keys to the consuming org across nodes.
- **Billing-on-signup** (`plan_provisioning`): plan activation auto-provisions the org's
  gateway key (migration 011; `/key/update` on plan changes).
- **Federated local models in the customer LLM API**: a trusted peer's published model is
  served via federation under the caller's org; publisher resolves raw catalog names →
  gateway aliases. Surfaced in `/models` and `/models/categorized`.
- **Layer-2 agent contracts**: per-agent ACLs (`consume: ["agents/<id>"]`) +
  `POST /federation/agents/{id}/invoke` → one `agent_invocation` Lago event (completed-only;
  units from `FEDERATION_AGENT_PRICING`).
- **True SSE stream-through** for federated inference — token-by-token relay across both
  nodes (`serve_federated_inference_stream`, `proxy_to_node_stream`,
  `stream_llm_via_federation`); the publisher's gateway meters once on stream completion.
- **Per-(app, model) included-vs-metered policy** (`inference_policy.py` + `app_model_policy`
  table) — bundle specific models into an app subscription; default metered (zero rows = no
  behavior change).
- **Routing-audit timed flush** (`FEDERATION_AUDIT_FLUSH_SECONDS`, default 30s).

### Fixed
- **Credit double-debit**: chat/image handlers stamp `_metadata.credits_settled`; the credit
  middleware skips its own deduction on `credits_settled`/`gateway_metered` (was a latent
  double-charge for non-exempt paid users, masked by exempt tiers).
- **Mode C cost leak**: direct-API (`uc_`) keys now bill the key owner's real tier instead of
  a hardcoded `vip_founder` exempt (fail-open to exempt on lookup error).
- **Budget/tier decouple**: gateway-key budget is no longer sourced from the subscription
  tier — inference spend is guarded by the credit wallet (subscription and credits are
  orthogonal axes).

### Removed
- Opus-distill model (weights + presets + alias).

## [2.5.2] - 2026-02-27

### Added
- **Colonel → Brigade Delegation**: One-way A2A delegation from Colonel to Unicorn Brigade
  - New `brigade-delegation` skill with `delegate_task` and `list_agents` actions
  - Colonel can delegate research, coding, finance, legal, medical, and other domain tasks to Brigade's 17 specialist agents
  - Uses A2A protocol (JSON-RPC over HTTP) for inter-service communication
  - Agent discovery via public A2A endpoint, task execution via authenticated invoke
  - Handles timeouts (120s), auth errors, missing agents, and empty responses gracefully

### Configuration
- **Brigade Auth**: Added `BRIGADE_ADMIN_KEY` to Brigade container for service-to-service authentication
- **Ops-Center Env**: Added `BRIGADE_API_URL` and `BRIGADE_API_KEY` environment variables
- **Docker Compose**: Updated `docker-compose.brigade.yml` and `docker-compose.direct.yml`

### Files Added
- `backend/colonel/skills/brigade-delegation.skill.md` - Skill definition (YAML frontmatter)

### Files Modified
- `backend/colonel/skill_executor.py` - Added `brigade_delegate_task()` and `brigade_list_agents()` executors
- `backend/colonel/models.py` - Added `brigade-delegation` to default `enabled_skills`

---

## [2.5.1] - 2026-02-22

### Fixed
- **Frontend Audit Sweep**: Comprehensive 108-file frontend quality audit and fix
  - Removed dead code: 3 unused files deleted (useColonelSkills.js, useColonelMemory.js, CommandOutput.jsx)
  - Removed unused imports across 10 files (App.jsx, Layout.jsx, RootRedirect.jsx, ColonelChat.jsx, UserDetail.jsx, AccountAPIKeys.jsx)
  - Removed duplicate routes for `platform/white-label` and `apps` in App.jsx
  - Removed debug `console.log` statements from App.jsx, Layout.jsx, OrganizationTeam.jsx
  - Fixed Dashboard.jsx quick actions: `window.location.href` → `navigate()` for SPA routing
  - Fixed swapped Visitors/Page Views labels in UmamiConfig.jsx
  - Fixed hardcoded `localhost:8084` URLs in UmamiConfig, GrafanaConfig, PrometheusConfig, GrafanaViewer → relative paths
  - Added `credentials: 'include'` to 232 fetch() calls across 74 files for proper SSO cookie handling
  - Added `StatusBadge` null checks in SubscriptionBilling and SubscriptionPlan to prevent crashes
  - Added missing `FireIcon` import in Security.jsx
  - Wired OrganizationBilling buttons (Change Plan, View Invoices, Cancel)
  - Wired SubscriptionCancel buttons (Pause Instead → plan page, Get Help → email)
  - Added WebSocket `streamBuffer` reset on session change in useColonelWebSocket.js
  - Replaced mock session fallback with empty array in AccountSecurity.jsx

### Improved
- **Monitoring Config Persistence**: UmamiConfig, GrafanaConfig, PrometheusConfig now save settings to localStorage and restore on page load (previously lost on refresh)
- **GrafanaViewer Preferences**: Theme, time range, and refresh interval now persist via localStorage
- **Colonel API Standardization**: ColonelSidebar.jsx now uses colonelApi.js instead of raw fetch calls
- **Dynamic URLs**: AccountAPIKeys.jsx now uses `window.location.origin` instead of hardcoded domain

### Changed
- Version bumped from v2.4.0 to v2.5.0 in Layout.jsx footer

---

## [2.3.0] - 2025-11-09

### Major Refactoring: Feature → App Terminology

**Breaking Changes**:
- API endpoint `/api/v1/admin/features` renamed to `/api/v1/admin/apps`
- Frontend route `/admin/system/feature-management` renamed to `/admin/system/app-management`

### Changed

#### Database Schema
- **Table Renamed**: `feature_definitions` → `app_definitions`
- **Table Renamed**: `tier_features` → `tier_apps`
- **Column Renamed** (app_definitions): `feature_key` → `app_key`, `feature_name` → `app_name`, `feature_description` → `app_description`, `feature_icon` → `app_icon`
- **Column Renamed** (tier_apps): `feature_key` → `app_key`, `feature_value` → `app_value`
- **Backward Compatibility**: Created views `feature_definitions` and `tier_features` as aliases for transition period

#### Backend API
- **New File**: `backend/app_definitions_api.py` - App management endpoints
- **Updated**: `backend/tier_features_api.py` - Updated to use `tier_apps` table
- **Updated**: `backend/server.py` - Router registration updated
- **Updated**: `backend/subscription_tiers_api.py` - Updated JOIN to use `tier_apps`
- **Updated**: `backend/my_apps_api.py` - Updated terminology throughout

#### Frontend
- **Renamed**: `FeatureManagement.jsx` → `AppManagement.jsx` (16.15 KB)
- **Updated**: `App.jsx` - Route and import updated
- **Updated**: `Layout.jsx` - Navigation menu updated
- **Updated**: `SubscriptionManagement.jsx` - API calls and data mapping updated
- **UI Text**: All instances of "Feature" changed to "App" throughout interface

### Added
- **Migration Script**: `backend/migrations/rename_features_to_apps.sql` (1.8 KB)
- **Documentation**: `FEATURE_TO_APP_REFACTORING_COMPLETE.md` - Comprehensive refactoring guide
- **API Endpoints**: 4 new endpoints under `/api/v1/admin/apps/*`

### Fixed
- **Terminology Confusion**: Eliminated ambiguity between tier properties (e.g., `is_active`, `byok_enabled`) and user-facing services/applications (e.g., Brigade, Bolt, Chat)
- **Consistent Naming**: Database, backend, and frontend now use consistent "app" terminology

### Migration Guide

**For API Clients**:
```bash
# Old endpoint (deprecated but still works via backward-compatible views)
GET /api/v1/admin/features

# New endpoint (recommended)
GET /api/v1/admin/apps
```

**For Users**:
- Bookmark update: `/admin/system/feature-management` → `/admin/system/app-management`

**Database Migration** (automatic):
```sql
-- Backward-compatible views created automatically
-- Old code continues to work during transition period
SELECT * FROM feature_definitions;  -- Still works (view → app_definitions)
SELECT * FROM tier_features;        -- Still works (view → tier_apps)
```

### Data Preservation
- ✅ **100% Data Integrity**: All 17 apps and 21 tier-app associations preserved
- ✅ **Zero Downtime**: Backward-compatible views ensure old code continues working
- ✅ **Rollback Ready**: Complete rollback procedure documented if needed

---

## [2.2.0] - 2025-11-04

### Added
- **Image Generation API**: OpenAI-compatible `/api/v1/llm/image/generations` endpoint
  - Support for DALL-E 2/3, Stable Diffusion XL/3 via OpenRouter
  - BYOK support (no credits charged when using own API keys)
  - Tier-based pricing with automatic cost calculation
  - Quality options (standard/HD) and batch generation (up to 10 images)
  - OpenAI SDK compatible

- **Model Categorization**: New `/api/v1/llm/models/categorized` endpoint
  - Separates BYOK models (free) from Platform models (charged)
  - Smart provider detection based on user's API keys
  - Detailed provider-level summaries
  - Integration guide for Bolt/Presenton/Open-WebUI

### Documentation
- `docs/api/IMAGE_GENERATION_API_GUIDE.md` - Complete image generation guide (20+ pages)
- `docs/api/IMAGE_GENERATION_QUICK_START.md` - Quick start guide
- `docs/INTEGRATION_GUIDE.md` - Bolt/Presenton/Open-WebUI integration (800+ lines)

---

## [2.1.0] - 2025-10-29

### Fixed
- **Credit System Authentication**: Fixed user session integration
  - Replaced test user fallback with real Keycloak session authentication
  - Added automatic field mapping: Keycloak `sub` → application `user_id`
  - Fixed circular import in `credit_api.py`

- **Credit Display Formatting**: Removed misleading dollar signs
  - Changed display from "$10,000" to "10,000 credits"
  - Created `formatCredits()` function with comma separators
  - Updated 4 display locations in Credit Dashboard

### Added
- **Organization Setup**: Created "Magic Unicorn" organization with professional tier
- **Credit Allocation**: Allocated 10,000 credits to admin user
- **OpenRouter Integration**: Verified API key configuration in LiteLLM proxy

### Documentation
- `CREDIT_BALANCE_EXPLAINED.md` - Guide to understanding credit vs OpenRouter balances
- `CREDIT_API_USER_ID_FIX.md` - Authentication fix documentation
- `CREDIT_DISPLAY_FIX.md` - Display formatting documentation
- `FINAL_CREDIT_FIX_SUMMARY.md` - Complete technical summary

---

## [2.0.0] - 2025-10-15

### Added - Phase 1: User Management & Billing Dashboard

#### User Management System (Complete)
- **Bulk Operations**: CSV import/export, bulk role assignment, bulk suspend/delete, bulk tier changes
- **Advanced Filtering**: 10+ filter options (tier, role, status, org, date ranges, BYOK, email verified)
- **User Detail Page**: Comprehensive 6-tab profile view with charts and activity timeline
- **Enhanced Role Management**: Dual-panel UI with visual permission matrix
- **API Key Management**: Full CRUD for user API keys with bcrypt hashing
- **User Impersonation**: Admin "login as user" feature with 24hr sessions
- **Activity Timeline**: Color-coded audit log with expandable details

#### Billing Dashboard (Complete)
- **Subscription Plans**: Trial ($1/week), Starter ($19/mo), Professional ($49/mo), Enterprise ($99/mo)
- **Lago Integration**: Full billing system with GraphQL API
- **Stripe Integration**: Payment processing with 7 webhook events
- **Invoice Management**: History, payment tracking, usage metering
- **Webhook Handling**: Automated subscription lifecycle management

#### New Components
- `UserDetail.jsx` - 6-tab user profile page (1,078 lines)
- `RoleManagementModal.jsx` - Enhanced role UI (534 lines)
- `PermissionMatrix.jsx` - Visual permission grid (177 lines)
- `BulkActionsToolbar.jsx` - Bulk operations UI
- `ImportCSVModal.jsx` - CSV import wizard
- `APIKeysManager.jsx` - API key management (493 lines)
- `ActivityTimeline.jsx` - Activity audit log (418 lines)

#### New API Endpoints
- User Management: 15+ new endpoints for bulk operations, impersonation, API keys
- Role Management: 4 new endpoints for hierarchy, permissions, effective permissions
- Session Management: 3 endpoints for session tracking and revocation

### Changed
- **User Management**: Enhanced with advanced filtering (10+ parameters)
- **Keycloak Integration**: Automatic user attribute population for 9 users
- **Frontend Build**: Added dependencies: `react-chartjs-2`, `chart.js`

### Documentation
- `USER_MANAGEMENT_GAP_ANALYSIS.md` - Feature gap analysis
- `DEPLOYMENT_VERIFICATION_GUIDE.md` - 82-page testing guide
- `docs/API_REFERENCE.md` - OpenAPI-style API documentation
- `docs/ADMIN_OPERATIONS_HANDBOOK.md` - Practical admin guide
- `CODE_REVIEW_REPORT.md` - Quality assessment (B+ grade)
- `NEXT_PHASE_ROADMAP.md` - Strategic roadmap (Phases 2-4)

---

## [1.0.0] - 2025-09-01

### Initial Release
- Basic user management
- Service management dashboard
- Keycloak SSO integration
- LLM management via LiteLLM
- Docker deployment configuration
