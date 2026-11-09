"""Address safety and per-ring host settings."""

from __future__ import annotations

import pytest

from home import settings
from home.safety import WITHHELD, guard_document, is_off_ring, is_private_host, public_origin, public_url


@pytest.mark.parametrize(
    "host",
    ["10.0.0.5", "172.20.1.1", "192.168.1.220", "100.64.0.1", "100.127.255.254", "127.0.0.1",
     "169.254.10.10", "::1", "localhost", "app", "unicorn-brigade", "db.internal", "tower.tail1.ts.net",
     "printer.local", "", None],
)
def test_private_hosts(host):
    assert is_private_host(host) is True


@pytest.mark.parametrize(
    "host", ["projectops.unicorncommander.ai", "meetingops.magicunicorn.dev", "example.com", "8.8.8.8",
             "100.63.255.255", "100.128.0.1"],
)
def test_public_hosts(host):
    assert is_private_host(host) is False


def test_public_url_rules():
    assert public_url("https://projectops.unicorncommander.ai/dashboard", "customer")
    assert public_url("http://projectops.unicorncommander.ai/dashboard", "customer") is None
    assert public_url("https://user:pw@projectops.unicorncommander.ai/", "customer") is None
    assert public_url("https://10.1.2.3/x", "internal") is None
    assert public_url("https://meetingops.magicunicorn.dev/#/sessions", "customer") is None
    assert public_url("https://meetingops.magicunicorn.dev/#/sessions", "internal")
    assert public_origin("https://email-ops.unicorncommander.ai/api/v1/mcp", "customer") == (
        "https://email-ops.unicorncommander.ai"
    )
    assert is_off_ring("magicunicorn.dev", "customer") and not is_off_ring("magicunicorn.dev", "internal")


def test_guard_withholds_private_addresses_everywhere_and_off_ring_links_on_customer():
    document = {
        "a": "see http://10.0.0.9:8080/x and 192.168.4.4 and box.internal and n1.tail9.ts.net",
        "b": ["https://ops.magicunicorn.dev/admin", "write to aaron@magicunicorn.dev"],
        "c": {"keep": "https://projectops.unicorncommander.ai/dashboard/my-tasks", "n": 5},
    }
    cleaned, paths = guard_document(document, "customer")
    assert cleaned["a"].count(WITHHELD) == 4
    assert cleaned["b"][0] == WITHHELD
    assert cleaned["b"][1] == "write to aaron@magicunicorn.dev"  # plain text is the person's data
    assert cleaned["c"] == document["c"]
    assert set(paths) == {"$.a", "$.b[0]"}

    internal, paths = guard_document(document, "internal")
    assert internal["b"][0] == "https://ops.magicunicorn.dev/admin"
    assert paths == ["$.a"]


def test_ring_detection_matches_the_mcps_index_rule(monkeypatch):
    assert settings.ring_for_host("unicorncommander.ai") == "customer"
    assert settings.ring_for_host("ops.unicorncommander.ai:443") == "customer"
    assert settings.ring_for_host("magicunicorn.dev") == "internal"
    assert settings.ring_for_host("unicorncommander.ai.evil.example") == "internal"
    monkeypatch.setenv("HOME_RING", "customer")
    assert settings.resolve_ring("ops.example.org") == "customer"
    monkeypatch.setenv("HOME_RING", "bogus")
    assert settings.resolve_ring("magicunicorn.dev") == "internal"


def clear_app_env(monkeypatch):
    for spec in settings.APPS.values():
        monkeypatch.delenv(f"{spec.env_prefix}_API_URL", raising=False)
        monkeypatch.delenv(f"{spec.env_prefix}_WEB_URL", raising=False)


def test_api_defaults_come_from_the_rings_committed_index(monkeypatch):
    clear_app_env(monkeypatch)
    assert settings.api_base_url("project-ops", "customer") == "https://api.projectops.unicorncommander.ai"
    assert settings.api_base_url("customer-ops", "customer") == "https://api.customer-ops.unicorncommander.ai"
    assert settings.api_base_url("email-ops", "internal") == "https://email-ops.magicunicorn.dev"
    # No public REST door: Accounting-Ops /api is its Next.js tier; Center Deep is not indexed.
    assert settings.api_base_url("accounting-ops", "customer") is None
    assert settings.api_base_url("center-deep", "customer") is None
    for app in settings.APPS:
        value = settings.api_base_url(app, "customer")
        assert value is None or "magicunicorn.dev" not in value


