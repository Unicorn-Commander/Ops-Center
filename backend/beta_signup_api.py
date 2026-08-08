"""
Public beta-signup front door + the narrow public Listmonk surface.

WHY THIS EXISTS
---------------
Four Listmonk lists (public + double opt-in) were created for in-development
products and nothing on any website could reach them, so they could never fill.
Listmonk itself is deliberately NOT publicly reachable: the container binds
127.0.0.1:8301 (it was 0.0.0.0 and world-open over plaintext HTTP until
2026-08-08), and its nginx sidecar `listmonk-auth-proxy` injects a hardcoded
ADMIN Authorization header on every path, so exposing Listmonk through that
sidecar would hand the internet full admin.

So the browser never talks to Listmonk. It talks to this module, which talks to
Listmonk over the docker network at http://listmonk:9000.

WHAT WE CALL, AND WHY IT NEEDS NO CREDENTIAL
--------------------------------------------
We POST to Listmonk's own PUBLIC subscription handler (`/subscription/form`),
not the admin API. That handler is unauthenticated by design, and it is the one
path that does the whole double-opt-in dance correctly: upsert the subscriber,
attach them to the list as `unconfirmed`, and send the opt-in confirmation
email. The admin API (`POST /api/subscribers`) would require an API token with
subscriber-write scope — a credential that would then live in ops-center's
environment and be worth stealing. Reaching for the public handler over a
private network means there is NO Listmonk credential in this service at all.
That is strictly safer than the scoped token, so it is what we do.

The list a caller may reach is NOT taken from the request. `PROGRAMS` below is
a server-side allowlist of slug -> list UUID. A caller cannot name a list.

NEUTRALITY
----------
The response is identical whether the address is new, already subscribed,
already confirmed, blocklisted, or bounced by Listmonk. Anything else turns
this endpoint into an oracle for "is this person on the list", which is a
membership disclosure. The real outcome is logged server-side.

DOUBLE OPT-IN STAYS ON. A subscriber created here is `unconfirmed` until they
click the link in the mail. Nothing in this module confirms anyone.

THE /mail SURFACE
-----------------
That confirmation link has to be clickable, which means Listmonk's opt-in and
unsubscribe pages must be reachable from the internet even though Listmonk is
not. `mail_router` proxies a CLOSED allowlist of Listmonk's public,
unauthenticated pages under /mail/*, and nothing else — never /api/*, never
/admin/*, never the subscription FORM (this module is the only front door), and
never through the admin-injecting sidecar.
"""

import asyncio
import ipaddress
import json
import logging
import os
import re
import time
from typing import Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/public/beta", tags=["Public Beta Signup"])
mail_router = APIRouter(prefix="/mail", tags=["Listmonk public surface"])

LISTMONK_BASE = os.environ.get("LISTMONK_INTERNAL_URL", "http://listmonk:9000").rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("BETA_SIGNUP_TIMEOUT", "10"))

# ---------------------------------------------------------------------------
# THE ALLOWLIST. A caller sends a program slug; the list UUID is resolved here.
# These UUIDs are not secrets (they appear in every opt-in link Listmonk sends);
# the security property is that the set is CLOSED, so no request can subscribe
# an address to a list that is not an open beta programme.
#
# Override with BETA_SIGNUP_PROGRAMS as JSON: {"slug": {"list_uuid": "...",
# "label": "...", "product": "..."}}
# ---------------------------------------------------------------------------
_DEFAULT_PROGRAMS: Dict[str, Dict[str, str]] = {
    "unicorn-commander-suite": {
        "list_uuid": "405b9803-ecb5-4720-b0b4-71adc7302fb8",
        "label": "Unicorn Commander Suite Beta",
        "product": "Unicorn Commander Suite",
    },
    "accounting-ops": {
        "list_uuid": "deabfc4d-d175-4c61-80ce-e1ca5ce45966",
        "label": "Accounting-Ops Beta",
        "product": "Accounting-Ops",
    },
    "majiks-media": {
        "list_uuid": "dc146ba0-6a20-4810-bd0e-9bc55b906a6d",
        "label": "Majiks Media Beta",
        "product": "Majiks Media",
    },
    "home-ops": {
        "list_uuid": "33b5a133-213d-4799-891d-c934e9183e6b",
        "label": "Home-Ops Beta",
        "product": "Home-Ops",
    },
}


