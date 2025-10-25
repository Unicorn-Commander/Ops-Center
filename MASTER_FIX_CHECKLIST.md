# Ops-Center Master Fix Checklist

**Generated**: October 25, 2025
**Total Issues**: 79
**Source**: Comprehensive page reviews of 25 pages

---

## 🔴 CRITICAL BLOCKERS (Must fix before production)

### Large Component Refactorings (Total: 60-89 hours)

- [ ] **C01**: Refactor LLM Management (AIModelManagement.jsx) - 1944 lines → 15+ components
  - Priority: CRITICAL
  - Estimated: 16-24 hours
  - Files: `src/pages/AIModelManagement.jsx`
  - Blocker: YES

- [ ] **C02**: Refactor Cloudflare DNS (CloudflareDNS.jsx) - 1481 lines → 20+ components
  - Priority: CRITICAL
  - Estimated: 18-26 hours
  - Files: `src/pages/CloudflareDNS.jsx`
  - Blocker: YES

- [ ] **C03**: Refactor Email Settings (EmailSettings.jsx) - 1550 lines → 10+ components
  - Priority: CRITICAL
  - Estimated: 14-21 hours
  - Files: `src/pages/EmailSettings.jsx`
  - Blocker: YES

- [ ] **C04**: Refactor Local Users (LocalUserManagement.jsx) - 1089 lines → 18+ components
  - Priority: CRITICAL
  - Estimated: 12-18 hours
  - Files: `src/pages/LocalUserManagement.jsx`
  - Security Risk: YES (SSH key deletion bug)

### Data Integrity Issues (Total: 14-18 hours)

- [ ] **C05**: Remove fake data fallbacks in LLM Usage (LLMUsage.jsx)
  - Priority: CRITICAL
  - Estimated: 4-6 hours
  - Files: `src/pages/LLMUsage.jsx`, lines 150-350
  - Issue: Silently generates random data when APIs fail

- [ ] **C06**: Fix Credits & Tiers (TierComparison.jsx) - No subscription functionality
  - Priority: CRITICAL
  - Estimated: 8-12 hours
  - Files: `src/pages/TierComparison.jsx`
  - Issue: 100% hardcoded data, buttons don't work

### Missing Pages (Total: 24-36 hours)

- [ ] **C07**: Create Organizations List page
  - Priority: CRITICAL
  - Estimated: 16-24 hours
  - Files: Create `src/pages/OrganizationsList.jsx`
  - Issue: Page doesn't exist, can't manage multiple organizations

- [ ] **C08**: Remove Roles & Permissions page (non-functional)
  - Priority: CRITICAL
  - Estimated: 1 hour
  - Files: `src/pages/PermissionManagement.jsx`
  - Action: Remove page, use RoleManagementModal instead

- [ ] **C09**: Fix API Keys menu link
  - Priority: CRITICAL
  - Estimated: 5 minutes
  - Files: `src/components/Layout.jsx`
  - Issue: Links to `/admin/authentication` (404), should link to `/admin/account/api-keys`

### Backend Implementation (Total: 20-30 hours)

- [ ] **C10**: Implement Traefik dashboard aggregation endpoint
  - Priority: CRITICAL
  - Estimated: 4-6 hours
  - Files: `backend/traefik_api.py`
  - Endpoint: `GET /api/v1/traefik/dashboard`

- [ ] **C11**: Implement service discovery endpoint
  - Priority: CRITICAL
  - Estimated: 6-8 hours
  - Files: `backend/traefik_api.py`
  - Endpoint: `GET /api/v1/traefik/services/discover`

- [ ] **C12**: Implement SSL certificate renewal endpoints
  - Priority: CRITICAL
  - Estimated: 8-12 hours
  - Files: `backend/traefik_api.py`
  - Endpoints: `POST /api/v1/traefik/ssl/renew/{id}`, `POST /api/v1/traefik/ssl/renew/bulk`

- [ ] **C13**: Fix Traefik metrics endpoint structure
  - Priority: CRITICAL
  - Estimated: 2-4 hours
  - Files: `backend/traefik_api.py`
  - Issue: Endpoint mismatch, missing CSV export

---

## ⚠️ HIGH PRIORITY (Should fix soon)

### alert() → Toast Notifications (Total: 6-8 hours)

- [ ] **H01**: Replace alert() in LLM Management
  - Files: `src/pages/AIModelManagement.jsx`, lines 373, 387

- [ ] **H02**: Replace alert() in Monitoring (System.jsx)
  - Files: `src/pages/System.jsx`, line 299

- [ ] **H03**: Replace alert() in LLM Providers
  - Files: `src/pages/LiteLLMManagement.jsx`