def test_api_override_by_name_and_validation(monkeypatch):
    clear_app_env(monkeypatch)
    monkeypatch.setenv("HOME_ACCOUNTING_OPS_API_URL", "http://accounting-app:8000/")
    assert settings.api_base_url("accounting-ops", "customer") == "http://accounting-app:8000"
    monkeypatch.setenv("HOME_ACCOUNTING_OPS_API_URL", "https://user:pw@ledger.example.com")
    assert settings.api_base_url("accounting-ops", "customer") is None
    monkeypatch.setenv("HOME_ACCOUNTING_OPS_API_URL", "ftp://ledger.example.com")
    assert settings.api_base_url("accounting-ops", "customer") is None


def test_web_base_order_env_then_catalog_then_index(monkeypatch):
    clear_app_env(monkeypatch)
    # Index fallback: screens live on the API name without the api. label.
    assert settings.web_base_url("project-ops", "customer") == "https://projectops.unicorncommander.ai"
    assert settings.web_base_url("customer-ops", "customer") == "https://customer-ops.unicorncommander.ai"
    assert settings.web_base_url("project-ops", "internal") == "https://projectops.magicunicorn.dev"
    # The catalog launch_url beats the index.
    assert settings.web_base_url(
        "project-ops", "customer", "https://projects.unicorncommander.ai/dashboard"
    ) == "https://projects.unicorncommander.ai"
    # An off-ring or private catalog value is skipped.
    assert settings.web_base_url(
        "project-ops", "customer", "https://projects.magicunicorn.dev"
    ) == "https://projectops.unicorncommander.ai"
    # The explicit setting wins, unless it is unsafe.
    monkeypatch.setenv("HOME_PROJECT_OPS_WEB_URL", "https://po.example.com")
    assert settings.web_base_url("project-ops", "customer", "https://x.unicorncommander.ai") == (
        "https://po.example.com"
    )
    monkeypatch.setenv("HOME_PROJECT_OPS_WEB_URL", "http://192.168.1.10:3000")
    assert settings.web_base_url("project-ops", "customer") == "https://projectops.unicorncommander.ai"
    assert settings.web_base_url("center-deep", "customer") is None


def test_ops_center_web_base(monkeypatch):
    monkeypatch.delenv("HOME_OPS_CENTER_WEB_URL", raising=False)
    assert settings.ops_center_web_base("customer", "unicorncommander.ai") == "https://unicorncommander.ai"
    assert settings.ops_center_web_base("customer", "ops-center") == "https://unicorncommander.ai"
    assert settings.ops_center_web_base("customer", "magicunicorn.dev") == "https://unicorncommander.ai"
    assert settings.ops_center_web_base("internal", "10.0.0.2") == "https://magicunicorn.dev"
    monkeypatch.setenv("HOME_OPS_CENTER_WEB_URL", "https://ops.rivergreen.example")
    assert settings.ops_center_web_base("customer", "unicorncommander.ai") == "https://ops.rivergreen.example"


def test_flag_and_limits(monkeypatch):
    monkeypatch.delenv("HOME_STATE_ENABLED", raising=False)
    assert settings.home_state_enabled() is False
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("HOME_STATE_ENABLED", value)
        assert settings.home_state_enabled() is True
    monkeypatch.setenv("HOME_STATE_ENABLED", "off")
    assert settings.home_state_enabled() is False
    monkeypatch.delenv("HOME_APP_TIMEOUT_SECONDS", raising=False)
    assert settings.app_timeout_seconds() == 2.5
    monkeypatch.setenv("HOME_APP_TIMEOUT_SECONDS", "abc")
    assert settings.app_timeout_seconds() == 2.5
    monkeypatch.setenv("HOME_APP_TIMEOUT_SECONDS", "999")
    assert settings.app_timeout_seconds() == 15.0
