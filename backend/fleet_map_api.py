"""
Fleet Map API
=============

Serves the live fleet topology (sites, hosts, containers, routes, links, layers)
that the fleet-map collector (`~/Projects/fleet-map`: collect.sh -> build.py ->
data.js) gathers over ssh. A copy of that collector runs on bigboy every 5 min
(`panel-fleet-push.timer`) and POSTs the result here, so the console's
"Fleet Map" page is always current without anyone touching a static file.

Endpoints
---------
POST /api/v1/fleet/ingest   machine-to-machine. `Authorization: Bearer <token>`.
                            Body = the FLEET JSON object, OR the raw data.js
                            text (`window.FLEET = {...};`) - both accepted so
                            the collector can post data.js verbatim.
                            Listed in auth_middleware PUBLIC_EXACT and the CSRF
                            exempt set; auth is the bearer check below.
GET  /api/v1/fleet/map      admin session. Full topology JSON + `_meta`.
GET  /api/v1/fleet/map.js   admin session. Same payload as `window.FLEET = ...;`
                            (application/javascript) for the vendored D3 viewer
                            at /fleet-map/index.html, which loads it via a
                            plain <script src> so the session cookie rides along.
GET  /api/v1/fleet/status   admin session. Metadata only (age, counts, whether
                            ingest is configured) - what the React page polls.
GET  /api/v1/fleet/viewer/{file}
                            admin session. The vendored viewer itself
                            (public/fleet-map/{index.html,d3.v7.min.js,
                            fleet3d.bundle.js}). Served under /api/ on purpose:
                            on the multi-site rings only /admin, /api, /assets...
                            reach ops-center - the apex path space belongs to the
                            marketing site - so /fleet-map/... would 404 there.

Configuration (env)
-------------------
FLEET_MAP_INGEST_TOKEN        bearer the collector must present. If unset, the
FLEET_MAP_INGEST_TOKEN_FILE   token is read from this file (default
                              <backend>/data/fleet_map_ingest.token, which is
                              inside the bind-mounted backend/ dir on the
                              bind-mount deployments, so no container recreate
                              is needed to provision it). No token anywhere ->
                              ingest answers 503 and REFUSES (fails closed).
FLEET_MAP_DATA_DIR            where the last accepted payload is persisted
                              (default <backend>/data). File: fleet_map.json.
FLEET_MAP_FILE                optional read-through source: a data.js or .json
                              the collector writes directly (e.g. a mounted
                              volume). When set and present it wins over the
                              pushed copy; re-read when its mtime changes.
FLEET_MAP_STALE_SECONDS       age after which /status reports stale (default
                              1200 = 4 missed 5-minute cycles).
FLEET_MAP_MAX_BYTES           ingest body cap (default 16 MiB; data.js ~0.5 MB).

Security notes: the token is compared with hmac.compare_digest and is never
logged; the GET surfaces carry IPs/ports/hostnames for the whole fleet, hence
require_admin_user (the viewer has its own privacy toggle for screen sharing).
"""

import hmac
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from auth_dependencies import require_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/fleet", tags=["fleet-map"])

_BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("FLEET_MAP_DATA_DIR") or (_BACKEND_DIR / "data"))
STORE_PATH = DATA_DIR / "fleet_map.json"
TOKEN_FILE = Path(os.getenv("FLEET_MAP_INGEST_TOKEN_FILE") or (DATA_DIR / "fleet_map_ingest.token"))
STALE_SECONDS = int(os.getenv("FLEET_MAP_STALE_SECONDS", "1200"))
MAX_BYTES = int(os.getenv("FLEET_MAP_MAX_BYTES", str(16 * 1024 * 1024)))

# Viewer files are served by extension; the path is confined to the viewer dir (no "..", no symlink escape).
_VIEWER_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
    ".webp": "image/webp", ".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg",
    ".json": "application/json", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8",
}
_VIEWER_DIRS = (
    _BACKEND_DIR / "public" / "fleet-map",          # container: backend=/app, public bind-mounted at /app/public
    _BACKEND_DIR.parent / "public" / "fleet-map",   # source tree / local runs
    Path("public") / "fleet-map",                   # cwd-relative, like server.py's FileResponse("public/...")
)

