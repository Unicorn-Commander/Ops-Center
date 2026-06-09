# Ops-Center Security Audit — Unauthenticated Endpoint Exposure

**Date:** 2026-06-08
**Node audited:** magicunicorn.dev (bigboy, dogfood) — backend `ops-center-direct` @ localhost:8084
**Method:** Pulled the live OpenAPI spec (886 paths / 1015 ops), then unauthenticated-probed every parameter-free GET both externally (through Cloudflare) and internally (localhost, no proxy) for clean signal. Cross-checked against per-endpoint / router-level / include-level auth dependencies via AST.
**Trigger:** The new pricing rate-book router (commit `18b37fbb`) shipped with no auth. This audit asked: is that an isolated miss or systemic? **Answer: systemic.**

---

## Headline

| | Count |
|---|---|
| Param-free GET endpoints probed | 448 |
| Return `200` unauth (auth NOT enforced) | 162 |
| ↳ **Actively leaking real data unauth (>50 B body)** | **110** |
| ↳ Auth-bug but currently empty body (no data source on this node) | 15 |
| Reach handler unauth with `422` (validation, no auth) | 12 |
| Reach handler unauth with `500` (errored, no auth) | 11 |
| Properly protected (`401`/`403`) | 177 |

**This is a hard production blocker for the unicorncommander.ai rollout.**

> **REMEDIATION STATUS (2026-06-08, FULLY CLOSED — deployed + verified on magicunicorn.dev):**
> **Final state: 0 non-public endpoints reachable unauthenticated** (full param-free GET sweep:
> 393 → 401, 40 legitimately public). Two-part fix:
>
> 1. **Default-deny `AuthenticationMiddleware`** (`backend/auth_middleware.py`, commits `5bb72b72`,
>    `25f03685`) gates every `/api/*` behind a valid session unless allowlisted (public surfaces +
>    m2m prefixes). Closed ~111 endpoints at the front door (43 KB audit log, `/analytics/revenue/*`,
>    `/system/*`, `/permissions/*`, `/backups/*`). Kill switch: `AUTH_MIDDLEWARE_ENABLED=false`.
> 2. **Per-endpoint gates for the 11 residual** admin endpoints under the allowlisted `/llm` + `/compute`
>    prefixes (commits `9a33494b`, `bdb17c31`, `3612e8c2`) — classified admin-vs-m2m by an agent swarm
>    + manual adversarial m2m-caller check.
>
> **Also fixed a latent class bug:** `compute_api.py` and `billing_events.py` used a `from server import
> require_admin` pattern that ALWAYS hit ImportError (circular) and fell back to a stub returning
> `{role: admin}` unconditionally — making their auth **inert** (compute mutations like drain/delete-pipeline
> and the billing metering-ingest were effectively unauthenticated). Repaired both fallbacks to map to the
> standalone `auth_dependencies` module. The default-deny middleware already neutralized the broad blast
> radius of this pattern; only the allowlisted-prefix files needed the direct repair.
>
> **Verified:** unauth → 401 (all); logged-in admin (role=admin) → 200 (all 11 + billing dashboards);
> m2m intact — a real session inference call traversed middleware → endpoint → upstream LLM provider;
> `models/curated` (Brigade) 200; `GPU_AGENT_KEY` set so agent ingest functional; container starts clean.

### Why the customer node is *worse*, not better
Several endpoints return `200`-but-empty here only because their data source (the commander-only `uchub-postgres` Keycloak DB, billing aggregator) **isn't present on the dogfood node**. On **unicorncommander.ai**, which *does* have those data sources, the same unauthenticated endpoints would serve **real** revenue, user-cohort, audit, and Keycloak data to the public internet.

---

## Exposure by router cluster (the root-cause shape)

These are whole routers written without any auth dependency — not scattered one-offs:

