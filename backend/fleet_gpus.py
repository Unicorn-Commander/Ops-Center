"""
Fleet GPUs and private inference, read from the fleet map snapshot
==================================================================

What the admin dashboard's GPU and Local Inference cards show when this node has
no GPU of its own (the production web host runs GPU_SERVICES_ENABLED=false). The
source is the snapshot fleet_map_api already stores and loads (``_load``), so the
answer is what the collector saw, never a guess. Pure functions, no I/O; the GET
routes live in fleet_map_api.py beside /map and /status.

GPUs
    A host's ``gpu`` list is its inventory line (fleet-map data/inv.sh, ``GPU=``):
    nvidia-smi ``name, memory.total`` strings ("Tesla P40, 23040 MiB") plus an AMD
    GPU found through lspci when ROCm is present ("Radeon 780M (gfx1103)").
    From a string only the model and the first MiB figure (memory.total) are read.
    VRAM in use, utilization, temperature and processes come only from an object
    entry with explicit keys (memory_used_mib, utilization_pct, temperature_c,
    processes); otherwise they are null and the card says "not reported", never 0.
    Integrated GPUs (AMD APUs such as Strix or a 780M, NVIDIA GB10 or Jetson) count
    as GPUs. They have no dedicated VRAM, so they stay out of the VRAM total and
    carry the host's system memory as shared memory.

Hosts
    An inventoried host (inventory keys present) was seen when the snapshot was
    built (generatedAt). A host without inventory falls back to the tailnet:
    online means generatedAt, else headscale last_seen. headscale's last_seen is a
    connect time, not a heartbeat, so it is never used for a host the tailnet
    reports online. stale = age > FLEET_MAP_STALE_SECONDS.
    Ownership: hardware.ownership, a host ownership/controller field or a host tag
    (owned, leased, customer-provided) when present; else "Leased" when the
    chassis or the site description says VPS, leased or rented; else "Owned".

Notes
    Topology ``models`` notes are hand-written ("RTX 3090 (24G): ..."). A note
    whose label (the text before its first colon) names the model of a GPU on that
    host is attached to that GPU ("#1" picks the second GPU of that model; a note
    naming an integrated GPU goes to the host's only integrated GPU). The other
    notes stay on the host.

Inference services
    Containers, and the systemd units the collector lists, are kept when the image
    is a known model server (llama.cpp, llama-swap, vLLM, Ollama, faster-whisper,
    Kokoro and others; basis "image") or the name says the kind (whisper, parakeet,
    stt, speaker, tts, embed, rerank, ocr, vision and others; basis "name").
    Proxies, adapters, gateways, exporters and firewall units that match are
    counted under not_counted instead. The snapshot does not say which model a
    service has loaded or whether it answers requests; health is the container's
    own Docker healthcheck when it has one, and "active" for a systemd unit.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

GPU_SCHEMA = "uc.fleet.gpus/1"
INFERENCE_SCHEMA = "uc.fleet.inference/1"

#: A GPU counts as busy at or above this utilization, and only when utilization is reported.
BUSY_THRESHOLD_PCT = 10

# build.py sets these host keys only from the host's own inventory (data/inv.<host>.txt).
_INVENTORY_KEYS = ("os", "kern", "up", "cpu", "mem", "ips", "macs", "gpu", "listen", "units")

_NOTE_LABEL_MAX = 80  # a "label: text" note; longer prefixes are prose, not a label


# --------------------------------------------------------------------------- small readers
def _parse_time(value: Any) -> Optional[datetime]:
    """ISO text, epoch seconds, or a protobuf timestamp {"seconds", "nanos"} -> aware datetime."""
    try:
        if isinstance(value, bool) or value is None or value == "":
            return None
        if isinstance(value, dict):
            seconds = value.get("seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
                return None
            nanos = value.get("nanos")
            frac = nanos / 1e9 if isinstance(nanos, int) and not isinstance(nanos, bool) else 0.0
            return datetime.fromtimestamp(seconds + frac, tz=timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc) if value > 0 else None
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            return dt if dt.year >= 2000 else None  # headscale "0001-01-01" = never
    except (ValueError, OverflowError, OSError):
        return None
    return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _age(now: datetime, dt: Optional[datetime]) -> Optional[int]:
    return max(0, int((now - dt).total_seconds())) if dt else None


def _number(value: Any) -> Optional[float]:
    """24576, 24576.0, "24576 MiB", "45 %" -> number; None, "[N/A]", NaN, bools -> None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    if isinstance(value, str):
        m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", value)
        return float(m.group(1)) if m else None
    return None


