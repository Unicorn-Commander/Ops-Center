"""Focused regression tests for the founder workspace tier wiring."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from my_apps_api import get_user_tier_features
import org_api
from pricing_packages_api import PUBLIC_TIER_CODES
from usage_tracking import UsageTracker


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations" / "add_founder_workspace_tier_20261105.sql"
WIRING_SCRIPT = BACKEND / "scripts" / "wire_founder_workspace_prices.py"


class _FeatureConn:
    async def fetchrow(self, query, *params):
        assert "subscription_tiers" in query
        assert params == ("founder_workspace",)
        return {"id": 42}

    async def fetch(self, query, *params):
        assert "tier_features" in query
        assert params == (42,)
        return [{"feature_key": "chat_access"}, {"feature_key": "search_enabled"}]


class _MemberConn:
    def __init__(self):
        self.insert_count = 0
        self.closed = False

    async def fetchval(self, query, *params):
        assert "COUNT(*)" in query
        assert params == ("00000000-0000-4000-8000-000000000001",)
        if "organization_invitations" in query:
            return 0
        return 5

    async def fetchrow(self, query, *params):
        return None

    async def execute(self, query, *params):
        if "INSERT INTO organization_members" in query:
            self.insert_count += 1

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_founder_workspace_is_accepted_by_my_apps_entitlements():
    features = await get_user_tier_features("founder_workspace", _FeatureConn())
    assert features == {"chat_access", "search_enabled"}


@pytest.mark.asyncio
async def test_founder_workspace_rejects_sixth_member(monkeypatch):
    conn = _MemberConn()

    async def allow_owner(*args, **kwargs):
        return None

    async def org_row(*args, **kwargs):
        return {
            "plan_tier": "founder_workspace",
            "tier_name": "Team workspace",
            "seat_cap": 5,
        }

    async def no_existing_member(*args, **kwargs):
        return None

    async def owner(*args, **kwargs):
        return {"id": "fictional-owner", "email": "owner@example.com", "role": "user"}

    async def connection():
        return conn

    monkeypatch.setattr(org_api, "verify_org_access", allow_owner)
    monkeypatch.setattr(org_api, "get_current_user", owner)
    monkeypatch.setattr(org_api, "_get_org_row", org_row)
    monkeypatch.setattr(org_api, "_get_user_role_in_org", no_existing_member)
    monkeypatch.setattr(org_api, "get_db_connection", connection)

    response = await org_api.add_organization_member(
        "00000000-0000-4000-8000-000000000001",
        org_api.OrganizationMemberAdd(email="member-6@example.com"),
        object(),
    )

    assert response.status_code == 402
    assert json.loads(response.body) == {
        "detail": "Organization has reached its seat limit (5/5).",
        "seats_used": 5,
        "max_seats": 5,
        "add_seat_url": "/api/v1/billing/seats",
    }
    assert conn.insert_count == 0
    assert conn.closed is True


def test_founder_workspace_is_in_public_catalog_and_uses_byok_usage_limits():
    assert PUBLIC_TIER_CODES == ["free", "app", "byok", "founder_workspace", "managed"]
    assert UsageTracker.TIER_LIMITS["founder_workspace"] == {
        "daily_limit": -1,
        "monthly_limit": -1,
        "reset_period": "monthly",
    }


def test_migration_copies_byok_features_and_is_idempotent():
    sql = MIGRATION.read_text()
    assert "ON CONFLICT (tier_code) DO NOTHING" in sql
    assert "FROM subscription_tiers AS byok" in sql
    assert "JOIN tier_features AS byok_feature" in sql
    assert "ON CONFLICT (tier_id, feature_key) DO UPDATE" in sql
    assert "'founder_workspace'" in sql
    assert "149.00" in sql
    assert "NULL" in sql


def _load_wiring_script(monkeypatch):
    calls = []
    fake_stripe = ModuleType("stripe")

    class FakePrice:
        @staticmethod
        def list(**kwargs):
            calls.append(kwargs)
            lookup_key = kwargs["lookup_keys"][0]
            price_id = (
                "price_fixture_monthly"
                if lookup_key == "founder_workspace_monthly"
                else "price_fixture_seat"
            )
            return SimpleNamespace(data=[SimpleNamespace(id=price_id)])

    fake_stripe.Price = FakePrice
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    spec = importlib.util.spec_from_file_location("wire_founder_workspace_prices", WIRING_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls


def test_wiring_script_dry_run_resolves_lookup_keys_without_writes(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "fixture-only")
    module, calls = _load_wiring_script(monkeypatch)

    module.main([])

    output = capsys.readouterr().out
    assert "Dry run: no database writes will be made." in output
    assert "price_fixture_monthly" in output
    assert "price_fixture_seat" in output
    assert "fixture-only" not in output
    assert [call["lookup_keys"] for call in calls] == [
        ["founder_workspace_monthly"],
        ["founder_workspace_seat_monthly"],
    ]
