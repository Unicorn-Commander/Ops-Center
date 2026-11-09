"""fleet_gpus pure functions: GPU entries, notes, ownership, freshness, service classification.

No FastAPI and no files: each rule the cards rely on, pinned on fictional input.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

import fleet_gpus as fg
from fleetkit import NOW, host, inventoried, make_fleet, make_meta, pb


# --------------------------------------------------------------------------- GPU entries
@pytest.mark.parametrize("entry, expected", [
    ("NVIDIA GeForce RTX 3080, 10240 MiB", ("NVIDIA GeForce RTX 3080", "NVIDIA", "discrete", 10240)),
    ("Tesla P40, 23040 MiB", ("Tesla P40", "NVIDIA", "discrete", 23040)),
    ("Quadro RTX 8000, 49152 MiB", ("Quadro RTX 8000", "NVIDIA", "discrete", 49152)),
    ("Radeon 890M (gfx1150)", ("Radeon 890M (gfx1150)", "AMD", "integrated", None)),
    ("Radeon 8060S (gfx1151)", ("Radeon 8060S (gfx1151)", "AMD", "integrated", None)),
    ("Strix", ("Strix", "AMD", "integrated", None)),
    ("NVIDIA GB10, [N/A]", ("NVIDIA GB10", "NVIDIA", "integrated", None)),
    ("Mystery Accelerator", ("Mystery Accelerator", None, None, None)),
])
def test_inventory_strings(entry, expected):
    gpu = fg.parse_gpu(entry, 0, host_memory_gib=64)
    assert (gpu["model"], gpu["vendor"], gpu["kind"], gpu["vram_total_mib"]) == expected
    assert gpu["shared_memory_gib"] == (64 if expected[2] == "integrated" else None)
    for never_from_a_string in ("vram_used_mib", "utilization_pct", "temperature_c", "busy", "processes"):
        assert gpu[never_from_a_string] is None


def test_only_memory_total_is_read_from_a_string():
    # A second MiB figure could be used or free depending on the query; it is not guessed.
    gpu = fg.parse_gpu("Tesla P40, 23040 MiB, 1200 MiB, 40 %", 0)
    assert gpu["vram_total_mib"] == 23040 and gpu["vram_used_mib"] is None and gpu["utilization_pct"] is None


@pytest.mark.parametrize("entry", ["", "   ", ",", 42, None, ["Tesla P40"], {}, {"index": 3}, {"name": "  "}])
def test_unreadable_entries_are_skipped(entry):
    assert fg.parse_gpu(entry, 0) is None


def test_busy_threshold():
    assert fg.parse_gpu({"name": "x", "utilization_pct": fg.BUSY_THRESHOLD_PCT}, 0)["busy"] is True
    assert fg.parse_gpu({"name": "x", "utilization_pct": fg.BUSY_THRESHOLD_PCT - 1}, 0)["busy"] is False
    assert fg.parse_gpu({"name": "x", "integrated": True, "memory_total_mib": 512}, 0)["kind"] == "integrated"


# --------------------------------------------------------------------------- notes
def gpus(*entries):
    return [fg.parse_gpu(e, i) for i, e in enumerate(entries)]


def test_note_for_two_cards_of_one_model_goes_to_both():
    cards = gpus("Tesla P40, 23040 MiB", "Tesla P40, 23040 MiB")
    left = fg.attach_notes(cards, ["2x Tesla P40: shared chat pool"])
    assert left == [] and all(g["notes"] == ["2x Tesla P40: shared chat pool"] for g in cards)


def test_ordinal_out_of_range_stays_on_the_host():
    cards = gpus("Tesla P40, 23040 MiB", "Tesla P40, 23040 MiB")
    assert fg.attach_notes(cards, ["Tesla P40 #5: nothing"]) == ["Tesla P40 #5: nothing"]
    assert all(g["notes"] == [] for g in cards)


def test_a_model_number_inside_a_longer_one_does_not_match():
    cards = gpus("Tesla P40, 23040 MiB")
    note = "Quadro P4000: render node"
    assert fg.attach_notes(cards, [note]) == [note] and cards[0]["notes"] == []


def test_prose_without_a_label_and_non_strings_stay_or_drop():
    cards = gpus("NVIDIA GeForce RTX 4070, 12282 MiB")
    long_prefix = "Paused since spring (files kept in a folder with a very long path name for rollback later): x"
    left = fg.attach_notes(cards, [long_prefix, "no colon RTX 4070 here", None, 7, " "])
    assert left == [long_prefix, "no colon RTX 4070 here"] and cards[0]["notes"] == []


# --------------------------------------------------------------------------- ownership + freshness
@pytest.mark.parametrize("fields, site, expected", [
    ({"hardware": {"ownership": "Leased"}}, "lab", ("Leased", "tag")),
    ({"hardware": {"ownership": "customer-provided"}}, "lab", ("Customer-provided", "tag")),
    ({"tags": ["tag:leased"]}, "lab", ("Leased", "tag")),
    ({"tags": ["server"], "tags_overlay": ["prod"]}, "lab", ("Owned", "default")),
    ({"hardware": {"chassis": "Example Cloud VPS, 4 vCPU"}}, "lab", ("Leased", "site")),
    ({}, "rented", ("Leased", "site")),
    ({"hardware": {"chassis": "Tower, 2x GPU"}}, "lab", ("Owned", "default")),
    ({"hardware": {"ownership": "owned", "chassis": "VPS"}}, "lab", ("Owned", "tag")),
])
def test_ownership(fields, site, expected):
    sites = {"lab": {"label": "Example lab", "short": "Lab"},
             "rented": {"label": "Example rented VPS region", "short": "Rented"}}
    assert fg.host_ownership(dict({"site": site}, **fields), sites) == expected


def test_headscale_last_seen_is_a_connect_time_not_a_heartbeat():
    gen = NOW
    old = pb(NOW - timedelta(days=3))
    # Online on the tailnet, not inventoried: seen at the snapshot, not three days ago.
    online = fg._host_doc("a", {"online": True, "last_seen": old}, {}, gen, NOW + timedelta(minutes=1), 1200)
    assert online["last_seen_source"] == "tailnet" and online["stale"] is False and online["age_seconds"] == 60
    # Offline: headscale's last_seen is the best evidence, and it is old.
    offline = fg._host_doc("b", {"online": False, "last_seen": old}, {}, gen, NOW, 1200)
    assert offline["stale"] is True and offline["age_seconds"] == 3 * 86400
    # Nothing at all: no time, stale.
    nothing = fg._host_doc("c", {}, {}, gen, NOW, 1200)
    assert nothing["last_seen"] is None and nothing["stale"] is True
    # headscale's zero time means never.
    assert fg._parse_time({"seconds": 0, "nanos": 0}) is None
    assert fg._parse_time("0001-01-01T00:00:00Z") is None


def test_snapshot_without_generated_at_is_stale_not_fresh():
    fleet = make_fleet()
    del fleet["generatedAt"]
    doc = fg.gpu_summary(fleet, make_meta(), stale_seconds=1200, now=NOW)
    assert doc["state"] == "stale" and doc["age_seconds"] is None
    assert doc["totals"]["gpus"] == 5


def test_summaries_accept_a_host_list_and_ignore_junk():
    fleet = make_fleet()
    fleet["hosts"] = list(fleet["hosts"].values()) + ["junk", {"no": "id"}]
    fleet["containers"].append("junk")
    assert fg.gpu_summary(fleet, None, stale_seconds=1200, now=NOW)["totals"]["gpus"] == 5
    assert fg.inference_summary(fleet, None, stale_seconds=1200, now=NOW)["totals"]["services"] == 9


# --------------------------------------------------------------------------- service classification
@pytest.mark.parametrize("name, image, expected", [
    ("chat", "ghcr.io/ggml-org/llama.cpp:server-cuda", ("service", "Language model", "llama.cpp", "image")),
    ("vision-a", "ghcr.io/ggml-org/llama.cpp:server-cuda", ("service", "Vision / OCR", "llama.cpp", "image")),
    ("ocr-a", "vllm/vllm-openai:latest", ("service", "Vision / OCR", "vLLM", "image")),
    ("swap", "ghcr.io/mostlygeek/llama-swap:cuda", ("service", "Language model", "llama-swap", "image")),
    ("local", "ollama/ollama:latest", ("service", "Language model", "Ollama", "image")),
    ("asr", "fedirz/faster-whisper-server:latest-cuda", ("service", "Speech to text", "faster-whisper", "image")),
    ("voice", "ghcr.io/remsky/kokoro-fastapi-gpu:latest", ("service", "Text to speech", "Kokoro", "image")),
    ("embedder", "michaelf34/infinity:latest", ("service", "Embeddings / rerank", "Infinity", "image")),
    ("demo-parakeet-asr", "registry.example/parakeet-asr:1", ("service", "Speech to text", None, "name")),
    ("demo-speaker-svc", "registry.example/speaker-svc:1", ("service", "Diarization", None, "name")),
    ("demo-embed", "registry.example/embed:1", ("service", "Embeddings / rerank", None, "name")),
    ("demo-medsam", "registry.example/medsam:1", ("service", "Vision / OCR", None, "name")),
    ("image-flux", "registry.example/flux-api:1", ("service", "Image generation", None, "name")),
    ("demo-voice-tts.service", "", ("service", "Text to speech", None, "name")),
    ("tts-ha", "nginx:alpine", ("proxy", "Text to speech", None, "name")),
    ("demo-stt-proxy", "alpine/socat", ("proxy", "Speech to text", None, "name")),
    ("stt-openai-shim", "registry.example/shim:1", ("proxy", "Speech to text", None, "name")),
    ("edge-litellm", "ghcr.io/berriai/litellm:main", ("gateway", None, None, "name")),
    ("lab-lemonade-fw.service", "", ("firewall", "Language model", None, "name")),
    ("tts-exporter", "registry.example/tts-exporter:1", ("exporter", "Text to speech", None, "name")),
])
def test_classify_service(name, image, expected):
    got = fg.classify_service(name, image)
    assert (got["verdict"], got["kind"], got["engine"], got["basis"]) == expected


@pytest.mark.parametrize("name, image", [
    ("demo-postgres", "postgres:16"),
    ("influxdb", "influxdb:2"),
    ("settings-api", "registry.example/settings:1"),
    ("television-guide", "registry.example/tv:1"),
    ("node-exporter", "prom/node-exporter"),
    ("demo-gpu-agent", "registry.example/gpu-agent:1"),
    ("docker.service", ""),
])
def test_not_about_inference(name, image):
    assert fg.classify_service(name, image) is None


def test_inventoried_host_with_old_headscale_time_is_fresh_in_the_gpu_list():
    fleet = make_fleet()
    fleet["hosts"]["solo"] = host("solo", online=False, last_seen=NOW - timedelta(days=9),
                                  **inventoried(gpu=["NVIDIA GeForce RTX 3060, 12288 MiB"]))
    doc = fg.gpu_summary(fleet, None, stale_seconds=1200, now=NOW + timedelta(minutes=5))
    solo = next(h for h in doc["hosts"] if h["id"] == "solo")
    assert solo["last_seen_source"] == "inventory" and solo["stale"] is False and solo["online"] is False