def _tidy(n: Optional[float]) -> Optional[float]:
    if n is None:
        return None
    return int(n) if float(n).is_integer() else round(n, 1)


def _first(entry: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if entry.get(k) is not None:
            return entry.get(k)
    return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [v for v in value.split(";") if v.strip()]
    return []


def _hosts(fleet: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = fleet.get("hosts")
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        return {str(h.get("id")): h for h in raw if isinstance(h, dict) and h.get("id")}
    return {}


def _inventoried(host: Dict[str, Any]) -> bool:
    return any(k in host for k in _INVENTORY_KEYS)


def _host_memory_gib(host: Dict[str, Any]) -> Optional[float]:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*G", str(host.get("mem") or ""))
    return _tidy(float(m.group(1))) if m else None


# --------------------------------------------------------------------------- snapshot + host freshness
def _snapshot_doc(fleet: Optional[Dict[str, Any]], meta: Optional[Dict[str, Any]], now: datetime,
                  stale_seconds: int, ingest_configured: Optional[bool]) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "available": fleet is not None,
        "state": "not_connected",
        "stale_after_seconds": stale_seconds,
        "ingest_configured": ingest_configured,
        "generated_at": None,
        "received_at": None,
        "source": None,
        "age_seconds": None,
        "stale": None,
    }
    if fleet is None:
        return doc
    meta = meta or {}
    gen = _parse_time(fleet.get("generatedAt"))
    age = _age(now, gen)
    stale = age is None or age > stale_seconds
    doc.update({
        "state": "stale" if stale else "ok",
        "generated_at": fleet.get("generatedAt"),
        "received_at": meta.get("received_at"),
        "source": meta.get("source"),
        "age_seconds": age,
        "stale": stale,
    })
    return doc


def _host_seen(host: Dict[str, Any], gen: Optional[datetime]) -> Tuple[Optional[datetime], Optional[str]]:
    if gen is not None and _inventoried(host):
        return gen, "inventory"
    if gen is not None and host.get("online") is True:
        return gen, "tailnet"
    seen = _parse_time(host.get("last_seen"))
    return (seen, "tailnet") if seen else (None, None)


# --------------------------------------------------------------------------- ownership
_OWNERSHIP_WORDS = {
    "owned": "Owned",
    "leased": "Leased",
    "rented": "Leased",
    "customer-provided": "Customer-provided",
    "customer": "Customer-provided",
}
_LEASED_RX = re.compile(r"\b(vps|vds|leased|rented|rental)\b", re.IGNORECASE)
INFERENCE_LABELS = {"Owned": "Private (Owned)", "Leased": "Private (Leased)", "Customer-provided": "Customer-provided"}


def _ownership_word(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    word = value.strip().lower()
    for prefix in ("tag:", "ownership:", "ownership=", "controller:", "controller=", "private-", "private "):
        if word.startswith(prefix):
            word = word[len(prefix):]
    word = word.strip("() ").replace(" ", "-")
    return _OWNERSHIP_WORDS.get(word)


def host_ownership(host: Dict[str, Any], sites: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """("Owned" | "Leased" | "Customer-provided", basis "tag" | "site" | "default")."""
    hardware = host.get("hardware") if isinstance(host.get("hardware"), dict) else {}
    for value in (hardware.get("ownership"), host.get("ownership"), host.get("controller")):
        label = _ownership_word(value)
        if label:
            return label, "tag"
    for tag in _as_list(host.get("tags")) + _as_list(host.get("tags_overlay")):
        label = _ownership_word(tag)
        if label:
            return label, "tag"
    site = (sites or {}).get(host.get("site")) if isinstance(sites, dict) else None
    site = site if isinstance(site, dict) else {}
    for text in (hardware.get("chassis"), site.get("label"), site.get("short")):
        if isinstance(text, str) and _LEASED_RX.search(text):
            return "Leased", "site"
    return "Owned", "default"


def _host_doc(hid: str, host: Dict[str, Any], sites: Dict[str, Any], gen: Optional[datetime],
              now: datetime, stale_seconds: int) -> Dict[str, Any]:
    seen, seen_source = _host_seen(host, gen)
    age = _age(now, seen)
    ownership, basis = host_ownership(host, sites)
    site = sites.get(host.get("site")) if isinstance(sites.get(host.get("site")), dict) else {}
    return {
        "id": hid,
        "name": host.get("display") or host.get("id") or hid,
        "site": host.get("site"),
        "site_label": site.get("short") or site.get("label"),
        "ownership": ownership,
        "ownership_basis": basis,
        "inference_label": INFERENCE_LABELS.get(ownership, "Private (Owned)"),
        "online": host.get("online") if isinstance(host.get("online"), bool) else None,
        "inventoried": _inventoried(host),
        "last_seen": _iso(seen),
        "last_seen_source": seen_source,
        "age_seconds": age,
        "stale": age is None or age > stale_seconds,
    }


# --------------------------------------------------------------------------- GPU entries
_MIB_RX = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*MiB\s*$", re.IGNORECASE)
_INTEGRATED_RX = re.compile(
    r"\bstrix\b|\bphoenix\b|hawk\s*point|\brembrandt\b|\braphael\b|\brenoir\b|\bcezanne\b|"
    r"\blucienne\b|\bbarcelo\b|\bmendocino\b|van\s*gogh|\bkrackan\b|"
    r"radeon\s+\d{3,4}[ms]\b|\bgfx(?:90c|1035|1036|1037|1103|1150|1151|1152|1153)\b|"
    r"radeon\s+vega\s*\d{1,2}\b|\bvega\s*\d{1,2}\s+graphics\b|"
    r"\bintel\b.*\b(?:uhd|iris|hd\s+graphics)\b|"
    r"\bgb10\b|\bjetson\b|\borin\b",
    re.IGNORECASE,
)
_VENDORS = (
    ("NVIDIA", re.compile(r"nvidia|geforce|quadro|tesla|titan|\brtx\b|\bgtx\b|\bgb10\b|jetson|\borin\b|"
                          r"\b[ahlb]\d{2,3}s?\b", re.IGNORECASE)),
    ("AMD", re.compile(r"\bamd\b|radeon|instinct|\bmi\d{2,3}x?\b|\bgfx\d|strix|phoenix|hawk\s*point|"
                       r"rembrandt|raphael|renoir|cezanne|\bnavi\b|\bvega\b", re.IGNORECASE)),
    ("Intel", re.compile(r"\bintel\b|\barc\b|\biris\b|\buhd\b", re.IGNORECASE)),
)
_KEY_PATTERNS = (
    re.compile(r"\b(?:rtx|gtx|gt|rx)\s*[a-z]?\d{3,4}(?:\s*(?:ti|super|xtx|xt))?\b", re.IGNORECASE),
    re.compile(r"\b[pvkahlbt]\d{1,3}s?\b", re.IGNORECASE),
    re.compile(r"\b\d{3,4}[ms]\b", re.IGNORECASE),
    re.compile(r"\bgfx\d{3,4}[a-z]?\b", re.IGNORECASE),
    re.compile(r"\bmi\d{2,3}x?\b", re.IGNORECASE),
    re.compile(r"\b(?:strix|phoenix|hawk\s*point|rembrandt|raphael|renoir|cezanne)\b", re.IGNORECASE),
    re.compile(r"\bgb10\b|\bjetson\b|\borin\b", re.IGNORECASE),
)


def _vendor(model: Optional[str]) -> Optional[str]:
    for name, rx in _VENDORS:
        if model and rx.search(model):
            return name
    return None


def parse_gpu(entry: Any, position: int, host_memory_gib: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """One inventory GPU entry -> GPU document, or None for an empty or unreadable entry."""
    used = utilization = temperature = processes = None
    integrated: Optional[bool] = None
    index = position
    if isinstance(entry, str):
        parts = [p.strip() for p in entry.split(",")]
        model = parts[0] or None
        total = next((float(m.group(1)) for m in (_MIB_RX.match(p) for p in parts[1:]) if m), None)
        if model is None and total is None:
            return None
    elif isinstance(entry, dict):
        model = _first(entry, "name", "model")
        model = str(model).strip() if model is not None and str(model).strip() else None
        idx = _number(entry.get("index"))
        index = int(idx) if idx is not None else position
        total = _number(_first(entry, "memory_total_mib", "vram_total_mib", "memory_total_mb"))
        used = _number(_first(entry, "memory_used_mib", "vram_used_mib", "memory_used_mb"))
        utilization = _number(_first(entry, "utilization_pct", "utilization_percent"))
        temperature = _number(_first(entry, "temperature_c", "temperature"))
        procs = entry.get("processes")
        processes = [p for p in procs if isinstance(p, (str, dict))] if isinstance(procs, list) else None
        if isinstance(entry.get("integrated"), bool):
            integrated = entry["integrated"]
        if model is None and all(v is None for v in (total, used, utilization, temperature)):
            return None  # an index alone says nothing about a GPU
    else:
        return None

    if integrated is None:
        if model and _INTEGRATED_RX.search(model):
            integrated = True
        elif total is not None:
            integrated = False  # a dedicated-memory figure means a discrete card
    return {
        "index": index,
        "model": model,
        "vendor": _vendor(model),
        "kind": {True: "integrated", False: "discrete"}.get(integrated),
        "vram_total_mib": _tidy(total),
        "vram_used_mib": _tidy(used),
        "utilization_pct": _tidy(utilization),
        "temperature_c": _tidy(temperature),
        "busy": None if utilization is None else utilization >= BUSY_THRESHOLD_PCT,
        "processes": processes,
        "shared_memory": True if integrated else False if integrated is False else None,
        "shared_memory_gib": host_memory_gib if integrated else None,
        "notes": [],
    }


# --------------------------------------------------------------------------- notes -> GPUs
def _key_patterns(model: Optional[str]) -> List[re.Pattern]:
    found = set()
    for rx in _KEY_PATTERNS:
        for hit in rx.findall(model or ""):
            words = hit.lower().split()
            if words:
                found.add(r"\s*".join(re.escape(w) for w in words))
    return [re.compile(r"(?<![a-z0-9])" + key + r"(?![0-9])", re.IGNORECASE) for key in sorted(found)]


def _note_label(note: str) -> Optional[str]:
    head, sep, _ = note.partition(":")
    if not sep or not head.strip() or len(head) > _NOTE_LABEL_MAX:
        return None
    return re.sub(r"\s+", " ", head).strip().lower()


def attach_notes(gpus: List[Dict[str, Any]], notes: Iterable[Any]) -> List[str]:
    """Attach each note whose label names a GPU model to that GPU; return the notes left for the host."""
    keyed = [(gpu, _key_patterns(gpu.get("model"))) for gpu in gpus]
    integrated = [gpu for gpu in gpus if gpu.get("kind") == "integrated"]
    host_notes: List[str] = []
    for note in notes:
        if not isinstance(note, str) or not note.strip():
            continue
        label = _note_label(note)
        targets: List[Dict[str, Any]] = []
        if label:
            targets = [gpu for gpu, keys in keyed if any(k.search(label) for k in keys)]
            ordinal = re.search(r"#\s*(\d+)", label)
            if ordinal and len(targets) > 1:
                n = int(ordinal.group(1))
                targets = [targets[n]] if n < len(targets) else []
            if not targets and len(integrated) == 1 and _INTEGRATED_RX.search(label):
                targets = integrated
        for gpu in targets:
            gpu["notes"].append(note)
        if not targets:
            host_notes.append(note)
    return host_notes


# --------------------------------------------------------------------------- GPU summary
def gpu_summary(fleet: Optional[Dict[str, Any]], meta: Optional[Dict[str, Any]], *, stale_seconds: int,
                now: Optional[datetime] = None, ingest_configured: Optional[bool] = None) -> Dict[str, Any]:
    """GET /api/v1/fleet/gpus: totals, GPU hosts and their GPUs from the latest snapshot."""
    now = now or datetime.now(timezone.utc)
    doc = _snapshot_doc(fleet, meta, now, stale_seconds, ingest_configured)
    doc["schema"] = GPU_SCHEMA
    doc["busy_threshold_pct"] = BUSY_THRESHOLD_PCT
    if fleet is None:
        doc.update(totals=None, hosts=[], hosts_total=None, hosts_inventoried=None, reported=None)
        return doc

    gen = _parse_time(fleet.get("generatedAt"))
    sites = fleet.get("sites") if isinstance(fleet.get("sites"), dict) else {}
    hosts = _hosts(fleet)
    rows: List[Dict[str, Any]] = []
    for hid, host in hosts.items():
        mem = _host_memory_gib(host)
        gpus = [g for g in (parse_gpu(e, i, mem) for i, e in enumerate(_as_list(host.get("gpu")))) if g]
        if not gpus:
            continue
        row = _host_doc(hid, host, sites, gen, now, stale_seconds)
        row["memory_gib"] = mem
        row["notes"] = attach_notes(gpus, _as_list(host.get("models")))
        row["gpus"] = gpus
        dedicated = [g["vram_total_mib"] for g in gpus if g["vram_total_mib"] is not None and g["kind"] != "integrated"]
        row["vram_total_mib"] = _tidy(sum(dedicated)) if dedicated else None
        rows.append(row)
    rows.sort(key=lambda r: (-(r["vram_total_mib"] or 0), -len(r["gpus"]), str(r["name"]).lower()))

    all_gpus = [g for r in rows for g in r["gpus"]]
    dedicated = [g for g in all_gpus if g["kind"] != "integrated" and g["vram_total_mib"] is not None]
    used = [g for g in all_gpus if g["vram_used_mib"] is not None]
    util = [g for g in all_gpus if g["utilization_pct"] is not None]
    doc["totals"] = {
        "gpus": len(all_gpus),
        "hosts_with_gpus": len(rows),
        "integrated_gpus": sum(1 for g in all_gpus if g["kind"] == "integrated"),
        "discrete_gpus": sum(1 for g in all_gpus if g["kind"] == "discrete"),
        "vram_total_mib": _tidy(sum(g["vram_total_mib"] for g in dedicated)) if dedicated else None,
        "vram_used_mib": _tidy(sum(g["vram_used_mib"] for g in used)) if used else None,
        "vram_used_reported_gpus": len(used),
        "gpus_busy": sum(1 for g in util if g["busy"]) if util else None,
        "utilization_reported_gpus": len(util),
        "stale_hosts": sum(1 for r in rows if r["stale"]),
    }
    doc["reported"] = {
        "vram_used": bool(used),
        "utilization": bool(util),
        "temperature": any(g["temperature_c"] is not None for g in all_gpus),
        "processes": any(g["processes"] is not None for g in all_gpus),
    }
    doc["hosts"] = rows
    doc["hosts_total"] = len(hosts)
    doc["hosts_inventoried"] = sum(1 for h in hosts.values() if _inventoried(h))
    return doc


# --------------------------------------------------------------------------- inference services
KIND_ORDER = (
    "Language model", "Vision / OCR", "Embeddings / rerank", "Speech to text",
    "Diarization", "Text to speech", "Image generation", "Model server",
)
# Name rules, checked in order; the first match names the kind.
_KIND_RULES = (
    ("Diarization", re.compile(r"diariz|pyannote|(?<![a-z])speaker(?![a-z])")),
    ("Speech to text", re.compile(r"whisper|parakeet|(?<![a-z])(?:stt|asr)(?![a-z])|speech-?to-?text|transcri|speaches")),
    ("Text to speech", re.compile(r"(?<![a-z])tts(?![a-z])|kokoro|piper|chatterbox|vibevoice|xtts|orpheus|"
                                  r"text-?to-?speech|openedai-speech")),
    ("Embeddings / rerank", re.compile(r"embed|rerank|(?<![a-z])infinity(?![a-z])|text-embeddings-inference")),
    ("Vision / OCR", re.compile(r"(?<![a-z])ocr|ocr(?![a-z])|(?<![a-z])vision|(?<![a-z])vlm(?![a-z])|paddle|"
                                r"florence|medsam|mammo|(?<![a-z])cxr(?![a-z])|machine-learning|yolo")),
    ("Image generation", re.compile(r"comfyui|(?<![a-z])flux(?![a-z])|stable-?diffusion|sdxl|automatic1111|"
                                    r"invokeai|fooocus")),
    ("Language model", re.compile(r"llama|vllm|ollama|lemonade|sglang|text-generation-inference|localai|halogen|"
                                  r"koboldcpp|aphrodite|tabbyapi|exllama|mlc-llm|lmdeploy|tensorrt-llm|"
                                  r"(?<![a-z])tgi(?![a-z])")),
)
# Known model-server images: (engine, regex on the image repository, default kind).
_ENGINES = (
    ("llama-swap", re.compile(r"llama-swap"), "Language model"),
    ("llama.cpp", re.compile(r"llama\.cpp|llama-cpp|llamacpp|llama-server"), "Language model"),
    ("vLLM", re.compile(r"(?:^|/)vllm"), "Language model"),
    ("Ollama", re.compile(r"(?:^|/)ollama(?:$|/)"), "Language model"),
    ("SGLang", re.compile(r"sglang"), "Language model"),
    ("TGI", re.compile(r"text-generation-inference"), "Language model"),
    ("LocalAI", re.compile(r"localai"), "Language model"),
    ("Lemonade", re.compile(r"lemonade"), "Language model"),
    ("Halogen", re.compile(r"halogen"), "Language model"),
    ("KoboldCpp", re.compile(r"koboldcpp"), "Language model"),
    ("TEI", re.compile(r"text-embeddings-inference"), "Embeddings / rerank"),
    ("Infinity", re.compile(r"(?:^|/)infinity$"), "Embeddings / rerank"),
    ("faster-whisper", re.compile(r"faster-whisper"), "Speech to text"),
    ("Speaches", re.compile(r"speaches"), "Speech to text"),
    ("whisper.cpp", re.compile(r"whisper\.cpp|whisper-cpp"), "Speech to text"),
    ("Whisper", re.compile(r"whisper"), "Speech to text"),
    ("Kokoro", re.compile(r"kokoro"), "Text to speech"),
    ("Piper", re.compile(r"(?:^|/)piper|wyoming-piper"), "Text to speech"),
    ("PaddleOCR", re.compile(r"paddle"), "Vision / OCR"),
    ("Immich ML", re.compile(r"immich-machine-learning"), "Vision / OCR"),
    ("ComfyUI", re.compile(r"comfyui"), "Image generation"),
    ("Triton", re.compile(r"tritonserver"), "Model server"),
)
_GATEWAY_RX = re.compile(r"litellm|openrouter|portkey|ai-gateway|llm-gateway")
_PROXY_IMAGE_RX = re.compile(r"^(?:socat|nginx(?:-unprivileged)?|haproxy|envoy|caddy|traefik|squid|openresty)$")
_PROXY_NAME_RX = re.compile(r"(?<![a-z])(?:proxy|forward|fwd|shim|wrapper|relay)(?![a-z])")
_FIREWALL_RX = re.compile(r"(?<![a-z0-9])(?:fw|firewall|iptables|nftables)(?![a-z0-9])")
_EXPORTER_RX = re.compile(r"exporter|metrics")


def _image_repo(image: Any) -> str:
    """'ghcr.io/ggml-org/llama.cpp:server-cuda@sha256:...' -> 'ghcr.io/ggml-org/llama.cpp'."""
    repo = str(image or "").strip().lower().split("@", 1)[0]
    head, sep, tail = repo.rpartition(":")
    return head if sep and "/" not in tail else repo


def _kind_for(text: str) -> Optional[str]:
    for kind, rx in _KIND_RULES:
        if text and rx.search(text):
            return kind
    return None


def classify_service(name: Any, image: Any = "") -> Optional[Dict[str, Optional[str]]]:
    """A container or unit -> {verdict, kind, engine, basis}, or None when it is not about inference.

    verdict "service" is a model-serving service; "proxy", "gateway", "firewall" and "exporter"
    matched an inference word but do not serve a model themselves.
    """
    n = str(name or "").strip().lower()
    repo = _image_repo(image)
    engine = next(((label, kind) for label, rx, kind in _ENGINES if repo and rx.search(repo)), None)
    name_kind = _kind_for(n)
    image_kind = None if engine else _kind_for(repo)
    gateway = bool(_GATEWAY_RX.search(n) or _GATEWAY_RX.search(repo))
    if not (engine or name_kind or image_kind or gateway):
        return None
    verdict = "service"
    if gateway:
        verdict = "gateway"
    elif not engine:
        if _PROXY_IMAGE_RX.match(repo.rsplit("/", 1)[-1]) or _PROXY_NAME_RX.search(n):
            verdict = "proxy"
        elif _FIREWALL_RX.search(n):
            verdict = "firewall"
        elif _EXPORTER_RX.search(n) or _EXPORTER_RX.search(repo):
            verdict = "exporter"
    return {
        "verdict": verdict,
        "kind": name_kind or (engine[1] if engine else image_kind),
        "engine": engine[0] if engine else None,
        "basis": "image" if engine else "name",
    }


def _container_health(value: Any) -> Tuple[str, bool]:
    word = str(value or "").strip().lower()
    if not word:
        return "running", False  # listed by `docker ps`, no healthcheck defined
    return word, word in ("healthy", "unhealthy", "starting")


def inference_summary(fleet: Optional[Dict[str, Any]], meta: Optional[Dict[str, Any]], *, stale_seconds: int,
                      now: Optional[datetime] = None, ingest_configured: Optional[bool] = None) -> Dict[str, Any]:
    """GET /api/v1/fleet/inference: model-serving services grouped by host, with the controller label."""
    now = now or datetime.now(timezone.utc)
    doc = _snapshot_doc(fleet, meta, now, stale_seconds, ingest_configured)
    doc["schema"] = INFERENCE_SCHEMA
    if fleet is None:
        doc.update(totals=None, hosts=[], not_counted={})
        return doc

    gen = _parse_time(fleet.get("generatedAt"))
    sites = fleet.get("sites") if isinstance(fleet.get("sites"), dict) else {}
    hosts = _hosts(fleet)
    found: Dict[str, List[Dict[str, Any]]] = {}
    not_counted: Dict[str, int] = {}

    def consider(hid: str, source: str, name: Any, image: Any, health: Tuple[str, bool]) -> None:
        verdict = classify_service(name, image)
        if verdict is None:
            return
        if verdict["verdict"] != "service":
            not_counted[verdict["verdict"]] = not_counted.get(verdict["verdict"], 0) + 1
            return
        found.setdefault(hid, []).append({
            "name": str(name),
            "source": source,
            "kind": verdict["kind"],
            "engine": verdict["engine"],
            "basis": verdict["basis"],
            "health": health[0],
            "health_checked": health[1],
        })

    for c in fleet.get("containers") or []:
        if isinstance(c, dict) and c.get("host") and c.get("name"):
            consider(str(c["host"]), "container", c["name"], c.get("image"), _container_health(c.get("health")))
    for hid, host in hosts.items():
        for unit in _as_list(host.get("unit_items")) or _as_list(host.get("units")):
            uname = unit.get("name") if isinstance(unit, dict) else unit
            if uname:
                consider(hid, "unit", uname, "", ("active", False))

    order = {k: i for i, k in enumerate(KIND_ORDER)}
    rows: List[Dict[str, Any]] = []
    for hid, services in found.items():
        host = hosts.get(hid, {"id": hid})
        row = _host_doc(hid, host, sites, gen, now, stale_seconds)
        inventory = _as_list(host.get("gpu"))
        row["gpus"] = sum(1 for i, e in enumerate(inventory) if parse_gpu(e, i)) if "gpu" in host else None
        services.sort(key=lambda s: (order.get(s["kind"], len(order)), s["name"].lower()))
        row["services"] = services
        rows.append(row)
    rows.sort(key=lambda r: (-len(r["services"]), str(r["name"]).lower()))

    every = [s for r in rows for s in r["services"]]
    by_kind: Dict[str, int] = {}
    for s in every:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
    by_label: Dict[str, int] = {}
    for r in rows:
        by_label[r["inference_label"]] = by_label.get(r["inference_label"], 0) + len(r["services"])
    doc["totals"] = {
        "services": len(every),
        "hosts": len(rows),
        "by_kind": {k: by_kind[k] for k in sorted(by_kind, key=lambda k: order.get(k, len(order)))},
        "by_label": by_label,
        "healthy": sum(1 for s in every if s["health"] == "healthy"),
        "unhealthy": sum(1 for s in every if s["health"] == "unhealthy"),
        "stale_hosts": sum(1 for r in rows if r["stale"]),
    }
    doc["hosts"] = rows
    doc["not_counted"] = dict(sorted(not_counted.items()))
    return doc
