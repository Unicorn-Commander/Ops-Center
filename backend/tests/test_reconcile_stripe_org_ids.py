"""Fake-only coverage for the standalone Stripe organization reconciler."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType, SimpleNamespace

import pytest


BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "reconcile_stripe_org_ids.py"
ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


class FakeStripeState:
    def __init__(self):
        self.customers = {
            "cus_ok": {
                "id": "cus_ok",
                "email": "ok@example.com",
                "metadata": {"org_id": f"org_{ORG_A}"},
            },
            "cus_meeting": {
                "id": "cus_meeting",
                "email": "meeting@example.com",
                "metadata": {"meeting_ops_user_id": "meeting-user"},
            },
            "cus_other": {
                "id": "cus_other",
                "email": "other@example.com",
                "metadata": {},
            },
            "cus_owner": {
                "id": "cus_owner",
                "email": "owner@example.com",
                "metadata": {},
            },
            "cus_ambiguous": {
                "id": "cus_ambiguous",
                "email": "ambiguous@example.com",
                "metadata": {},
            },
        }
        self.subscriptions = {
            "cus_ok": [self.subscription("cus_ok", "unicorn-commander")],
            "cus_meeting": [self.subscription("cus_meeting", "unicorn-commander")],
            "cus_other": [self.subscription("cus_other", "meeting-ops")],
            "cus_owner": [self.subscription("cus_owner", "unicorn-commander")],
            "cus_ambiguous": [
                self.subscription("cus_ambiguous", "unicorn-commander")
            ],
        }
        self.sessions = {customer_id: [] for customer_id in self.customers}
        self.modify_calls = []

    @staticmethod
    def subscription(customer_id, suite, status="active"):
        return {
            "id": f"sub_{customer_id}",
            "customer": customer_id,
            "status": status,
            "metadata": {"suite": suite},
        }


class FakeOpsConnection:
    def __init__(self, state):
        self.state = state
        self.updates = []
        self.closed = False

    async def fetch(self, query, *params):
        if "SELECT id::text AS id, status, stripe_customer_id" in query:
            return [
                {"id": ORG_A, "status": "active", "stripe_customer_id": None},
                {"id": ORG_B, "status": "active", "stripe_customer_id": None},
            ]
        if "FROM organization_members" in query:
            orgs = {
                "kc-owner": [ORG_A],
                "kc-ambiguous-a": [ORG_A],
                "kc-ambiguous-b": [ORG_B],
            }
            result = []
            for user_id in params[0]:
                result.extend({"org_id": org_id} for org_id in orgs.get(user_id, []))
            return result
        raise AssertionError(f"unexpected Ops-Center query: {query}")

    async def execute(self, query, *params):
        assert "UPDATE organizations" in query
        self.updates.append(params)
        return "UPDATE 1"

    async def close(self):
        self.closed = True


class FakeKeycloakConnection:
    def __init__(self):
        self.closed = False

    async def fetch(self, query, *params):
        assert "lower(ue.email) = lower($2)" in query
        users = {
            "owner@example.com": ["kc-owner"],
            "ambiguous@example.com": ["kc-ambiguous-a", "kc-ambiguous-b"],
        }
        return [{"id": user_id} for user_id in users.get(params[1], [])]

    async def close(self):
        self.closed = True


@pytest.fixture
def reconciler_module(monkeypatch):
    state = FakeStripeState()
    ops_connections = []
    keycloak_connections = []

    class Customer:
        @staticmethod
        def list(**kwargs):
            assert kwargs == {"limit": 100}
            return SimpleNamespace(data=list(state.customers.values()))

        @staticmethod
        def retrieve(customer_id):
            return state.customers[customer_id]

        @staticmethod
        def modify(customer_id, **kwargs):
            state.modify_calls.append((customer_id, kwargs))
            state.customers[customer_id]["metadata"].update(kwargs["metadata"])
            return state.customers[customer_id]

    class Subscription:
        @staticmethod
        def list(**kwargs):
            return SimpleNamespace(data=state.subscriptions.get(kwargs["customer"], []))

    class Session:
        @staticmethod
        def list(**kwargs):
            return SimpleNamespace(data=state.sessions.get(kwargs["customer"], []))

    fake_stripe = ModuleType("stripe")
    fake_stripe.Customer = Customer
    fake_stripe.Subscription = Subscription
    fake_stripe.checkout = SimpleNamespace(Session=Session)
    fake_stripe.error = SimpleNamespace(StripeError=RuntimeError)

    fake_asyncpg = ModuleType("asyncpg")

    async def connect(*args, **kwargs):
        if args:
            connection = FakeKeycloakConnection()
            keycloak_connections.append(connection)
            return connection
        connection = FakeOpsConnection(state)
        ops_connections.append(connection)
        return connection

    fake_asyncpg.connect = connect
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)
    monkeypatch.setenv("KEYCLOAK_DATABASE_URL", "postgresql://keycloak.example.test/fixture")
    monkeypatch.setenv("OPS_CENTER_STRIPE_SUITE", "unicorn-commander")

    spec = importlib.util.spec_from_file_location("reconcile_fixture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._fixture_state = state
    module._fixture_ops_connections = ops_connections
    module._fixture_keycloak_connections = keycloak_connections
    return module


def test_standalone_dry_run_counts_and_id_only_plan(
    reconciler_module, tmp_path, capsys
):
    plan_path = tmp_path / "plan.json"

    assert reconciler_module.main(["--dry-run", "--plan-out", str(plan_path)]) == 0

    stdout = capsys.readouterr().out
    assert stdout == (
        "customers_total=5 in_scope=3 ok=1 bad_tag=2 "
        "meeting_ops_skipped=1 other_suite_skipped=1 to_tag=1 "
        "ambiguous=1 unresolved=0\n"
    )
    assert "@" not in stdout
    rows = json.loads(plan_path.read_text())
    assert {row["customer_id"] for row in rows} == {"cus_owner", "cus_ambiguous"}
    assert all(set(row) == {"customer_id", "org_id", "rule"} for row in rows)
    assert all("@" not in json.dumps(row) for row in rows)
    assert stat.S_IMODE(plan_path.stat().st_mode) == 0o600


def test_apply_refuses_unsafe_rows_without_only_and_is_idempotent(
    reconciler_module, tmp_path, capsys
):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            [
                {
                    "customer_id": "cus_owner",
                    "org_id": ORG_A,
                    "rule": "email_membership",
                },
                {"customer_id": "cus_ambiguous", "org_id": None, "rule": "ambiguous"},
            ]
        )
    )

    assert reconciler_module.main(["--apply", "--plan", str(plan_path)]) == 1
    assert reconciler_module._fixture_state.modify_calls == []
    capsys.readouterr()

    only = ["--apply", "--plan", str(plan_path), "--only", "cus_owner"]
    assert reconciler_module.main(only) == 0
    assert reconciler_module.main(only) == 0

    assert len(reconciler_module._fixture_state.modify_calls) == 1
    customer_id, kwargs = reconciler_module._fixture_state.modify_calls[0]
    assert customer_id == "cus_owner"
    assert kwargs["metadata"] == {"org_id": f"org_{ORG_A}"}
    assert kwargs["idempotency_key"] == f"oc-reconcile-cus_owner-{ORG_A}"
    assert len(reconciler_module._fixture_ops_connections[-1].updates) == 1


def test_script_has_no_application_imports():
    source = SCRIPT.read_text()
    assert "from org_api" not in source
    assert "from stripe_integration" not in source
    assert "from get_credential" not in source


def test_stripe_object_metadata_is_read_without_dict_get(reconciler_module):
    class StripeLikeMetadata:
        _data = {"suite": "unicorn-commander", "org_id": ORG_A}

        def keys(self):
            return self._data.keys()

        def __getitem__(self, key):
            return self._data[key]

    class StripeLikeCustomer:
        metadata = StripeLikeMetadata()

    assert reconciler_module._metadata(StripeLikeCustomer()) == {
        "suite": "unicorn-commander",
        "org_id": ORG_A,
    }
