#!/usr/bin/env python3
"""Reconcile Stripe customer organization metadata before the Ops-Center cutover.

This file deliberately has no imports from the application. It is copied into
the old production container and run there with only the Stripe and asyncpg
packages available.
"""

import argparse
import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
import sys
import uuid

import asyncpg
import stripe


COUNT_KEYS = (
    "customers_total",
    "in_scope",
    "ok",
    "bad_tag",
    "meeting_ops_skipped",
    "other_suite_skipped",
    "to_tag",
    "ambiguous",
    "unresolved",
)
TARGET_ROLES = ("owner", "admin", "billing_admin")
EXCLUDED_SUBSCRIPTION_STATUSES = {"canceled", "incomplete_expired"}


def _field(value, name, default=None):
    """Read a field from either a Stripe object or a plain fake/dict."""
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _metadata(value):
    value = _field(value, "metadata", {})
    if isinstance(value, Mapping):
        return value
    data = getattr(value, "_data", None)
    if isinstance(data, Mapping):
        return data
    try:
        return {key: value[key] for key in value.keys()}
    except (AttributeError, KeyError, TypeError):
        return {}


def _bare_org_id(value):
    """Return a normalized bare UUID for bare or ``org_`` values."""
    if value is None:
        return None
    candidate = str(value).strip()
    if candidate.lower().startswith("org_"):
        candidate = candidate[4:]
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError, TypeError):
        return None


def _stripe_org_id(org_id):
    return f"org_{org_id}"


def _stripe_list(resource, **kwargs):
    result = resource.list(**kwargs)
    auto_paging_iter = getattr(result, "auto_paging_iter", None)
    if callable(auto_paging_iter):
        return list(auto_paging_iter())
    data = _field(result, "data", result)
    return list(data or [])


def _safe_stripe_error(exc):
    code = getattr(exc, "code", None) or "unknown"
    text = str(code)
    for marker in ("sk_", "rk_", "pk_", "whsec_"):
        text = text.replace(marker, "[redacted]")
    return f"{type(exc).__name__} code={text}"


def _postgres_kwargs():
    return {
        "host": os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", "unicorn"),
        "password": os.getenv("POSTGRES_PASSWORD", "unicorn"),
        "database": os.getenv("POSTGRES_DB", "unicorn_db"),
    }


def _default_plan_path():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"/tmp/oc-reconcile-plan-{timestamp}.json"


def _write_plan(path, rows):
    """Write an ID-only plan with owner-readable permissions."""
    payload = json.dumps(rows, sort_keys=True, indent=2) + "\n"
    file_descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as plan_file:
            file_descriptor = None
            plan_file.write(payload)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
    os.chmod(path, 0o600)


def _load_plan(path):
    with open(path, encoding="utf-8") as plan_file:
        payload = json.load(plan_file)
    rows = payload.get("rows") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        raise ValueError("plan must contain a list of rows")
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"customer_id", "org_id", "rule"}:
            raise ValueError("plan rows must contain customer_id, org_id and rule only")
    return rows


