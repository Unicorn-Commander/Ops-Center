"""Autouse fixture for the home-state tests: a clean, fictional HOME_* environment.

Helpers live in ``homekit.py`` (a plain module, so importing them is never
ambiguous with ``backend/tests/conftest.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from homekit import API_HOSTS, HOME_ENV, WEB_HOSTS  # noqa: E402


@pytest.fixture(autouse=True)
def clean_home_env(monkeypatch):
    for name in HOME_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in {**API_HOSTS, **WEB_HOSTS}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HOME_APP_TIMEOUT_SECONDS", "1.0")
    monkeypatch.setenv("HOME_TOTAL_BUDGET_SECONDS", "3.0")
    yield


@pytest.fixture(autouse=True)
def no_real_session_store(monkeypatch):
    """A token refresh never reaches the real Redis session store (and so never
    Keycloak): it finds no store unless a test installs its fake one."""

    from home import session_tokens

    monkeypatch.setattr(session_tokens, "default_store", lambda: None)
    yield