def _load_programs() -> Dict[str, Dict[str, str]]:
    raw = os.environ.get("BETA_SIGNUP_PROGRAMS")
    if not raw:
        return _DEFAULT_PROGRAMS
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed:
            return parsed
    except Exception as exc:  # noqa: BLE001
        logger.error("BETA_SIGNUP_PROGRAMS is not valid JSON, using defaults: %s", exc)
    return _DEFAULT_PROGRAMS


PROGRAMS = _load_programs()

# ---------------------------------------------------------------------------
# Validation. Deliberately conservative: this endpoint's only side effect is
# causing mail to be sent to whatever it accepts, so a malformed address is a
# wasted send and a possible spam complaint against our sending domain.
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+$")
MAX_EMAIL_LEN = 254
MAX_NAME_LEN = 80


def _valid_email(value: str) -> bool:
    if not value or len(value) > MAX_EMAIL_LEN:
        return False
    if ".." in value:
        return False
    local, _, domain = value.partition("@")
    if not local or len(local) > 64 or not domain:
        return False
    tld = domain.rsplit(".", 1)[-1]
    if len(tld) < 2 or tld.isdigit():
        return False
    return bool(EMAIL_RE.match(value))


# ---------------------------------------------------------------------------
# Rate limiting. Redis-backed sliding window when Redis is up, with an
# in-process fallback so a Redis outage cannot turn this into an open mail
# relay. Three independent buckets:
#   per IP    — stops one source enumerating or hammering
#   per email — stops this endpoint being used to mail-bomb one person
#   global    — bounds total outbound mail from a signup form, full stop
# ---------------------------------------------------------------------------
def _limit(env_name: str, default: str) -> Tuple[int, int]:
    raw = os.environ.get(env_name, default)
    try:
        count, _, period = raw.partition("/")
        seconds = {"minute": 60, "hour": 3600, "day": 86400}.get(period.strip().lower(), 3600)
        return int(count.strip()), seconds
    except Exception:  # noqa: BLE001
        return 5, 3600


LIMITS = {
    "ip_hour": _limit("BETA_SIGNUP_LIMIT_IP_HOUR", "5/hour"),
    "ip_day": _limit("BETA_SIGNUP_LIMIT_IP_DAY", "20/day"),
    "email_day": _limit("BETA_SIGNUP_LIMIT_EMAIL_DAY", "3/day"),
    "global_hour": _limit("BETA_SIGNUP_LIMIT_GLOBAL_HOUR", "200/hour"),
}

_local_hits: Dict[str, list] = {}
_local_lock = asyncio.Lock()
_redis = None
_redis_ready = False


async def _get_redis():
    global _redis, _redis_ready
    if _redis_ready:
        return _redis
    _redis_ready = True
    try:
        import redis.asyncio as aioredis  # noqa: PLC0415

        url = os.environ.get(
            "REDIS_URL",
            f"redis://{os.environ.get('REDIS_HOST', 'unicorn-redis')}:{os.environ.get('REDIS_PORT', '6379')}/0",
        )
        client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
        await client.ping()
        _redis = client
        logger.info("beta-signup: rate limiting on Redis")
    except Exception as exc:  # noqa: BLE001
        _redis = None
        logger.warning("beta-signup: Redis unavailable, using in-process rate limiting (%s)", exc)
    return _redis


