"""Concurrent admin-token requests must share one Keycloak login (prod lockout 2026-11-07)."""
import asyncio
from datetime import datetime, timedelta
import pytest
import keycloak_integration as kc


@pytest.mark.asyncio
async def test_concurrent_callers_make_one_login(monkeypatch):
    kc._admin_token_cache["token"] = None
    kc._admin_token_cache["expires_at"] = None
    kc._admin_token_lock = None
    calls = []

    async def fake_fetch():
        calls.append(1)
        await asyncio.sleep(0.01)
        kc._admin_token_cache["token"] = "tok-1"
        kc._admin_token_cache["expires_at"] = datetime.now() + timedelta(minutes=4)
        return "tok-1"

    monkeypatch.setattr(kc, "_fetch_admin_token", fake_fetch)
    tokens = await asyncio.gather(*(kc.get_admin_token() for _ in range(8)))
    assert tokens == ["tok-1"] * 8
    assert len(calls) == 1
    assert await kc.get_admin_token() == "tok-1" and len(calls) == 1


@pytest.mark.asyncio
async def test_expired_cache_refreshes_once(monkeypatch):
    kc._admin_token_cache["token"] = "old"
    kc._admin_token_cache["expires_at"] = datetime.now() - timedelta(seconds=1)
    kc._admin_token_lock = None
    calls = []

    async def fake_fetch():
        calls.append(1)
        kc._admin_token_cache["token"] = "new"
        kc._admin_token_cache["expires_at"] = datetime.now() + timedelta(minutes=4)
        return "new"

    monkeypatch.setattr(kc, "_fetch_admin_token", fake_fetch)
    assert await asyncio.gather(kc.get_admin_token(), kc.get_admin_token()) == ["new", "new"]
    assert len(calls) == 1