- [ ] **H04**: Replace alert() in Email Settings
  - Files: `src/pages/EmailSettings.jsx`

- [ ] **H05**: Replace alert() in Cloudflare DNS
  - Files: `src/pages/CloudflareDNS.jsx`

- [ ] **H06**: Replace alert() in Local Users
  - Files: `src/pages/LocalUserManagement.jsx`

- [ ] **H07**: Replace alert() in Brigade
  - Files: `src/pages/Brigade.jsx`

- [ ] **H08**: Replace alert() in Platform Settings
  - Files: `src/pages/PlatformSettings.jsx`

### Error Handling (Total: 12-16 hours)

- [ ] **H09**: Add error states to Monitoring (System.jsx)
  - Files: `src/pages/System.jsx`
  - Missing: Error handling for hardware/disk-io/network APIs

- [ ] **H10**: Add error boundaries to LLM Management
  - Files: `src/pages/AIModelManagement.jsx`

- [ ] **H11**: Add error states to LLM Providers
  - Files: `src/pages/LiteLLMManagement.jsx`

- [ ] **H12**: Add error handling to Traefik pages (5 pages)
  - Files: All Traefik components

- [ ] **H13**: Add error boundaries to Billing pages
  - Files: All billing components

### Network Issues (Total: 6-8 hours)

- [ ] **H14**: Implement Network tab in Monitoring
  - Files: `src/pages/System.jsx`, lines 898-913
  - Option A: Hide tab (5 min)
  - Option B: Implement network stats (6-8 hours)

- [ ] **H15**: Fix network stats in Monitoring (always 0)
  - Files: `src/pages/System.jsx`, line 180
  - Issue: State never updated from API

### Security & Validation (Total: 10-15 hours)

- [ ] **H16**: Fix SSH key deletion bug in Local Users
  - Files: `src/pages/LocalUserManagement.jsx`
  - Issue: Uses array index instead of key ID (will delete wrong key)

- [ ] **H17**: Add form validation to Email Settings
  - Files: `src/pages/EmailSettings.jsx`

- [ ] **H18**: Add validation to Platform Settings
  - Files: `src/pages/PlatformSettings.jsx`

- [ ] **H19**: Add process kill warnings for critical processes
  - Files: `src/pages/System.jsx`

### Backend Verification (Total: 8-12 hours)

- [ ] **H20**: Verify Platform Settings backend exists
  - Files: `backend/platform_settings_api.py`

- [ ] **H21**: Verify Local Users backend exists
  - Files: `backend/local_users_api.py`

- [ ] **H22**: Verify BYOK API endpoints work
  - Files: `backend/user_api_keys.py`

- [ ] **H23**: Implement Brigade usage/history endpoints
  - Files: `backend/brigade_api.py`
  - Endpoints: `/api/v1/brigade/usage`, `/api/v1/brigade/tasks/history`

---

## 🟡 MEDIUM PRIORITY (Nice to have)

### Mock Data Issues (Total: 8-12 hours)

- [ ] **M01**: Remove/label mock BYOK data in LLM Providers
  - Files: `src/pages/LiteLLMManagement.jsx`

- [ ] **M02**: Fix dynamic Tailwind classes in LLM Providers
  - Files: `src/pages/LiteLLMManagement.jsx`
  - Issue: `className={`border-${color}/20`}` won't work

- [ ] **M03**: Fix provider logos (404 errors)
  - Files: `src/pages/LiteLLMManagement.jsx`

- [ ] **M04**: Remove hardcoded subscription data
  - Files: `src/pages/SubscriptionManagement.jsx`

### UX Improvements (Total: 12-16 hours)

- [ ] **M05**: Implement Network tab or hide it
  - Files: `src/pages/System.jsx`

- [ ] **M06**: Add auto-refresh to Traefik pages
  - Files: All Traefik components

- [ ] **M07**: Add bulk operations to Traefik
  - Files: Traefik components

