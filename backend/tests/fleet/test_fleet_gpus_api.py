"""GET /api/v1/fleet/gpus and /api/v1/fleet/inference through FastAPI.

The fleet-map router is mounted on a bare FastAPI app (server.py is never
imported). The real require_admin_user runs against an in-memory session store
(``redis_session`` is replaced in sys.modules), so the admin guard under test is
the one production uses. Snapshots are written where fleet_map_api's own loader
reads them (the pushed store, or FLEET_MAP_FILE), all fictional (fleetkit.py).
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fleet_map_api
from fleetkit import make_fleet, make_meta

SESSIONS = {
    "tok-admin": {"user": {"sub": "admin-1", "email": "admin@example.test", "role": "admin"}},
    "tok-viewer": {"user": {"sub": "viewer-1", "email": "viewer@example.test", "role": "viewer"}},
    "tok-user": {"user": {"sub": "user-1", "email": "user@example.test", "role": "user"}},
}


class FakeSessionManager:
    def get_for_request(self, token):
        value = SESSIONS.get(token)
        return copy.deepcopy(value) if value is not None else None


@pytest.fixture(autouse=True)
def fake_sessions(monkeypatch):
    module = ModuleType("redis_session")

    class RedisSessionUnavailable(Exception):
        pass

    module.RedisSessionUnavailable = RedisSessionUnavailable
    module.redis_session_manager = FakeSessionManager()
    monkeypatch.setitem(sys.modules, "redis_session", module)


def client(token="tok-admin"):
    app = FastAPI()
    app.include_router(fleet_map_api.router)
    c = TestClient(app)
    if token:
        c.cookies.set("session_token", token)
    return c


def store(fleet, meta=None):
    fleet_map_api.STORE_PATH.write_text(json.dumps({"fleet": fleet, "meta": meta or make_meta()}))


def fresh(minutes_old=4):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_old)


def get(path, token="tok-admin"):
    response = client(token).get(path)
    assert response.status_code == 200, response.text
    return response


# --------------------------------------------------------------------------- GPUs
def test_normal_snapshot_counts_every_gpu_with_hosts_and_detail():
    generated = fresh()
    store(make_fleet(generated))
    response = get("/api/v1/fleet/gpus")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()

    assert body["schema"] == "uc.fleet.gpus/1"
    assert body["available"] is True and body["state"] == "ok" and body["stale"] is False
    assert body["stale_after_seconds"] == 1200
    assert 200 <= body["age_seconds"] <= 300
    totals = body["totals"]
    assert totals["gpus"] == 5 and totals["hosts_with_gpus"] == 3
    assert totals["discrete_gpus"] == 4 and totals["integrated_gpus"] == 1
    assert totals["vram_total_mib"] == 24564 + 16376 + 23040 + 23040
    # The fictional collector, like the real one, reports model and total memory only.
    assert totals["vram_used_mib"] is None and totals["vram_used_reported_gpus"] == 0
    assert totals["gpus_busy"] is None and totals["utilization_reported_gpus"] == 0
    assert body["reported"] == {"vram_used": False, "utilization": False, "temperature": False, "processes": False}

    assert [h["id"] for h in body["hosts"]] == ["gpu-b", "gpu-a", "apu-1"]  # most dedicated VRAM first
    gpu_a = next(h for h in body["hosts"] if h["id"] == "gpu-a")
    assert gpu_a["name"] == "gpu-a.example"
    assert gpu_a["ownership"] == "Owned" and gpu_a["ownership_basis"] == "default"
    # Inventoried in this snapshot -> seen at generatedAt, even though headscale's
    # last_seen (a connect time) is three days old.
    assert gpu_a["last_seen_source"] == "inventory"
    assert datetime.fromisoformat(gpu_a["last_seen"]) == generated
    assert gpu_a["stale"] is False
    assert gpu_a["vram_total_mib"] == 24564 + 16376
    first, second = gpu_a["gpus"]
    assert (first["index"], first["model"], first["vendor"], first["kind"]) == \
        (0, "NVIDIA GeForce RTX 4090", "NVIDIA", "discrete")
    assert first["vram_total_mib"] == 24564
    for missing in ("vram_used_mib", "utilization_pct", "temperature_c", "busy", "processes"):
        assert first[missing] is None
    assert first["notes"] == ["RTX 4090 (24G): chat model, 64k context"]
    assert second["notes"] == ["RTX A4000: speech to text lane"]
    assert gpu_a["notes"] == ["edge-gateway :8080 routes chat here"]

    gpu_b = body["hosts"][0]
    assert [g["notes"] for g in gpu_b["gpus"]] == [["Tesla P40 #0: overnight batch jobs"],
                                                   ["Tesla P40 #1: speaker labels for recordings"]]
    assert gpu_b["notes"] == ["imaging workers for the demo clinic"]


def test_stale_snapshot_marks_every_gpu_host_stale_with_its_last_seen():
    generated = fresh(minutes_old=120)
    store(make_fleet(generated))
    body = get("/api/v1/fleet/gpus").json()
    assert body["state"] == "stale" and body["stale"] is True
    assert body["age_seconds"] >= 7200
    assert body["totals"]["gpus"] == 5  # the GPUs are still listed, marked stale, not dropped
    assert body["totals"]["stale_hosts"] == 3
    for row in body["hosts"]:
        assert row["stale"] is True and row["age_seconds"] >= 7200
        assert datetime.fromisoformat(row["last_seen"]) <= generated + timedelta(seconds=1)


def test_hosts_without_gpus_are_not_gpu_hosts_but_are_counted_in_the_fleet():
    store(make_fleet(fresh()))
    body = get("/api/v1/fleet/gpus").json()
    ids = {h["id"] for h in body["hosts"]}
    assert "web-1" not in ids and "vps-1" not in ids and "laptop-1" not in ids
    assert body["hosts_total"] == 6
    assert body["hosts_inventoried"] == 5  # laptop-1 sent no inventory


def test_integrated_gpu_counts_and_notes_shared_memory_outside_the_vram_total():
    store(make_fleet(fresh()))
    body = get("/api/v1/fleet/gpus").json()
    apu = next(h for h in body["hosts"] if h["id"] == "apu-1")
    (igpu,) = apu["gpus"]
    assert igpu["model"] == "Strix" and igpu["vendor"] == "AMD" and igpu["kind"] == "integrated"
    assert igpu["vram_total_mib"] is None
    assert igpu["shared_memory"] is True and igpu["shared_memory_gib"] == 110
    assert igpu["notes"] == ["Radeon 8060S gfx1151 (ROCm): long-context chat"]
    assert apu["vram_total_mib"] is None and apu["memory_gib"] == 110
    assert body["totals"]["integrated_gpus"] == 1
    assert body["totals"]["vram_total_mib"] == 24564 + 16376 + 23040 + 23040  # no shared memory added


def test_missing_fields_stay_null_and_reported_fields_are_used():
    fleet = make_fleet(fresh())
    fleet["hosts"]["odd-1"] = {
        "id": "odd-1", "mem": "not-a-number",
        "gpu": [
            {"name": "NVIDIA L4", "index": 0, "memory_total_mib": 23034, "memory_used_mib": 20480,
             "utilization_pct": 85, "temperature_c": 61, "processes": ["chat-llama"]},
            {"name": "NVIDIA L4", "index": 1, "memory_total_mib": "23034 MiB", "memory_used_mib": "[N/A]",
             "utilization_pct": 3},
            {"model": "NVIDIA L4"},
            "Mystery Accelerator",
            "",
            42,
        ],
    }
    store(fleet)
    body = get("/api/v1/fleet/gpus").json()
    odd = next(h for h in body["hosts"] if h["id"] == "odd-1")
    assert odd["name"] == "odd-1" and odd["site"] is None and odd["site_label"] is None
    assert odd["online"] is None and odd["memory_gib"] is None and odd["notes"] == []
    assert odd["ownership"] == "Owned"
    busy, idle, bare, mystery = odd["gpus"]
    assert (busy["vram_used_mib"], busy["utilization_pct"], busy["temperature_c"], busy["busy"]) == (20480, 85, 61, True)
    assert busy["processes"] == ["chat-llama"]
    assert (idle["vram_total_mib"], idle["vram_used_mib"], idle["busy"]) == (23034, None, False)
    assert bare["index"] == 2 and bare["vram_total_mib"] is None and bare["kind"] is None
    assert bare["busy"] is None and bare["shared_memory"] is None
    assert mystery["model"] == "Mystery Accelerator" and mystery["vendor"] is None and mystery["kind"] is None
    assert mystery["vram_total_mib"] is None

    totals = body["totals"]
    assert totals["gpus"] == 9 and totals["hosts_with_gpus"] == 4
    assert totals["vram_used_mib"] == 20480 and totals["vram_used_reported_gpus"] == 1
    assert totals["gpus_busy"] == 1 and totals["utilization_reported_gpus"] == 2
    assert body["reported"] == {"vram_used": True, "utilization": True, "temperature": True, "processes": True}


@pytest.mark.parametrize("path", ["/api/v1/fleet/gpus", "/api/v1/fleet/inference"])
def test_no_snapshot_is_not_connected_never_disabled(path):
    body = get(path).json()
    assert body["available"] is False and body["state"] == "not_connected"
    assert body["totals"] is None and body["hosts"] == []
    assert body["ingest_configured"] is False
    assert "disabled" not in json.dumps(body).lower()

    fleet_map_api.TOKEN_FILE.write_text("fictional-token-for-the-flag-only\n")
    body = get(path).json()
    assert body["state"] == "not_connected" and body["ingest_configured"] is True
    assert "fictional-token" not in json.dumps(body)


@pytest.mark.parametrize("path", ["/api/v1/fleet/gpus", "/api/v1/fleet/inference"])
def test_non_admin_is_refused(path):
    store(make_fleet(fresh()))
    assert client(token=None).get(path).status_code == 401
    assert client(token="tok-expired").get(path).status_code == 401
    for token in ("tok-viewer", "tok-user"):
        response = client(token).get(path)
        assert response.status_code == 403
        assert "hosts" not in response.text
    assert client("tok-admin").get(path).status_code == 200


def test_reads_the_same_loader_as_map_including_fleet_map_file(tmp_path, monkeypatch):
    data_js = tmp_path / "data.js"
    data_js.write_text("window.FLEET = " + json.dumps(make_fleet(fresh())) + ";\n")
    monkeypatch.setenv("FLEET_MAP_FILE", str(data_js))
    gpus = get("/api/v1/fleet/gpus").json()
    fleet_map = get("/api/v1/fleet/map").json()
    assert gpus["source"] == "file" and gpus["generated_at"] == fleet_map["generatedAt"]
    assert gpus["totals"]["gpus"] == 5


# --------------------------------------------------------------------------- inference
def test_inference_groups_model_services_by_host_with_the_controller_label():
    store(make_fleet(fresh()))
    response = get("/api/v1/fleet/inference")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schema"] == "uc.fleet.inference/1" and body["state"] == "ok"

    totals = body["totals"]
    assert totals["services"] == 9 and totals["hosts"] == 5
    assert totals["by_label"] == {"Private (Owned)": 8, "Private (Leased)": 1}
    assert totals["by_kind"] == {"Language model": 3, "Embeddings / rerank": 1, "Speech to text": 2,
                                 "Diarization": 1, "Text to speech": 2}
    assert (totals["healthy"], totals["unhealthy"]) == (3, 1)
    assert body["not_counted"] == {"exporter": 1, "firewall": 1, "gateway": 1, "proxy": 2}

    hosts = {h["id"]: h for h in body["hosts"]}
    assert set(hosts) == {"gpu-a", "gpu-b", "apu-1", "web-1", "vps-1"}
    gpu_a = hosts["gpu-a"]
    assert gpu_a["inference_label"] == "Private (Owned)" and gpu_a["gpus"] == 2
    assert [(s["name"], s["kind"], s["engine"], s["basis"], s["health"], s["source"]) for s in gpu_a["services"]] == [
        ("chat-llama", "Language model", "llama.cpp", "image", "healthy", "container"),
        ("stt-whisper", "Speech to text", "faster-whisper", "image", "running", "container"),
        ("demo-tts.service", "Text to speech", None, "name", "active", "unit"),
    ]
    names = {s["name"] for h in body["hosts"] for s in h["services"]}
    for not_a_model_server in ("stt-proxy", "edge-litellm", "demo-ocr-wrapper", "tts-metrics-exporter",
                               "lab-lemonade-fw.service", "demo-postgres", "demo-website"):
        assert not_a_model_server not in names

    gpu_b = hosts["gpu-b"]
    assert [(s["name"], s["kind"], s["health"]) for s in gpu_b["services"]] == [
        ("batch-vllm", "Language model", "running"),
        ("demo-rerank", "Embeddings / rerank", "unhealthy"),
        ("demo-speaker-id", "Diarization", "healthy"),
    ]
    vps = hosts["vps-1"]
    assert vps["ownership"] == "Leased" and vps["ownership_basis"] == "site"
    assert vps["inference_label"] == "Private (Leased)" and vps["gpus"] == 0
    assert [(s["name"], s["kind"], s["health"], s["health_checked"]) for s in vps["services"]] == [
        ("cpu-parakeet-stt", "Speech to text", "starting", True)]
    assert hosts["web-1"]["gpus"] == 0 and hosts["apu-1"]["services"][0]["engine"] == "Ollama"


def test_inference_stale_snapshot_marks_hosts_stale():
    store(make_fleet(fresh(minutes_old=90)))
    body = get("/api/v1/fleet/inference").json()
    assert body["state"] == "stale"
    assert body["totals"]["stale_hosts"] == body["totals"]["hosts"] == 5
    assert all(h["stale"] for h in body["hosts"])
