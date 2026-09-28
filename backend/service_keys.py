"""
Inbound service keys: configured from the environment, stored only as SHA-256 hashes.

Internal services (Majiks, the Colonel, Brigade, ...) call the LLM API with
``Authorization: Bearer REMOVED<service>-<random>``. The console never holds the
plaintext keys. It holds their SHA-256 hashes:

    OPS_CENTER_SERVICE_KEY_HASHES='{"majiks": "<64 hex>", "colonel": "<64 hex>"}'

- A service that is absent from the map (or has an empty or malformed hash) is
  disabled: its key is rejected with 401.
- Hashes are compared with ``hmac.compare_digest`` against every configured
  entry, so a lookup does not leak which service matched through timing.
- A service may act on behalf of a user (the ``X-User-ID`` header) ONLY when
  it is listed in ``OPS_CENTER_SERVICE_KEY_ACT_AS_USER`` (comma separated
  names, or a JSON list). Every other service is billed to its own service
  organization, and an ``X-User-ID`` from it is refused (403).

Hash a new key on the host that generated it, without printing it:

    python3 -c "import hashlib,sys;print(hashlib.sha256(sys.stdin.buffer.read().strip()).hexdigest())" < keyfile

Changing the env takes effect on the next process start (the parsed
configuration is cached; tests call ``reset_service_key_cache``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)

HASHES_ENV = "OPS_CENTER_SERVICE_KEY_HASHES"
ACT_AS_USER_ENV = "OPS_CENTER_SERVICE_KEY_ACT_AS_USER"

# Service organizations that service-key traffic WITHOUT a user context is billed
# to. These are organization ids (not secrets); unchanged from the previous
# hardcoded mapping. The colonel shares the brigade service org.
SERVICE_ORG_IDS: Dict[str, str] = {
    "bolt-diy-service": "3766e9ee-7cc1-472f-92ae-afec687f0d74",
    "presenton-service": "13587747-66e6-43df-b21d-4411c7373465",
    "brigade-service": "e9b40f6b-b683-4bcf-b462-9fd526cfbb37",
    "centerdeep-service": "91d3b68e-e4c4-457e-80ce-de6997243c34",
    "partnerpulse-service": "8f5bf9a9-2e7c-4465-93d8-97f18bdac098",
    "open-webui-service": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "colonel-service": "e9b40f6b-b683-4bcf-b462-9fd526cfbb37",
    "majiks-service": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
}

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ServiceKeyMatch:
    """A presented key that matched a configured service."""

    service: str            # canonical name, e.g. "majiks-service"
    act_as_user: bool       # may this service send X-User-ID?
    org_id: Optional[str]   # its service organization id (no "org_" prefix), if any


class ServiceKeyUserContextForbidden(Exception):
    """A valid service key sent X-User-ID but may not act on behalf of a user."""

    def __init__(self, service: str):
        super().__init__(f"service {service} may not act on behalf of a user")
        self.service = service


def canonical_service_name(name: str) -> str:
    """'majiks' and 'majiks-service' both become 'majiks-service'."""
    name = (name or "").strip().lower()
    return name if name.endswith("-service") else f"{name}-service"


_cache: Optional[Tuple[Tuple[Tuple[str, bytes], ...], FrozenSet[str]]] = None


def reset_service_key_cache() -> None:
    """Forget the parsed configuration (tests, or an explicit reload)."""
    global _cache
    _cache = None


def _parse_hashes(raw: str) -> Tuple[Tuple[str, bytes], ...]:
    if not raw.strip():
        return ()
    try:
        data = json.loads(raw)
    except ValueError:
        logger.error("%s is not valid JSON; all service keys are disabled", HASHES_ENV)
        return ()
    if not isinstance(data, dict):
        logger.error("%s must be a JSON object of service name -> sha256 hex; all service keys are disabled", HASHES_ENV)
        return ()
    entries = []
    for name, digest in data.items():
        if not isinstance(name, str) or not _NAME_RE.match(name.strip().lower()):
            logger.error("%s: ignoring an entry with an invalid service name", HASHES_ENV)
            continue
        service = canonical_service_name(name)
        if not isinstance(digest, str) or not _HEX64_RE.match(digest.strip().lower()):
            # Never log the value: an operator may have pasted the plaintext key here.
            logger.error("%s: %s is not a 64-char sha256 hex digest; that service is disabled", HASHES_ENV, service)
            continue
        entries.append((service, bytes.fromhex(digest.strip().lower())))
    return tuple(entries)


def _parse_act_as_user(raw: str) -> FrozenSet[str]:
    raw = (raw or "").strip()
    if not raw:
        return frozenset()
    names = None
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                names = [str(x) for x in parsed]
        except ValueError:
            names = None
        if names is None:
            logger.error("%s is not a valid JSON list; no service may act on behalf of a user", ACT_AS_USER_ENV)
            return frozenset()
    else:
        names = raw.split(",")
    return frozenset(canonical_service_name(n) for n in names if n.strip())


def _config() -> Tuple[Tuple[Tuple[str, bytes], ...], FrozenSet[str]]:
    global _cache
    if _cache is None:
        entries = _parse_hashes(os.getenv(HASHES_ENV, ""))
        act_as_user = _parse_act_as_user(os.getenv(ACT_AS_USER_ENV, ""))
        configured = {s for s, _ in entries}
        for name in sorted(act_as_user - configured):
            logger.warning("%s lists %s, which has no key hash configured; ignored", ACT_AS_USER_ENV, name)
        if not entries:
            logger.warning("No inbound service keys are configured (%s unset or empty); service-key auth is disabled", HASHES_ENV)
        else:
            logger.info(
                "Inbound service keys configured for: %s (may act as a user: %s)",
                ", ".join(sorted(configured)),
                ", ".join(sorted(act_as_user & configured)) or "none",
            )
        _cache = (entries, frozenset(act_as_user & configured))
    return _cache


def configured_services() -> FrozenSet[str]:
    """Canonical names of the services whose keys are currently accepted."""
    entries, _ = _config()
    return frozenset(s for s, _ in entries)


def match_service_key(token: Optional[str]) -> Optional[ServiceKeyMatch]:
    """Return the service a presented key belongs to, or None (unknown or disabled)."""
    if not token:
        return None
    entries, act_as_user = _config()
    if not entries:
        return None
    presented = hashlib.sha256(token.encode("utf-8")).digest()
    matched = None
    for service, digest in entries:
        # Compare against every entry (no early exit) so timing does not reveal which service matched.
        if hmac.compare_digest(presented, digest) and matched is None:
            matched = service
    if matched is None:
        return None
    return ServiceKeyMatch(service=matched, act_as_user=matched in act_as_user, org_id=SERVICE_ORG_IDS.get(matched))


def resolve_principal(match: ServiceKeyMatch, x_user_id: Optional[str]) -> Tuple[Optional[str], bool]:
    """Who a service-key request acts as.

    Returns (principal_id, is_service_account):
      - with X-User-ID from a service allowed to act as a user: (user id, False)
      - with X-User-ID from any other service: raises ServiceKeyUserContextForbidden
      - without X-User-ID: ("org_<service org id>", True), or (None, True) when the
        service has no service organization configured.
    """
    user_id = (x_user_id or "").strip()
    if user_id:
        if not match.act_as_user:
            raise ServiceKeyUserContextForbidden(match.service)
        return user_id, False
    if match.org_id:
        return f"org_{match.org_id}", True
    return None, True
