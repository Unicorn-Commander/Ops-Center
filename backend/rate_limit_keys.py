"""Rate-limit bucket keys for machine traffic."""

import hashlib

from slowapi.util import get_remote_address


def uuda_aware_rate_limit_key(request):
    """Return a per-agent bucket for authenticated UUDA traffic.

    UUDA agents share the container's bridge-gateway IP, so an agent key keeps
    one device from consuming the whole fleet's per-IP rate-limit budget.
    Requests without the expected path/header retain the original IP bucket.
    """
    try:
        if request.url.path.startswith("/api/v1/uuda/"):
            agent_key = request.headers.get("x-agent-key")
            if agent_key:
                return "uuda-agent:" + hashlib.sha256(agent_key.encode()).hexdigest()[:32]
    except Exception:
        pass
    return get_remote_address(request)