async def _allowed(bucket: str, identity: str, limit: Tuple[int, int]) -> bool:
    """True if this hit is under the limit. Records the hit either way."""
    count, window = limit
    key = f"betasignup:{bucket}:{identity}"
    now = time.time()

    client = await _get_redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zcard(key)
            pipe.zadd(key, {f"{now}:{os.urandom(4).hex()}": now})
            pipe.expire(key, window + 1)
            results = await pipe.execute()
            return int(results[1]) < count
        except Exception as exc:  # noqa: BLE001
            logger.warning("beta-signup: Redis rate-limit check failed, falling back (%s)", exc)

    async with _local_lock:
        hits = [t for t in _local_hits.get(key, []) if t > now - window]
        allowed = len(hits) < count
        hits.append(now)
        _local_hits[key] = hits
        if len(_local_hits) > 5000:  # crude bound; this is the degraded path
            for stale in [k for k, v in _local_hits.items() if not v or max(v) < now - 86400][:1000]:
                _local_hits.pop(stale, None)
        return allowed


# ---------------------------------------------------------------------------
# Client identity for rate limiting.
#
# CF-Connecting-IP is just a request header. Cloudflare sets it, but so can
# anything else that can open a socket to us, and this origin IS reachable
# without going through Cloudflare (Traefik binds 0.0.0.0:443 and this app
# publishes 0.0.0.0:8084). Trusting it unconditionally meant one host could
# rotate a forged value and mint a fresh rate-limit bucket per request, walking
# straight past the 5/hour + 20/day per-IP caps and using our sending
# reputation to mail confirmation links to arbitrary third parties.
#
# So: only believe CF-Connecting-IP when the hop that actually reached us is
# Cloudflare. Traefik has no forwardedHeaders.trustedIPs, which means it
# DISCARDS any inbound X-Forwarded-For and rewrites it from the real TCP peer.
# That makes the last X-Forwarded-For entry the one address in the request an
# outsider cannot choose. On the direct :8084 path there is no XFF at all and
# request.client.host is already the true peer.
#
# Override the trusted set with BETA_TRUSTED_PROXY_CIDRS (comma/space list) if
# the edge ever moves. Empty value = trust nothing = always use the raw peer.
_CLOUDFLARE_CIDRS_DEFAULT = (
    # https://www.cloudflare.com/ips-v4 + ips-v6, fetched 2026-08-08.
    "173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 "
    "141.101.64.0/18 108.162.192.0/18 190.93.240.0/20 188.114.96.0/20 "
    "197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 104.16.0.0/13 "
    "104.24.0.0/14 172.64.0.0/13 131.0.72.0/22 "
    "2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 "
    "2405:8100::/32 2a06:98c0::/29 2c0f:f248::/32"
)


def _parse_cidrs(raw: str) -> Tuple[ipaddress._BaseNetwork, ...]:
    nets = []
    for token in re.split(r"[,\s]+", (raw or "").strip()):
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            logger.warning("beta-signup: ignoring bad trusted-proxy CIDR %r", token)
    return tuple(nets)


_raw_trusted = os.getenv("BETA_TRUSTED_PROXY_CIDRS")
if _raw_trusted is None:
    _raw_trusted = _CLOUDFLARE_CIDRS_DEFAULT
_TRUSTED_PROXY_NETS = _parse_cidrs(_raw_trusted)


def _is_trusted_proxy(addr: str) -> bool:
    """True if `addr` is one of our known edge proxies (Cloudflare)."""
    if not _TRUSTED_PROXY_NETS:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in _TRUSTED_PROXY_NETS)


# Our own reverse proxy reaches this app from the docker/host network. Only a
# request whose TCP peer is in here has an X-Forwarded-For that WE wrote; from
# anyone else the header is attacker-supplied and must be ignored completely.
_LOCAL_PROXY_CIDRS_DEFAULT = (
    "127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 ::1/128 fc00::/7"
)
_LOCAL_PROXY_NETS = _parse_cidrs(
    os.getenv("BETA_LOCAL_PROXY_CIDRS", _LOCAL_PROXY_CIDRS_DEFAULT)
)


def _is_local_proxy(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in _LOCAL_PROXY_NETS)


