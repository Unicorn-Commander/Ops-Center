"""Unit tests for the dependency-free backend smoke checker."""

import importlib.util
from pathlib import Path
import textwrap

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "backend_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("backend_smoke_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SMOKE = _load_smoke_module()


@pytest.mark.unit
def test_literal_tuple_allowlist_remains_supported(tmp_path):
    auth_path = tmp_path / "auth_middleware.py"
    auth_path.write_text(
        'PUBLIC_PREFIXES = ("/api/v1/public/", "/api/v1/health/")\n',
        encoding="utf-8",
    )

    assert SMOKE.resolve_allowlist(auth_path, "PUBLIC_PREFIXES") == (
        "/api/v1/public/",
        "/api/v1/health/",
    )


@pytest.mark.unit
def test_computed_tuple_can_resolve_an_imported_fixture_builder(tmp_path):
    (tmp_path / "auth_manager.py").write_text(
        textwrap.dedent(
            """
            import os

            def local_auth_enabled():
                return os.environ.get("LEGACY_LOCAL_AUTH_ENABLED", "false").lower() == "true"
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "prefix_builder.py").write_text(
        textwrap.dedent(
            """
            BASE_PREFIXES = ("/api/v1/public/",)

            def build_public_prefixes(local_auth_is_enabled):
                auth_prefix = ("/api/v1/auth/login",) if local_auth_is_enabled else ()
                return auth_prefix + BASE_PREFIXES
            """
        ),
        encoding="utf-8",
    )
    auth_path = tmp_path / "auth_middleware.py"
    auth_path.write_text(
        textwrap.dedent(
            """
            from auth_manager import local_auth_enabled
            from prefix_builder import build_public_prefixes

            PUBLIC_PREFIXES = build_public_prefixes(local_auth_enabled())
            """
        ),
        encoding="utf-8",
    )

    assert SMOKE.resolve_allowlist(auth_path, "PUBLIC_PREFIXES") == ("/api/v1/public/",)


@pytest.mark.unit
def test_unresolvable_computed_tuple_fails_loudly(tmp_path):
    auth_path = tmp_path / "auth_middleware.py"
    auth_path.write_text(
        "PUBLIC_PREFIXES = builder_that_is_not_static()\n",
        encoding="utf-8",
    )

    with pytest.raises(SMOKE.StaticResolutionError, match="could not be resolved statically"):
        SMOKE.resolve_allowlist(auth_path, "PUBLIC_PREFIXES")
