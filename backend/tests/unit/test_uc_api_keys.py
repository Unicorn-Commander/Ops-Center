"""Tests for the flag-gated signup/onboarding UC API-key step."""

import asyncio
from datetime import datetime
from uuid import uuid4

import bcrypt
import pytest

import uc_api_keys


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _Connection:
    def __init__(self, plan_row=None):
        self.plan_row = plan_row
        self.rows = []
        self.execute_calls = []

    def transaction(self):
        return _Transaction()

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "SELECT 1"

    async def fetchrow(self, query, *args):
        if "FROM organization_members" in query:
            return self.plan_row

        if "INSERT INTO user_api_keys" in query:
            key_hash = args[2]
            key_prefix = args[3]
            created_at = datetime.utcnow()
            row = {
                "id": uuid4(),
                "user_id": args[0],
                "key_name": args[1],
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "permissions": list(uc_api_keys.DEFAULT_UC_KEY_PERMISSIONS),
                "created_at": created_at,
                "expires_at": args[5],
            }
            self.rows.append(row)
            return {"id": row["id"], "created_at": created_at}

        if "FROM user_api_keys" in query:
            return next(
                (
                    row
                    for row in self.rows
                    if row["key_name"] == args[1] and row["user_id"] == args[0]
                ),
                None,
            )

        raise AssertionError(f"Unexpected query: {query}")


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _Pool:
    def __init__(self, plan_row=None):
        self.connection = _Connection(plan_row=plan_row)

    def acquire(self):
        return _Acquire(self.connection)


def _run(coro):
    return asyncio.run(coro)


def test_first_and_second_onboarding_calls_mint_exactly_one_key(monkeypatch, caplog):
    monkeypatch.setenv(uc_api_keys.AUTO_PROVISION_DEFAULT_UC_API_KEY_ENV, "true")
    pool = _Pool()
    user = {"user_id": "user-123", "subscription_tier": "starter"}

    with caplog.at_level("INFO", logger=uc_api_keys.logger.name):
        first = _run(uc_api_keys.ensure_default_uc_api_key(user, pool))
        second = _run(uc_api_keys.ensure_default_uc_api_key(user, pool))

    assert first.enabled is True
    assert first.eligible is True
    assert first.created is True
    assert first.api_key and first.api_key.startswith("uc_")
    assert second.enabled is True
    assert second.eligible is True
    assert second.created is False
    assert second.api_key is None
    assert second.reason == "already_provisioned"
    assert len(pool.connection.rows) == 1
    assert first.api_key not in caplog.text


def test_default_key_is_bcrypt_hashed_at_rest(monkeypatch):
    monkeypatch.setenv(uc_api_keys.AUTO_PROVISION_DEFAULT_UC_API_KEY_ENV, "1")
    pool = _Pool()

    result = _run(
        uc_api_keys.ensure_default_uc_api_key(
            {"user_id": "user-123", "subscription_tier": "professional"},
            pool,
        )
    )

    stored = pool.connection.rows[0]
    assert stored["key_hash"].startswith("$2")
    assert bcrypt.checkpw(result.api_key.encode(), stored["key_hash"].encode())
    assert result.api_key not in stored["key_hash"]
    assert stored["permissions"] == uc_api_keys.DEFAULT_UC_KEY_PERMISSIONS


def test_disabled_flag_does_not_mint(monkeypatch):
    monkeypatch.delenv(uc_api_keys.AUTO_PROVISION_DEFAULT_UC_API_KEY_ENV, raising=False)
    pool = _Pool()

    result = _run(
        uc_api_keys.ensure_default_uc_api_key(
            {"user_id": "user-123", "subscription_tier": "starter"},
            pool,
        )
    )

    assert result.enabled is False
    assert result.created is False
    assert result.reason == "feature_disabled"
    assert pool.connection.rows == []


def test_unentitled_plan_does_not_mint(monkeypatch):
    monkeypatch.setenv(uc_api_keys.AUTO_PROVISION_DEFAULT_UC_API_KEY_ENV, "true")
    pool = _Pool()

    result = _run(
        uc_api_keys.ensure_default_uc_api_key(
            {"user_id": "user-123", "subscription_tier": "trial"},
            pool,
        )
    )

    assert result.enabled is True
    assert result.eligible is False
    assert result.created is False
    assert result.api_key is None
    assert result.reason == "plan_not_entitled"
    assert pool.connection.rows == []


@pytest.mark.parametrize(
    ("tier", "api_calls_limit", "expected"),
    [
        ("free", None, False),
        ("trial", 700, False),
        ("custom", 0, False),
        ("custom", -1, True),
        ("starter", None, True),
    ],
)
def test_plan_gate_matches_existing_api_access_boundary(
    tier, api_calls_limit, expected
):
    assert uc_api_keys.plan_allows_default_uc_api_key(tier, api_calls_limit) is expected


def test_step_one_point_five_endpoint_is_registered():
    assert any(
        route.path == "/api/v1/account/uc-api-keys/ensure-default"
        and "POST" in route.methods
        for route in uc_api_keys.router.routes
    )
