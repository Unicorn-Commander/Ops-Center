# Legacy local authentication

Ops-Center's file-backed local-user login is disabled by default. Set
`LEGACY_LOCAL_AUTH_ENABLED=true` only when a deployment intentionally needs the
legacy `/api/v1/auth/login` flow. When enabled, the startup admin is created
only if `ADMIN_PASSWORD` is set to a value at least 16 characters long; there is
no fallback password. If the requirement is not met, startup logs one warning
and creates no admin.

The normal Keycloak/SSO session flow is separate from this legacy local-auth
flag. Existing local JWTs and routes that accept them are rejected with 401
while the flag is disabled.