def _client_ip(request: Request) -> str:
    peer = (request.client.host if request.client else "").strip()

    if _is_local_proxy(peer):
        # Behind our reverse proxy: it discards inbound X-Forwarded-For and
        # rewrites it from the real TCP peer, so the LAST hop is ours to trust.
        hops = [h.strip() for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
        edge = hops[-1] if hops else peer
    else:
        # Direct hit on the published port. Nothing in the request is
        # trustworthy except the socket itself.
        hops = []
        edge = peer

    if edge and _is_trusted_proxy(edge):
        cf = (request.headers.get("cf-connecting-ip") or "").strip()
        if cf:
            return cf[:64]
        if hops:
            return hops[0][:64]

    # Not behind a proxy we trust: the peer is the only honest identity, and a
    # forged CF-Connecting-IP / X-Forwarded-For is ignored outright.
    return (edge or "unknown")[:64]


# ---------------------------------------------------------------------------
# Copy. ONE neutral sentence, used for every outcome.
# ---------------------------------------------------------------------------
NEUTRAL_MESSAGE = (
    "Check your inbox. If that address can receive mail, a confirmation link is on its way. "
    "You are not on the list until you click it."
)


def _neutral() -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "status": "confirmation_requested",
            "message": NEUTRAL_MESSAGE,
        },
    )


class BetaSignupRequest(BaseModel):
    program: str = Field(..., max_length=64)
    email: str = Field(..., max_length=MAX_EMAIL_LEN)
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LEN)
    # Honeypot. A human never sees this field; a form-filling bot does.
    company: Optional[str] = Field(default=None, max_length=200)


@router.get("/health")
async def beta_health():
    """Liveness + whether Listmonk is reachable. Exposes no list contents."""
    reachable = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{LISTMONK_BASE}/health")
            reachable = resp.status_code == 200
    except Exception:  # noqa: BLE001
        reachable = False
    return {
        "status": "healthy" if reachable else "degraded",
        "listmonk_reachable": reachable,
        "programs": sorted(PROGRAMS.keys()),
    }


@router.get("/programs")
async def beta_programs():
    """The open beta programmes. No subscriber counts — that is list state."""
    return {
        "programs": [
            {"slug": slug, "product": cfg.get("product", slug), "label": cfg.get("label", slug)}
            for slug, cfg in sorted(PROGRAMS.items())
        ]
    }


