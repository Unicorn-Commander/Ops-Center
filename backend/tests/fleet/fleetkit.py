"""A fictional fleet-map snapshot with the shape the collector pushes (fleet-map build.py).

Everything here is invented: hosts are *.example, addresses come from 192.0.2.0/24
(TEST-NET-1), and the notes and container names describe no real machine. The
shapes follow build.py: ``hosts`` is a dict keyed by host id, inventory keys (os,
mem, gpu, ...) exist only for hosts the collector reached, ``last_seen`` is
headscale's protobuf timestamp, ``containers`` is a flat list.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

NOW = datetime(2030, 1, 15, 12, 0, tzinfo=timezone.utc)


def pb(dt: datetime) -> Dict[str, int]:
    """headscale's last_seen shape."""
    return {"seconds": int(dt.timestamp()), "nanos": 0}


SITES = {
    "lab": {"label": "Example lab, Springfield", "short": "Springfield lab", "color": "#3b82f6", "geo": None},
    "cloud": {"label": "Example Cloud, region one", "short": "Example Cloud", "color": "#a855f7", "geo": None},
}


def inventoried(**fields: Any) -> Dict[str, Any]:
    """The keys build.py copies from a host's own inventory, with fictional defaults."""
    host = {"os": "Ubuntu 24.04 LTS", "kern": "6.8.0-1-generic", "up": "3 days, 2 hours", "cpu": "16c",
            "mem": "62G", "ips": ["eth0=192.0.2.10/24"], "macs": ["02:00:00:00:00:01"], "gpu": [],
            "listen": ["22"], "units": []}
    host.update(fields)
    return host


def host(hid: str, *, site: str = "lab", online: Optional[bool] = True, last_seen: Optional[datetime] = None,
         models: Optional[List[str]] = None, chassis: str = "", **fields: Any) -> Dict[str, Any]:
    h = {"id": hid, "containers": [], "stacks": {}, "hostnames": [], "file_routes": [], "ts": "",
         "site": site, "role": "", "warn": "", "public": "", "display": f"{hid}.example",
         "online": online, "tags": [], "last_seen": pb(last_seen or NOW - timedelta(days=3)),
         "models": models or [], "hardware": {"chassis": chassis} if chassis else {}, "physical": {},
         "unit_items": [], "byLayer": {}, "tags_overlay": []}
    h.update(fields)
    return h


def container(hid: str, name: str, image: str, health: str = "") -> Dict[str, Any]:
    return {"id": f"{hid}/{name}", "host": hid, "name": name, "image": image, "stack": "demo",
            "service": name, "depends": [], "ports": [], "health": health, "hostnames": [],
            "cat": "app", "layer": "apps", "tags": [], "depends_ids": []}


def unit(name: str) -> Dict[str, Any]:
    return {"name": name, "cat": "ai/inference", "layer": "ai", "tags": []}


def make_fleet(generated_at: datetime = NOW) -> Dict[str, Any]:
    hosts = {
        # Two discrete GPUs, notes naming each; online, but headscale's last_seen is a days-old connect time.
        "gpu-a": host("gpu-a", models=[
            "RTX 4090 (24G): chat model, 64k context",
            "RTX A4000: speech to text lane",
            "edge-gateway :8080 routes chat here",
        ], **inventoried(mem="96G", gpu=["NVIDIA GeForce RTX 4090, 24564 MiB", "NVIDIA RTX A4000, 16376 MiB"]),
            unit_items=[unit("lab-lemonade-fw.service"), unit("demo-tts.service")]),
        # Two cards of the same model: "#0" and "#1" pick one each.
        "gpu-b": host("gpu-b", models=[
            "Tesla P40 #0: overnight batch jobs",
            "Tesla P40 #1: speaker labels for recordings",
            "imaging workers for the demo clinic",
        ], **inventoried(gpu=["Tesla P40, 23040 MiB", "Tesla P40, 23040 MiB"])),
        # An APU: the inventory names the codename only; the note names the Radeon.
        "apu-1": host("apu-1", site="lab", models=["Radeon 8060S gfx1151 (ROCm): long-context chat"],
                      **inventoried(mem="110G", gpu=["Strix"])),
        # Inventoried, no GPU: must not count as a GPU host.
        "web-1": host("web-1", **inventoried(gpu=[])),
        # A rented VPS (chassis says so): no GPU, CPU speech to text.
        "vps-1": host("vps-1", site="cloud", chassis="Example Cloud VPS, 8 vCPU", **inventoried()),
        # Never inventoried; offline on the tailnet, last seen 40 days before the snapshot.
        "laptop-1": host("laptop-1", online=None, last_seen=generated_at - timedelta(days=40)),
    }
    containers = [
        container("gpu-a", "chat-llama", "ghcr.io/ggml-org/llama.cpp:server-cuda", "healthy"),
        container("gpu-a", "stt-whisper", "fedirz/faster-whisper-server:latest", ""),
        container("gpu-a", "stt-proxy", "alpine/socat", ""),
        container("gpu-a", "edge-litellm", "ghcr.io/berriai/litellm:main-stable", "healthy"),
        container("gpu-a", "demo-postgres", "postgres:16", "healthy"),
        container("gpu-b", "batch-vllm", "vllm/vllm-openai:v0.6.0", ""),
        container("gpu-b", "demo-speaker-id", "registry.example/speaker-id:1.0", "healthy"),
        container("gpu-b", "demo-rerank", "registry.example/demo-reranker:1.0", "unhealthy"),
        container("gpu-b", "demo-ocr-wrapper", "registry.example/ocr-wrapper:1.0", "healthy"),
        container("gpu-b", "tts-metrics-exporter", "registry.example/tts-exporter:1.0", ""),
        container("apu-1", "long-chat", "ollama/ollama:0.5.0", ""),
        container("web-1", "voice-kokoro", "ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.0", "healthy"),
        container("web-1", "demo-website", "nginx:1.27-alpine", ""),
        container("vps-1", "cpu-parakeet-stt", "registry.example/parakeet-svc:local", "starting"),
    ]
    return {
        "generatedAt": generated_at.isoformat(),
        "unmapped": [],
        "sites": copy.deepcopy(SITES),
        "externals": [],
        "links": [],
        "tailnetMembers": list(hosts),
        "layers": [],
        "linkLayer": {},
        "overlays": [],
        "privacy": {"desc": "fictional demo fleet"},
        "lanMembers": [],
        "hosts": hosts,
        "containers": containers,
        "routes": [],
        "network": None,
        "agents": [],
        "agentKinds": [],
    }


def make_meta(received_at: datetime = NOW) -> Dict[str, Any]:
    return {"source": "push", "received_at": received_at.isoformat(), "bytes": 4096,
            "remote": "192.0.2.50", "collector": "collector.example"}