- [ ] **M08**: Fix Email Settings edit form (doesn't pre-populate)
  - Files: `src/pages/EmailSettings.jsx`
  - Known issue: Documented in KNOWN_ISSUES.md

- [ ] **M09**: Add loading states to Brigade
  - Files: `src/pages/Brigade.jsx`

- [ ] **M10**: Add CSV export to Traefik Metrics
  - Files: `src/pages/TraefikMetrics.jsx`

### Code Quality (Total: 10-14 hours)

- [ ] **M11**: Replace axios with fetch in Cloudflare DNS
  - Files: `src/pages/CloudflareDNS.jsx`
  - Issue: Inconsistent with rest of app

- [ ] **M12**: Use useReducer instead of 23 useState in Cloudflare DNS
  - Files: `src/pages/CloudflareDNS.jsx`

- [ ] **M13**: Use useReducer instead of 19 useState in User Management
  - Files: `src/pages/UserManagement.jsx`

- [ ] **M14**: Make chart colors theme-aware in Monitoring
  - Files: `src/pages/System.jsx`, lines 318-323

### Configuration (Total: 6-8 hours)

- [ ] **M15**: Replace hardcoded paths with env vars in LLM Management
  - Files: `src/pages/AIModelManagement.jsx`, lines 69, 79, 93, 103

- [ ] **M16**: Make API base URL dynamic in API Documentation
  - Files: `src/pages/APIDocumentation.jsx`

- [ ] **M17**: Remove hardcoded version in API Documentation
  - Files: `src/pages/APIDocumentation.jsx`

---

## 🟢 LOW PRIORITY (Future enhancements)

### Feature Additions (Total: 30-40 hours)

- [ ] **L01**: Add audit logging to Platform Settings
- [ ] **L02**: Add test connections for all Platform Settings categories
- [ ] **L03**: Add global search to API Documentation
- [ ] **L04**: Add route testing endpoint in Traefik
- [ ] **L05**: Add model comparison feature in LLM Management
- [ ] **L06**: Add model benchmarks/performance in LLM Management
- [ ] **L07**: Add model versioning in LLM Management
- [ ] **L08**: Add model aliasing in LLM Management
- [ ] **L09**: Add model usage analytics in LLM Management
- [ ] **L10**: Add export metrics to CSV in Monitoring

### UX Polish (Total: 20-30 hours)

- [ ] **L11**: Improve mobile experience for large tables
- [ ] **L12**: Add keyboard shortcuts
- [ ] **L13**: Add dark mode improvements
- [ ] **L14**: Add tooltips to all icons
- [ ] **L15**: Add loading skeletons everywhere
- [ ] **L16**: Add empty states everywhere
- [ ] **L17**: Add success animations
- [ ] **L18**: Add undo/redo for destructive actions

### Performance (Total: 20-30 hours)

- [ ] **L19**: Implement code splitting
- [ ] **L20**: Add service worker for offline support
- [ ] **L21**: Optimize bundle size (currently 2.7MB)
- [ ] **L22**: Add pagination to large lists
- [ ] **L23**: Implement virtual scrolling for large tables
- [ ] **L24**: Add data caching strategies
- [ ] **L25**: Optimize re-renders

---

## 📊 Summary Statistics

### By Priority
- **Critical**: 13 items (98-163 hours)
- **High**: 23 items (42-59 hours)
- **Medium**: 17 items (36-50 hours)
- **Low**: 25 items (70-100 hours)

### Total Estimated Effort
- **Phase 1 (Critical)**: 98-163 hours (12-20 days with 1 dev, 6-10 days with 2 devs)
- **Phase 2 (High)**: 42-59 hours (5-7 days)
- **Phase 3 (Medium)**: 36-50 hours (4-6 days)
- **Phase 4 (Low)**: 70-100 hours (9-12 days)

### Grand Total: 246-372 hours (31-47 days with 1 developer)

### With Parallel Development (5 developers)
- **Phase 1**: 6-10 days
- **Phase 2**: 3-4 days
- **Phase 3**: 2-3 days
- **Phase 4**: 5-6 days
- **Total**: 16-23 days (3-5 weeks)

---

## 🎯 Recommended Execution Order

### Sprint 1 (Week 1): Quick Wins
- C09: Fix API Keys menu (5 min)
- C08: Remove Permissions page (1 hour)
- All H01-H08: Replace alert() → toast (6-8 hours)
- H14 Option A: Hide Network tab (5 min)

### Sprint 2 (Week 1-2): Data Integrity
- C05: Remove fake data in LLM Usage
- C06: Fix Credits & Tiers subscription
- H15: Fix network stats

### Sprint 3 (Week 2-3): Backend APIs
- C10-C13: Traefik endpoints
- H23: Brigade endpoints
- H20-H22: Backend verification

### Sprint 4 (Week 3-4): Refactoring
- C01: LLM Management refactor
- C02: Cloudflare DNS refactor

### Sprint 5 (Week 4-5): More Refactoring
- C03: Email Settings refactor
- C04: Local Users refactor (with SSH key bug fix)

### Sprint 6 (Week 5): Missing Pages
- C07: Create Organizations List page

### Sprint 7 (Week 6+): Error Handling & Polish
- H09-H13: Add error states
- H16-H19: Security & validation
- M01-M17: Medium priority items

