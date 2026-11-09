"""Fleet GPU tests: every test gets its own empty fleet-map store and no ingest token.

fleet_map_api reads its paths at import time, so they are re-pointed here and the
mtime-keyed loader cache is cleared before and after each test. Helpers live in
``fleetkit.py`` (a plain module, so importing them never collides with
``backend/tests/conftest.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
for path in (HERE, BACKEND):  # runnable as `cd backend && pytest tests/fleet` or from anywhere
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import fleet_map_api  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_fleet_store(tmp_path, monkeypatch):
    monkeypatch.delenv("FLEET_MAP_FILE", raising=False)
    monkeypatch.delenv("FLEET_MAP_INGEST_TOKEN", raising=False)
    monkeypatch.setattr(fleet_map_api, "STORE_PATH", tmp_path / "fleet_map.json")
    monkeypatch.setattr(fleet_map_api, "TOKEN_FILE", tmp_path / "fleet_map_ingest.token")
    monkeypatch.setattr(fleet_map_api, "STALE_SECONDS", 1200)
    fleet_map_api._cache.update(key=None, fleet=None, meta=None)
    yield tmp_path
    fleet_map_api._cache.update(key=None, fleet=None, meta=None)
