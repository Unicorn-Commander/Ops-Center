# Multi-Deployment Theming Guide

## Overview

The UC-Cloud platform (Ops-Center + supporting services) runs on **multiple servers**, each with its own branding, domain, and theme. All servers share the same platform codebase but must maintain distinct visual identities.

## Active Deployments

| Server | Domain | Theme | Purpose |
|--------|--------|-------|---------|
| **Unicorn Commander** | unicorncommander.ai | Purple/gold Magic Unicorn | Main platform hub |
| **Center Deep** | centerdeep.online | Blue/teal privacy-focused | AI metasearch & data intel |
| **Magic Unicorn Special Project** | magicunicorn.dev | TBD | Special project deployment |

## Rules for Contributors

### 1. Theme changes are server-specific, NOT universal

If you're changing colors, logos, branding, or visual identity:
- **DO NOT** commit these to the shared `main` branch
- Keep them in server-specific config files (e.g., `.env.centerdeep`, `docker-compose.centerdeep.yml`)
- Or maintain them as local-only changes on that server

### 2. What IS universal (push to Forgejo)

- Backend logic (API endpoints, database queries, auth flows)
- New features (billing, user management, integrations)
- Bug fixes
- Expanded tier lists, new subscription tiers
- Navigation structure changes
- Security patches

### 3. What is NOT universal (keep local per server)

- Theme colors, gradients, accent colors
- Logo files specific to a deployment
- Domain-specific `.env` values (`EXTERNAL_HOST`, `SESSION_COOKIE_DOMAIN`)
- Server-specific Docker Compose files
- Landing page branding
- Server-specific integrations (e.g., DataIntel is Center Deep only)

## Server-Specific Configuration Pattern

Each server deployment should use:

```
.env.{server}          # Server-specific environment variables
docker-compose.{server}.yml  # Server-specific Docker Compose overlay
```

### Example: Center Deep

```bash
# Files that exist only on Center Deep server:
.env.centerdeep                    # EXTERNAL_HOST=centerdeep.online
docker-compose.centerdeep.yml     # Traefik labels for centerdeep.online
src/pages/admin/DataIntelSettings.tsx  # Center Deep-only feature
public/logos/caqrp_logo.png       # Center Deep partner logos
```

### Example: Unicorn Commander

```bash
# Files that exist only on Unicorn Commander server:
.env.auth                          # EXTERNAL_HOST=unicorncommander.ai
docker-compose.direct.yml         # Traefik labels for unicorncommander.ai
```

## How to Add a New Server Deployment

1. Create `.env.{servername}` with server-specific variables
2. Create `docker-compose.{servername}.yml` with Traefik routing
3. Configure Keycloak realm federation (if using shared SSO)
4. Set `SESSION_COOKIE_DOMAIN=.yourdomain.com`
5. Apply any server-specific theme customizations locally
6. **Do NOT push theme customizations to the shared repo**

## Cross-Domain SSO

Each server runs its own Keycloak instance in the `uchub` realm. Center Deep's Keycloak federates with Unicorn Commander's, enabling cross-platform login. See the Ops-Center `CLAUDE.md` for SSO configuration details.
