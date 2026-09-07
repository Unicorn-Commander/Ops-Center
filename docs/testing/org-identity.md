# Billing identity and release verification

## Current authorization contract

Every user-facing billing selection is checked against current active persisted
membership. Session and Keycloak org attributes express selection only. Neither
session-wide admin claims nor ownership of another organization grant billing
rights in the selected organization. An absent selection can resolve only when
there is exactly one active membership.

The default SQL reads `public.organization_members` directly by authenticated
uchub subject (`user_id` varchar), joins `public.organizations` (`id` UUID), and
requires `status = 'active'`. It does not depend on `public."user"`, which the
orchestrator's live schema check found absent in both dogfood and production.
Only when direct membership is empty does a catalog capability check inspect
whether the optional legacy table has both `id` and `oauth_sub`; SQL referencing
that table is never parsed unless the capability exists. There is no email lookup
or locally created identity. Selected non-membership returns 403, missing or
conflicting selection returns 409, and lookup outages return 503.

Mutation routes require the selected membership's `owner`, `admin`, or
`billing_admin` role. Ordinary members retain reads. Checkout, portal, subscription
cancel/upgrade/change/downgrade/confirmation, invoice retry, payment setup/default/
remove/address, and org-billing subscription creation/upgrade and credit add/allocation apply these checks
before provider or mutation calls. Target org IDs must agree with the selected
organization. Duplicate conflicting membership roles cannot promote privilege.

## Stripe and Lago identity

Lago keys normalize to `org_<uchub UUID>`. Stripe customer IDs remain billing
provider linkage, never tenant identity. Customer search considers bare and
prefixed UUID metadata together and rejects duplicates; subscription management
rejects foreign/missing metadata and incomplete paginated results. Invoice reads,
PDF and retry do not fall back to email or bypass the selected org for an admin.

The canonical `/api/v1/webhooks/stripe` dispatcher and compatibility aliases
validate event/customer organization consistency. Checkout and cancellation are
pinned independently of the browser's current selection. Confirmation rejects a
paid checkout belonging to a different selected org. Partial provisioning failures
return 503 for retry.

`customer.subscription.updated` fetches the latest subscription to avoid replaying
a delayed event's old price. Event/current-subscription/customer organization,
customer and suite must agree. Exactly one complete item price must map to exactly
one active `subscription_tiers` row via `stripe_price_monthly` or
`stripe_price_yearly`. Tier metadata is deliberately ignored. Conflicting/unmapped
prices return 409; provider/database/provisioning failures are retryable. Canceled
or unpaid subscriptions downgrade; incomplete, expired-incomplete, past-due,
paused and trialing states do not grant new paid entitlements.

## Reproduce without application services

Python 3.12 failed to build the repository's pinned dependency set. Python 3.11
installed the unchanged requirements in this worktree:

```sh
python3.11 -m venv .venv311
.venv311/bin/pip install -r backend/requirements.txt pytest pytest-asyncio
.venv311/bin/python backend/tests/run_billing_identity_tests.py
```

The runner redirects the legacy org-manager singleton's import-time `/app/data`
path to temporary storage. It selects the backend pytest config and clears legacy
coverage/strict-marker addopts. Providers and DB calls are mocked. A test-owned
loopback HTTP fixture verifies serialized Lago payloads; imported FastAPI routers
are exercised through HTTPX ASGI transport. No application services, live billing
operations, or deployment are involved.

## Evidence

- Original base `0a7968b8`: 93 passed / 3 existing failures.
- Initial identity commit `f2d8db6b`: 122 passed / same 3 failures.
- Registered-route follow-up `ee8bd34c`: 219 passed / same 3 failures.
- This release-blocker follow-up: 345 passed / the same 3 failures (126 added regressions).
- Before fixes: two membership tests reproduced missing-table failure and trusted
  selection bypass; four mutation-router tests reproduced member access despite
  insufficient org role; two actual subscription-update route tests reproduced
  silently ignored entitlement changes.
- Membership tests cover missing optional schema, capability gating, active-only
  SQL, revoked membership, role changes and cross-org privilege isolation.
- Actual router tests cover same-email tenants, selection changes, metadata/price
  conflicts, role denial before provider calls and retries after partial failures.
- The three inherited failures remain promo active validation, organization
  default tier, and concurrent membership addition; this is not a green legacy suite.
- Final full run log: `/tmp/astra-billing-release-suite.log` on bigboy.

## Remaining release gates

The orchestrator owns deployment and dogfood verification. No live Stripe/Lago,
Postgres/Redis integration, or deployed browser verification is claimed here.
Confirm real membership roles and active price mappings in the deployment ring.
Untagged/conflicting legacy Stripe customers and email-keyed Lago records require
explicit reconciliation; no migration or customer mutation is included.
Latest-state retrieval reduces stale-event replay but adds no distributed lock
for concurrently executing webhooks. Trial/past-due grace behavior is preserved.
Dedicated system-admin configuration/provisioning policy is not broadened by this
user-facing mutation change. Unrelated `.env.test.example` and `.venv311` are
preserved, and no local orchestrator draft or checkout UI files are touched.
