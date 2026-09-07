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

## Registered-route follow-up (2026-09-07)

The initial commit did not cover the canonical registered Stripe dispatcher or
all customer-management callers. The follow-up traces `server.py` registrations
and the BillingDashboard, OrganizationBilling, SubscriptionPlan, PaymentMethods,
AddPaymentMethodDialog and UpcomingInvoiceCard callers. The actual route surfaces
now share the org boundary:

- `/api/v1/webhooks/stripe`: paid checkout and cancellation resolve the event's
  Stripe customer, require its canonical org metadata and reject conflicting
  event metadata. They never query current Keycloak org by email. The checkout
  and subscription-updated compatibility aliases delegate to this dispatcher.
- `/api/v1/billing`: portal, payment methods, subscription status/cancel/upgrade
  select the org's Stripe customer. Subscription metadata and customer references
  must agree; multiple active subscriptions and truncated history fail closed.
- `/api/v1/payment-methods`: all seven routes use org-scoped lookup. Details,
  default and detach validate payment-method ownership before exposing/mutating
  it; SetupIntent org metadata overrides untrusted input.
- `/api/v1/billing` invoices/cycle/summary/PDF/retry and Lago read helpers no longer
  fall back to email. PDF/retry require the selected org even for an admin.
- `/api/v1/subscriptions/confirm-upgrade` verifies suite, payment and event/customer
  identity against the selected org before idempotent paid-org provisioning.
  It cannot provision org B using a paid checkout from org A.

The two Stripe webhook functions in stripe_api.py are undecorated legacy callables
at this baseline, not registered webhook routes; they now delegate to the canonical
handler as well. The first subscription `/upgrade` route is a payment-required
guard and shadows a later duplicate. Tests now mount the actual imported routers,
rather than relying only on extracted functions. The dormant
`StripeIntegration.process_webhook_event` and private email-oriented lifecycle
methods have no production callers in this checkout and were not expanded into
another active dispatch path.

Customer search treats bare UUID and `org_<uuid>` metadata as equivalent and
rejects duplicates across either form. Provider lookup failures return 503;
subscription history beyond the requested 100 records returns 409 rather than
making an ownership/uniqueness decision on an incomplete page. Explicit partial
provisioning failures return 503 for retry, including failed Lago subscription
creation and failed application of a finite cloud cap.

Follow-up results: 122 passed / 3 baseline failures before; 219 passed / the same
3 failures after. This adds 97 passing regressions: 48 actual canonical/billing
router cases, 23 payment-method cases, 20 invoice/helper cases, and 6 customer/
subscription lookup cases. Representative pre-fix runs recorded 32 failures in
the first 33 canonical/billing route cases, 18 payment-method failures, and 20
billing-read failures. Tests use the unchanged runner above; all provider/DB calls
are mocked and no live billing/customer mutations occurred. Existing loopback
payload tests remain included. All changed Python modules compile and diff checks
pass. The full service-free run log is
`/tmp/ops-center-astra-route-full-tests.log` on bigboy.

Current rollout limits supersede the initial event-metadata note: a legacy event
without org metadata may use a uniquely org-tagged Stripe customer; untagged or
conflicting customer/event metadata requires explicit reconciliation. Legacy
email-keyed Lago records remain inaccessible through org-scoped reads. Admin
invoice actions now require org selection. Subscription-updated aliases no longer
write email-wide Keycloak tiers; checkout and cancellation drive org provisioning.
No deployed endpoint/browser, real Stripe/Lago, Postgres or Redis verification is
claimed. Deployment and dogfood verification remain with the orchestrator.