class Reconciler:
    def __init__(self, suite):
        self.suite = suite
        self.pg = None
        self.keycloak = None
        self.organizations = {}
        self.organizations_by_customer = {}

    async def open(self):
        self.pg = await asyncpg.connect(**_postgres_kwargs())
        rows = await self.pg.fetch(
            """
            SELECT id::text AS id, status, stripe_customer_id
            FROM organizations
            """
        )
        for row in rows:
            org_id = _bare_org_id(_field(row, "id"))
            if not org_id:
                continue
            customer_id = _field(row, "stripe_customer_id")
            customer_id = str(customer_id) if customer_id else None
            self.organizations[org_id] = {
                "status": str(_field(row, "status", "")),
                "stripe_customer_id": customer_id,
            }
            if customer_id:
                self.organizations_by_customer.setdefault(customer_id, []).append(org_id)
        for customer_ids in self.organizations_by_customer.values():
            customer_ids.sort()

    async def close(self):
        if self.keycloak is not None:
            await self.keycloak.close()
            self.keycloak = None
        if self.pg is not None:
            await self.pg.close()
            self.pg = None

    def _active_org(self, org_id):
        record = self.organizations.get(org_id)
        return record if record and record["status"].lower() == "active" else None

    async def _keycloak_user_ids(self, email):
        if not email:
            return []
        if self.keycloak is None:
            keycloak_dsn = os.getenv("KEYCLOAK_DATABASE_URL", "")
            if not keycloak_dsn:
                return []
            self.keycloak = await asyncpg.connect(keycloak_dsn)
        rows = await self.keycloak.fetch(
            """
            SELECT ue.id::text AS id
            FROM user_entity AS ue
            JOIN realm AS r ON r.id = ue.realm_id
            WHERE r.name = $1
              AND lower(ue.email) = lower($2)
            """,
            os.getenv("KEYCLOAK_REALM", "uchub"),
            email,
        )
        return sorted({str(_field(row, "id")) for row in rows if _field(row, "id")})

    async def _membership_org_ids(self, user_ids):
        if not user_ids:
            return []
        rows = await self.pg.fetch(
            """
            SELECT DISTINCT om.org_id::text AS org_id
            FROM organization_members AS om
            JOIN organizations AS o ON o.id = om.org_id
            WHERE om.user_id = ANY($1::text[])
              AND om.role = ANY($2::text[])
              AND o.status = 'active'
            """,
            list(user_ids),
            list(TARGET_ROLES),
        )
        return sorted(
            {
                org_id
                for org_id in (_bare_org_id(_field(row, "org_id")) for row in rows)
                if org_id and self._active_org(org_id)
            }
        )

    async def _resolve(self, customer_id, customer, subscriptions, sessions):
        for org_id in self.organizations_by_customer.get(customer_id, []):
            if self._active_org(org_id):
                return org_id, "organization.stripe_customer_id", None

        for subscription in subscriptions:
            org_id = _bare_org_id(_metadata(subscription).get("org_id"))
            if org_id and self._active_org(org_id):
                return org_id, "subscription.metadata.org_id", None

        for session in sessions:
            org_id = _bare_org_id(_metadata(session).get("org_id"))
            if org_id and self._active_org(org_id):
                return org_id, "checkout_session.metadata.org_id", None

        email = _field(customer, "email")
        user_ids = await self._keycloak_user_ids(email)
        org_ids = await self._membership_org_ids(user_ids)
        if len(org_ids) == 1:
            return org_ids[0], "email_membership", None
        if len(org_ids) > 1:
            return None, "ambiguous", "ambiguous"
        return None, "unresolved", "unresolved"

    async def _customer_context(self, customer):
        customer_id = str(_field(customer, "id"))
        subscriptions = _stripe_list(
            stripe.Subscription,
            customer=customer_id,
            status="all",
            limit=100,
        )
        other_suite_subscription = any(
            _metadata(subscription).get("suite")
            and _metadata(subscription).get("suite") != self.suite
            for subscription in subscriptions
        )
        if other_suite_subscription:
            return "other_suite_skipped", None

        sessions = _stripe_list(
            stripe.checkout.Session,
            customer=customer_id,
            status="complete",
            limit=100,
        )
        sessions = [
            session
            for session in sessions
            if (
                not _field(session, "status")
                or _field(session, "status") == "complete"
            )
        ]
        suite_subscriptions = [
            subscription
            for subscription in subscriptions
            if _metadata(subscription).get("suite") == self.suite
            and _field(subscription, "status") not in EXCLUDED_SUBSCRIPTION_STATUSES
        ]
        suite_sessions = [
            session
            for session in sessions
            if _metadata(session).get("suite") == self.suite
        ]
        has_org_customer = bool(self.organizations_by_customer.get(customer_id))
        if not suite_subscriptions and not suite_sessions and not has_org_customer:
            return "out_of_scope", None

        metadata = _metadata(customer)
        tagged_org_id = _bare_org_id(metadata.get("org_id"))
        if tagged_org_id and self._active_org(tagged_org_id):
            return "ok", None

        org_id, rule, status = await self._resolve(
            customer_id,
            customer,
            suite_subscriptions,
            suite_sessions,
        )
        if status == "ambiguous":
            return "ambiguous", {
                "customer_id": customer_id,
                "org_id": None,
                "rule": "ambiguous",
            }
        if status == "unresolved":
            return "unresolved", {
                "customer_id": customer_id,
                "org_id": None,
                "rule": "unresolved",
            }
        if metadata.get("org_id"):
            rule = f"bad_tag:{rule}"
        return "to_tag", {
            "customer_id": customer_id,
            "org_id": org_id,
            "rule": rule,
        }

    async def dry_run(self):
        counts = {key: 0 for key in COUNT_KEYS}
        plan_rows = []
        customers = _stripe_list(stripe.Customer, limit=100)
        counts["customers_total"] = len(customers)
        await self.open()
        try:
            for customer in customers:
                metadata = _metadata(customer)
                if metadata.get("meeting_ops_user_id"):
                    counts["meeting_ops_skipped"] += 1
                    continue
                status, row = await self._customer_context(customer)
                if status == "other_suite_skipped":
                    counts["other_suite_skipped"] += 1
                    continue
                if status == "out_of_scope":
                    continue
                counts["in_scope"] += 1
                if status == "ok":
                    counts["ok"] += 1
                    continue
                counts["bad_tag"] += 1
                if status == "to_tag":
                    counts["to_tag"] += 1
                elif status == "ambiguous":
                    counts["ambiguous"] += 1
                elif status == "unresolved":
                    counts["unresolved"] += 1
                plan_rows.append(row)
        finally:
            await self.close()
        return counts, plan_rows

    async def _retrieve_customer(self, customer_id):
        return stripe.Customer.retrieve(customer_id)

    async def apply(self, rows):
        await self.open()
        try:
            for row in rows:
                customer_id = str(row["customer_id"])
                org_id = _bare_org_id(row["org_id"])
                if not customer_id or not org_id:
                    raise ValueError("plan row has no actionable organization")
                if not self._active_org(org_id):
                    raise ValueError("plan organization is no longer active")
                customer = await self._retrieve_customer(customer_id)
                current_raw_org_id = _metadata(customer).get("org_id")
                current_org_id = _bare_org_id(current_raw_org_id)
                if current_raw_org_id and current_org_id != org_id:
                    raise ValueError("customer already has a different organization tag")
                if current_org_id != org_id:
                    stripe.Customer.modify(
                        customer_id,
                        metadata={"org_id": _stripe_org_id(org_id)},
                        idempotency_key=f"oc-reconcile-{customer_id}-{org_id}",
                    )
                await self.pg.execute(
                    """
                    UPDATE organizations
                    SET stripe_customer_id = $1
                    WHERE id = $2 AND stripe_customer_id IS NULL
                    """,
                    customer_id,
                    org_id,
                )
        finally:
            await self.close()


