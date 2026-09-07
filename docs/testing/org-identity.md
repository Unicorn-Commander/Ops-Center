# Billing organization identity verification

This change uses the trusted server-side session/user org ID (including Keycloak
attributes), or the sole active persisted membership for the authenticated subject.
Membership resolution includes both the subject directly and its `"user".oauth_sub`
to local primary-key mapping. `user_org_access` is a view over the same
`organization_members` rows. It never resolves a tenant by email or creates an ID.
Ambiguous/conflicting identity requires organization selection (409); membership
lookup failure returns 503. A bare UUID and `org_<uuid>` normalize to the same Lago
external customer ID.

Both checkout callers capture that identity in Stripe session and subscription
metadata. Stripe customer lookup is scoped by org metadata; customer creation uses
an org-scoped idempotency key. Completed checkout uses the captured org, and failed
synchronization is returned as an error so Stripe can retry. Lago POST retries keep
the same external ID; Stripe customer ID remains in billing configuration.

## Run without services

On bigboy, Python 3.12 could not build the pinned dependency set (`distutils` error).
The installed Python 3.11 successfully installed the unchanged requirements:

```sh
python3.11 -m venv .venv311
.venv311/bin/pip install -r backend/requirements.txt pytest pytest-asyncio
.venv311/bin/python backend/tests/run_billing_identity_tests.py
```

The runner redirects the legacy org-manager singleton's import-time `/app/data`
path to temporary storage. It explicitly selects backend pytest configuration and
clears its default addopts: existing Stripe tests use unregistered markers, and
coverage is unnecessary for this bounded pass. It starts no application services and reads no
production credentials; one regression owns a temporary loopback HTTP test fixture. The new tests isolate import-time credential access and
use mocked membership, Stripe, and Lago operations. Route helpers/callers are loaded
from their actual source via AST to avoid unrelated application startup effects.

For just the new regressions:

```sh
PYTHONPATH=backend .venv311/bin/python -m pytest -c backend/pytest.ini -o addopts= backend/tests/unit/test_billing_org_identity.py
```

## Results on 2026-09-07

- Baseline at `0a7968b8092bd0ae2c6de743b8f6aa1e11dc2288`: 93 passed, 3 failed.
- Fabrication reproduction before implementation: 2 failed (one per route helper).
- After implementation: 122 passed, the same 3 failed; all 29 new regressions pass.
- Existing failures: promo-code active validation, organization default tier, and
  concurrent membership addition. These are outside this identity change.
- HTTP verification uses FastAPI and HTTPX ASGI transport: missing org returns 409;
  a selected org returns 200 with its canonical ID despite another query-string org.
  This is in-process verification, not a deployed endpoint or browser inspection.
  A test-owned loopback HTTP server also receives two actual Lago POST requests
  and verifies their serialized canonical external IDs and Stripe billing linkage.
- PostgreSQL/Redis integration tests were deliberately not run. The fallback SQL
  was reviewed against the checked-in schema/view; no live DB verification occurred.

## Review and rollout limits

No deploy or existing-customer migration is included. Old checkout events without
org metadata now fail closed. Existing Stripe customers without canonical org
metadata are not inferred from email; review legacy customer linkage before rollout.
The fallback cannot repair orphan membership rows that match neither the subject
nor its mapped local user ID. Dogfood verification against real uchub membership,
Stripe, and Lago remains for the deployment owner.