@router.post("/signup")
async def beta_signup(payload: BetaSignupRequest, request: Request):
    program = PROGRAMS.get(payload.program.strip().lower())
    if not program:
        # Not a membership oracle: the programme list is public at /programs.
        raise HTTPException(status_code=400, detail="Unknown beta programme.")

    email = payload.email.strip().lower()
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="That does not look like an email address.")

    ip = _client_ip(request)

    # Honeypot. Answer exactly as we answer a real signup so a bot cannot tell
    # it was caught, but do nothing.
    if payload.company:
        logger.info("beta-signup: honeypot tripped from %s for %s", ip, payload.program)
        return _neutral()

    for bucket, identity, limit in (
        ("global", "all", LIMITS["global_hour"]),
        ("ip_h", ip, LIMITS["ip_hour"]),
        ("ip_d", ip, LIMITS["ip_day"]),
        ("email_d", email, LIMITS["email_day"]),
    ):
        if not await _allowed(bucket, identity, limit):
            logger.warning("beta-signup: rate limited (%s) ip=%s program=%s", bucket, ip, payload.program)
            return JSONResponse(
                status_code=429,
                content={"ok": False, "status": "rate_limited",
                         "message": "Too many signups from here just now. Try again later."},
                headers={"Retry-After": "3600"},
            )

    # Listmonk's own public handler. Unauthenticated by design, and the only
    # path that sends the double-opt-in confirmation. `l` is the list UUID from
    # the server-side allowlist above — never anything the caller sent.
    form = {"email": email, "l": program["list_uuid"]}
    if payload.name:
        form["name"] = payload.name.strip()[:MAX_NAME_LEN]

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{LISTMONK_BASE}/subscription/form",
                data=form,
                headers={
                    # So Listmonk records the real requester if
                    # privacy.record_optin_ip is ever turned on.
                    "X-Forwarded-For": ip,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
    except Exception as exc:  # noqa: BLE001
        # A signup we could not hand to Listmonk is a DROPPED signup. Say so
        # rather than showing a success page that means nothing.
        logger.error("beta-signup: Listmonk unreachable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="We could not reach the mailing service. Nothing was recorded — please try again shortly.",
        ) from exc

    if resp.status_code >= 500:
        logger.error("beta-signup: Listmonk %s for program=%s", resp.status_code, payload.program)
        raise HTTPException(
            status_code=503,
            detail="We could not reach the mailing service. Nothing was recorded — please try again shortly.",
        )

    # 2xx and 4xx both return the SAME neutral answer. A 4xx here means
    # Listmonk declined (already subscribed and confirmed, blocklisted, domain
    # denylist). Reporting which would disclose list membership.
    logger.info(
        "beta-signup: program=%s listmonk_status=%s ip=%s",
        payload.program, resp.status_code, ip,
    )
    return _neutral()


# ===========================================================================
# THE PUBLIC LISTMONK SURFACE  (/mail/*)
#
# Listmonk's `app.root_url` points here, so every opt-in and unsubscribe link
# it mails resolves to https://unicorncommander.ai/mail/... . Only the paths
# below are proxied. Everything else 404s, including /api/*, /admin/*, and
# /subscription/form (this module is the only signup front door).
# ===========================================================================
_ALLOWED_MAIL_PATHS = (
    # opt-in confirmation:  /subscription/optin/<subscriber-uuid>
    re.compile(r"^subscription/optin/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    # unsubscribe / preferences:  /subscription/<campaign-uuid>/<subscriber-uuid>
    re.compile(r"^subscription/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/"
               r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    # the stylesheet/favicon/logo those two pages ask for
    re.compile(r"^public/static/[A-Za-z0-9._\-/]{1,120}$"),
    re.compile(r"^public/custom\.(css|js)$"),
)

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
    "content-length",
}


def _mail_allowed(path: str) -> bool:
    if ".." in path or path.startswith("/"):
        return False
    return any(rx.match(path) for rx in _ALLOWED_MAIL_PATHS)


async def _proxy_listmonk(path: str, request: Request) -> Response:
    if not _mail_allowed(path):
        raise HTTPException(status_code=404, detail="Not found")

    url = f"{LISTMONK_BASE}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body() if request.method == "POST" else None
    headers = {"X-Forwarded-For": _client_ip(request)}
    if request.method == "POST":
        headers["Content-Type"] = request.headers.get("content-type", "application/x-www-form-urlencoded")

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
            upstream = await client.request(request.method, url, content=body, headers=headers)
    except Exception as exc:  # noqa: BLE001
        logger.error("mail proxy: listmonk unreachable for %s: %s", path, exc)
        raise HTTPException(status_code=503, detail="The mailing service is unavailable.") from exc

    content = upstream.content
    media_type = upstream.headers.get("content-type", "application/octet-stream")

    # Listmonk emits ROOT-relative asset and form URLs ("/public/static/...",
    # action="/subscription/..."). Under the /mail prefix those would miss, so
    # the page would render unstyled and its own forms would post to the SPA.
    if "text/html" in media_type:
        text = content.decode("utf-8", errors="replace")
        text = text.replace('href="/public/', 'href="/mail/public/')
        text = text.replace('src="/public/', 'src="/mail/public/')
        text = text.replace('action="/subscription/', 'action="/mail/subscription/')
        text = text.replace('href="/subscription/', 'href="/mail/subscription/')
        content = text.encode("utf-8")

    out_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "content-type"
    }
    # A subscriber's opt-in URL must never end up in an index.
    out_headers["X-Robots-Tag"] = "noindex, nofollow"
    out_headers.pop("set-cookie", None)

    return Response(content=content, status_code=upstream.status_code,
                    media_type=media_type, headers=out_headers)


@mail_router.get("/{path:path}")
async def mail_get(path: str, request: Request):
    return await _proxy_listmonk(path, request)


@mail_router.post("/{path:path}")
async def mail_post(path: str, request: Request):
    return await _proxy_listmonk(path, request)