| Cluster | ~Endpoints | What leaks | Severity |
|---|---|---|---|
| `/api/v1/analytics/revenue/*` | 13 | MRR, ARR, churn, LTV, forecasts, revenue by-plan/by-tier | **Critical** (business-confidential) |
| `/api/v1/analytics/users/*` | 10 | acquisition, churn, cohorts, segments, retention, LTV | **Critical** |
| `/api/v1/analytics/{usage,services,metrics}/*` | 17 | usage/cost/latency/uptime telemetry | High |
| `/api/v1/audit/*` | 5 | **audit logs (43 KB), security log, recent actions** | **Critical** |
| `/api/v1/llm/usage/*` + `/llm/{providers,costs,routing,models,test}` | 15 | LLM usage, costs, provider list, routing rules | High |
| `/api/v1/system/{keycloak,alerts,hardware,processes}` | 8 | KC clients/SSL/session config, process list, hardware | **Critical** |
| `/api/v1/permissions/*` | 5 | full RBAC matrix, roles, resources, actions | High |
| `/api/v1/billing/{events,analytics}/*` | 4 | billing events, markup-revenue, analytics summary | High |
| `/api/v1/{backups,storage}/*` | 8 | backup config/providers, storage volumes/info | High |
| `/api/v1/{platform/settings, deployment/config, settings, service-urls, services/*}` | 8 | platform/deployment config, service inventory | High |
| `/api/v1/{metering, models, logs, compute, email-provider, forgejo, network}/*` | ~15 | metering, model mgmt, service logs, compute jobs, email providers | Medium–High |

### Top 15 active leaks by response size (unauth, real data)
```
43551 B  /api/v1/audit/logs
20346 B  /api/v1/audit/recent
12341 B  /api/v1/logs/services
10743 B  /api/v1/analytics/services/errors
 8321 B  /api/v1/extensions/catalog          (may be intentional — marketplace)
 6592 B  /api/v1/platform/settings           (CHECK for embedded credentials)
 6142 B  /api/v1/llm/models/curated
 6110 B  /api/v1/analytics/services/uptime
 6080 B  /api/v1/analytics/services/latency
 5634 B  /api/v1/compute/jobs
 4403 B  /api/v1/llm/test/templates
 4384 B  /api/v1/llm/usage/overview
 3899 B  /api/v1/permissions/matrix
 3553 B  /api/v1/my-apps/authorized          (should be user-scoped; returns data unauth)
 3012 B  /api/v1/backups/rclone/providers
```

### Needs a manual secret-check (names imply credentials)
- `/api/v1/system/keycloak/api-credentials` — 200 unauth (empty on this node; **verify on a node with KC DB**)
- `/api/v1/platform/settings` — 6.5 KB unauth; confirm no provider keys/secrets in the payload
- `/api/v1/system/keycloak/{clients,session-config,ssl-status}` — KC config

### Known-intentional public (exclude from remediation)
`/api/v1/billing/provider-config` (public Stripe pk + provider name, by design), `/api/v1/public/pricing/*`, `/api/v1/branding/config`, `*/health`, `/.well-known/*`, `/api/v1/auth/{login,logout,csrf-token,password-policy}`, `/api/v1/my-apps/marketplace`, `/api/v1/llm/models/curated` (used by Brigade/Open-WebUI — verify intended).

---

## Root cause

The console relies on **per-endpoint `Depends(<auth fn>)`** for protection (e.g. `require_admin_user`, `require_admin`, `require_authenticated_user`). Routers whose authors never added that dependency are simply open — there is **no default-deny**. The CSRF middleware has a centralized allowlist, but there is no equivalent **authentication** middleware, so a forgotten dependency = a public endpoint. (The pricing router was one instance; the analytics/audit/system/llm-usage/permissions routers are the rest.)

---

## Recommended remediation

**Add a default-deny authentication middleware** (mirroring the existing CSRF middleware): authenticate every request, with an explicit **public allowlist** (health, `/public/*`, `branding/config`, auth handshake, `.well-known`, webhooks-with-own-signature, and machine-to-machine routes that use their own key auth — federation/compute/inference/uuda/a2a). This fixes the entire class at once and makes "forgot the dependency" fail **closed** instead of open.

- **Preferred:** one middleware + allowlist (~1 file, plus careful allowlist curation + broad re-test). Fixes 110+ endpoints structurally.
- **Alternative:** add `Depends(require_admin_user)` to ~15–20 routers individually (≈137 endpoints). More churn, more risk of missing one, no protection against the *next* forgotten dependency.
- Either way: re-run this probe after the fix and confirm the 110 flip to `401`, while authenticated admin + m2m flows still work.

**Caveat:** the allowlist must be curated carefully — several currently-open routes are legitimately public or use their own auth (provider-config, pricing, federation/compute m2m). Getting the allowlist wrong breaks real traffic, so this is a deliberate change with a full re-test, not a quick patch.

---

## Appendix — full machine-readable lists
- Size-ranked active leaks: `/tmp/exposed_sizes.txt`
- Full 200-unauth + 422/500 list: `/tmp/exposed_list.txt`
- Probe raw results (internal): bigboy `/tmp/probe_internal.txt`
- Audit script (per-endpoint auth AST check): `audit_auth.py` (noisy on custom auth-fn names; live probe above is authoritative)
