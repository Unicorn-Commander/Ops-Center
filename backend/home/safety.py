"""Address safety for the home document.

Two rules, applied twice (when a link is built, and once more over the whole
document before it leaves Ops-Center):

1. No private address on either ring: RFC 1918, 100.64.0.0/10 (CGNAT and the
   tailnet), loopback, link-local, ``.internal``, ``.ts.net``, single-label
   service names (``app``, ``unicorn-brigade``) and ``localhost``.
2. On the customer ring, no link to the internal ring (``magicunicorn.dev``).

Rule 1 is enforced on every string in the document, including third-party text
such as an email preview. Rule 2 is enforced on every URL in the document;
plain text that merely names the internal domain (an email address in a draft,
for example) is the person's own data and is left as it is.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

WITHHELD = "[address withheld]"

_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

_PRIVATE_SUFFIXES = (
    ".internal",
    ".ts.net",
    ".local",
    ".localdomain",
    ".lan",
    ".home.arpa",
    ".localhost",
    ".cluster.local",
)

# The internal ring's parent domain. A customer-ring document never links here.
INTERNAL_RING_SUFFIX = "magicunicorn.dev"

_URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]{}]+", re.IGNORECASE)
_IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
_PRIVATE_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9-])(?:[A-Za-z0-9-]+\.)+(?:internal|ts\.net)(?![A-Za-z0-9-])",
    re.IGNORECASE,
)


def _ip_is_private(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in _PRIVATE_NETWORKS)


def is_private_host(host: Optional[str]) -> bool:
    """True when ``host`` is not a public DNS name or public IP address."""

    host = (host or "").strip().lower().rstrip(".").strip("[]")
    if not host:
        return True
    if host == "localhost":
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return _ip_is_private(host)
    if "." not in host:
        # A single-label name only resolves inside a private network.
        return True
    return any(host.endswith(suffix) for suffix in _PRIVATE_SUFFIXES)


def is_off_ring(host: Optional[str], ring: str) -> bool:
    """True when a customer-ring document would point at the internal ring."""

    if ring != "customer":
        return False
    host = (host or "").strip().lower().rstrip(".")
    return host == INTERNAL_RING_SUFFIX or host.endswith("." + INTERNAL_RING_SUFFIX)


def _safe_parts(url: str, ring: str):
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if is_private_host(parsed.hostname) or is_off_ring(parsed.hostname, ring):
        return None
    return parsed


def public_origin(url: str, ring: str) -> Optional[str]:
    """``https://host[:port]`` of a public, on-ring URL, else None."""

    parsed = _safe_parts(url, ring)
    if parsed is None:
        return None
    return f"https://{parsed.netloc}"


def public_url(url: str, ring: str) -> Optional[str]:
    """``url`` unchanged when it is a public, on-ring https URL, else None."""

    parsed = _safe_parts(url, ring)
    if parsed is None:
        return None
    return urlunparse(parsed)


def join_url(origin: Optional[str], path: str) -> Optional[str]:
    """``origin`` plus an app path (which may carry a ``#`` fragment)."""

    if not origin:
        return None
    if not path.startswith("/"):
        path = "/" + path
    return origin.rstrip("/") + path


def _scrub_string(value: str, ring: str) -> Tuple[str, bool]:
    changed = False

    def _url(match: "re.Match[str]") -> str:
        nonlocal changed
        host = urlparse(match.group(0)).hostname
        if is_private_host(host) or is_off_ring(host, ring):
            changed = True
            return WITHHELD
        return match.group(0)

    def _ip(match: "re.Match[str]") -> str:
        nonlocal changed
        if _ip_is_private(match.group(1)):
            changed = True
            return WITHHELD
        return match.group(0)

    def _name(match: "re.Match[str]") -> str:
        nonlocal changed
        changed = True
        return WITHHELD

    result = _URL_RE.sub(_url, value)
    result = _IPV4_RE.sub(_ip, result)
    result = _PRIVATE_NAME_RE.sub(_name, result)
    return result, changed


def guard_document(document: Any, ring: str) -> Tuple[Any, List[str]]:
    """Return a copy of ``document`` with unsafe addresses withheld.

    The second value lists the JSON paths that were changed (never the values),
    so the caller can log that the guard fired without echoing what it hid.
    """

    changed_paths: List[str] = []

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, str):
            cleaned, changed = _scrub_string(node, ring)
            if changed:
                changed_paths.append(path or "$")
            return cleaned
        if isinstance(node, dict):
            return {key: walk(value, f"{path}.{key}") for key, value in node.items()}
        if isinstance(node, (list, tuple)):
            return [walk(value, f"{path}[{index}]") for index, value in enumerate(node)]
        return node

    cleaned_document = walk(document, "$")
    if changed_paths:
        logger.warning(
            "home state: withheld %d unsafe address(es) at %s",
            len(changed_paths),
            ", ".join(changed_paths[:10]),
        )
    return cleaned_document, changed_paths