_REQUIRED_KEYS = ("hosts", "containers")
_JS_PREFIX = re.compile(r"^\s*(?:window\.)?FLEET\s*=\s*", re.DOTALL)

# In-process cache: (source path, mtime) -> (fleet dict, meta dict)
_cache: Dict[str, Any] = {"key": None, "fleet": None, "meta": None}


# --------------------------------------------------------------------------- helpers
def _ingest_token() -> Optional[str]:
    tok = os.getenv("FLEET_MAP_INGEST_TOKEN", "").strip()
    if tok:
        return tok
    try:
        tok = TOKEN_FILE.read_text().strip()
        return tok or None
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("fleet-map: token file %s unreadable: %s", TOKEN_FILE, e)
        return None


def parse_payload(raw: bytes) -> Dict[str, Any]:
    """Accept either a JSON object or the data.js text `window.FLEET = {...};`."""
    text = raw.decode("utf-8", errors="strict").strip()
    text = _JS_PREFIX.sub("", text, count=1)
    text = text.rstrip().rstrip(";").rstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Body is not JSON or data.js: {e.msg} at char {e.pos}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Topology must be a JSON object")
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise HTTPException(status_code=400, detail=f"Topology missing keys: {', '.join(missing)}")
    return data


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _counts(fleet: Dict[str, Any]) -> Dict[str, int]:
    def n(v):
        return len(v) if isinstance(v, (list, dict)) else 0
    return {
        "sites": n(fleet.get("sites")),
        "hosts": n(fleet.get("hosts")),
        "containers": n(fleet.get("containers")),
        "routes": n(fleet.get("routes")),
        "links": n(fleet.get("links")),
        "externals": n(fleet.get("externals")),
    }


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")))
    os.replace(tmp, path)