def _build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report counts and write a plan")
    parser.add_argument("--plan-out", default=None, help="0600 JSON path for the dry-run plan")
    parser.add_argument("--apply", action="store_true", help="apply a previously written plan")
    parser.add_argument("--plan", help="JSON plan path for --apply")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="apply only this customer ID; may be repeated",
    )
    return parser


async def _run(args):
    suite = os.getenv("OPS_CENTER_STRIPE_SUITE", "unicorn-commander")
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if args.apply:
        if not args.plan:
            raise ValueError("--apply requires --plan")
        rows = _load_plan(args.plan)
        selected = (
            [row for row in rows if row["customer_id"] in set(args.only)]
            if args.only
            else rows
        )
        if not args.only:
            blocked = [
                row
                for row in rows
                if str(row["rule"]).lower().startswith(("ambiguous", "unresolved", "bad_tag"))
            ]
            if blocked:
                raise ValueError("plan contains unresolved, ambiguous or bad_tag rows")
        reconciler = Reconciler(suite)
        await reconciler.apply(selected)
        return 0

    reconciler = Reconciler(suite)
    counts, rows = await reconciler.dry_run()
    _write_plan(args.plan_out or _default_plan_path(), rows)
    print(" ".join(f"{key}={counts[key]}" for key in COUNT_KEYS))
    return 0


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except stripe.error.StripeError as exc:
        print(_safe_stripe_error(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