def _load() -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (fleet, meta) from FLEET_MAP_FILE (if configured) else the pushed store."""
    file_src = os.getenv("FLEET_MAP_FILE", "").strip()
    if file_src and Path(file_src).is_file():
        p = Path(file_src)
        key = ("file", str(p), p.stat().st_mtime_ns)
        if _cache["key"] != key:
            try:
                fleet = parse_payload(p.read_bytes())
            except HTTPException as e:
                logger.error("fleet-map: FLEET_MAP_FILE %s rejected: %s", p, e.detail)
                fleet = None
            if fleet is not None:
                meta = {
                    "source": "file",
                    "path": str(p),
                    "received_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "bytes": p.stat().st_size,
                }
                _cache.update(key=key, fleet=fleet, meta=meta)
                return fleet, meta
        else:
            return _cache["fleet"], _cache["meta"]

    if STORE_PATH.is_file():
        key = ("store", str(STORE_PATH), STORE_PATH.stat().st_mtime_ns)
        if _cache["key"] != key:
            try:
                doc = json.loads(STORE_PATH.read_text())
                fleet, meta = doc.get("fleet"), doc.get("meta") or {}
                if not isinstance(fleet, dict):
                    raise ValueError("store has no fleet object")
            except (OSError, ValueError) as e:
                logger.error("fleet-map: store %s unreadable: %s", STORE_PATH, e)
                return None, None
            _cache.update(key=key, fleet=fleet, meta=meta)
        return _cache["fleet"], _cache["meta"]
    return None, None


def _status_doc(fleet: Optional[Dict[str, Any]], meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc: Dict[str, Any] = {
        "available": fleet is not None,
        "ingest_configured": _ingest_token() is not None,
        "ingest_endpoint": "/api/v1/fleet/ingest",
        "stale_after_seconds": STALE_SECONDS,
    }
    if fleet is None:
        return doc
    gen = _parse_iso(fleet.get("generatedAt"))
    age = int((now - gen).total_seconds()) if gen else None
    doc.update({
        "generated_at": fleet.get("generatedAt"),
        "received_at": (meta or {}).get("received_at"),
        "source": (meta or {}).get("source"),
        "age_seconds": age,
        "stale": (age is None) or (age > STALE_SECONDS),
        "counts": _counts(fleet),
        "privacy_note": (fleet.get("privacy") or {}).get("desc"),
    })
    return doc


# --------------------------------------------------------------------------- ingest
@router.post("/ingest")
async def ingest_fleet_map(request: Request):
    """Collector -> console. Bearer-authed, no session, no CSRF."""
    expected = _ingest_token()
    if not expected:
        # Fail closed: an unconfigured ingest is not an open ingest.
        raise HTTPException(status_code=503, detail="Fleet map ingest is not configured on this node")

    auth = request.headers.get("authorization", "")
    presented = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")

    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Payload exceeds {MAX_BYTES} bytes")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="Empty body")

    fleet = parse_payload(raw)
    meta = {
        "source": "push",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "bytes": len(raw),
        "remote": getattr(request.client, "host", None),
        "collector": request.headers.get("x-fleet-collector"),
    }
    try:
        _atomic_write(STORE_PATH, {"fleet": fleet, "meta": meta})
    except OSError as e:
        logger.error("fleet-map: cannot persist to %s: %s", STORE_PATH, e)
        raise HTTPException(status_code=500, detail="Could not persist topology")
    _cache.update(key=None)  # force re-read so mtime-keyed cache and file agree

    counts = _counts(fleet)
    logger.info(
        "fleet-map: ingested %s bytes, generatedAt=%s, hosts=%s containers=%s routes=%s from %s",
        len(raw), fleet.get("generatedAt"), counts["hosts"], counts["containers"], counts["routes"], meta["remote"],
    )
    return {"ok": True, "generated_at": fleet.get("generatedAt"), "received_at": meta["received_at"],
            "bytes": len(raw), "counts": counts}


# --------------------------------------------------------------------------- reads (admin)
@router.get("/status")
async def fleet_map_status(user: Dict = Depends(require_admin_user)):
    fleet, meta = _load()
    return _status_doc(fleet, meta)


@router.get("/map")
async def fleet_map_json(user: Dict = Depends(require_admin_user)):
    fleet, meta = _load()
    if fleet is None:
        raise HTTPException(status_code=404, detail="No fleet topology ingested yet")
    body = dict(fleet)
    body["_meta"] = dict(meta or {}, status=_status_doc(fleet, meta))
    return JSONResponse(content=body, headers={"Cache-Control": "no-store"})


@router.get("/map.js")
async def fleet_map_js(user: Dict = Depends(require_admin_user)):
    """`window.FLEET = {...};` for the vendored viewer (loaded via <script src>)."""
    fleet, meta = _load()
    if fleet is None:
        # Still valid JS so the viewer can render its own "nothing yet" message.
        js = "window.FLEET = null; window.FLEET_STATUS = %s;\n" % json.dumps(_status_doc(None, None))
    else:
        js = "window.FLEET = %s;\nwindow.FLEET_STATUS = %s;\n" % (
            json.dumps(fleet, separators=(",", ":")), json.dumps(_status_doc(fleet, meta)))
    return Response(content=js, media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- viewer (admin)
@router.get("/viewer/{path:path}")
async def fleet_map_viewer(path: str, user: Dict = Depends(require_admin_user)):
    """The vendored viewer (public/fleet-map/, see scripts/vendor-fleet-map.sh): index.html, d3,
    the 3D bundle and assets/agents/*.webp avatars. Path is confined to the viewer directory."""
    rel = path.strip("/") or "index.html"
    if rel.endswith("/"):
        rel += "index.html"
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        raise HTTPException(status_code=404, detail="Not Found")
    media_type = _VIEWER_TYPES.get(Path(rel).suffix.lower())
    if not media_type:
        raise HTTPException(status_code=404, detail="Not Found")
    for d in _VIEWER_DIRS:
        if not d.is_dir():
            continue
        root = d.resolve()
        p = (root / rel).resolve()
        if p.is_file() and root in p.parents:
            cache = "no-cache, must-revalidate" if rel.endswith(".html") else "public, max-age=86400"
            return FileResponse(str(p), media_type=media_type, headers={"Cache-Control": cache})
    raise HTTPException(status_code=404, detail="Not Found")
