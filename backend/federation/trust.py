"""
Federation trust-mode enforcement — Phase 2 of FEDERATION_TRUST_MODES.md.

Migration 009 added per-peer trust modes to `federation_peers`
(trust_mode ∈ full|scoped|consumer|publisher|isolated, plus publish[] /
consume[] service-type ACLs). This module is the runtime that actually
READS and ENFORCES them. Until now zero code consulted those columns.

Semantics — a row (local_node = SELF, remote_node = P) describes the LOCAL
node's stance toward peer P:

  full       Bidirectional, unrestricted (today's mesh default).
  scoped     P may SEE only `publish[]` service types on us and may CALL
             only `consume[]` service types on us. Our own outbound calls
             to P are likewise limited to `consume[]` (the local mirror of
             the peer-pair edge, per FEDERATION_TRUST_MODES.md mode
             semantics). Unlisted service types are DENIED (fail-closed).
  consumer   Outbound-only: we may call P's services; P sees and may call
             NOTHING on us.
  publisher  Inbound-only: we advertise/serve to P; we never call out to P.
  isolated   Topology-metadata only; no live federation traffic either way.

Unknown peers (no `federation_peers` row for them) get
FEDERATION_DEFAULT_TRUST_MODE (env). The default is "full" because
migration 009 explicitly preserves current full-mesh behavior as a no-op;
set FEDERATION_DEFAULT_TRUST_MODE=isolated to make unknown peers
deny-by-default once explicit peer rows are seeded.

is_active = false on a row is treated as `isolated`.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("federation.trust")

VALID_TRUST_MODES = {"full", "scoped", "consumer", "publisher", "isolated"}

# Modes that let the peer SEE services on us (advertisement / catalog reads)
_ADVERTISE_ALL = {"full", "publisher"}
# Modes that let the peer CALL services on us (inbound execution)
_INBOUND_ALL = {"full", "publisher"}
# Modes that let US call the peer's services (outbound routing)
_OUTBOUND_ALL = {"full", "consumer"}

_POLICY_CACHE_TTL = 30.0  # seconds


def _normalize_list(value: Any) -> List[str]:
    """JSONB columns may arrive as list, JSON string, or None."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


class TrustModeEnforcer:
    """Loads federation_peers trust rows for the local node and answers
    allow/deny questions for inbound visibility, inbound calls, and
    outbound consumption. Deny decisions inside `scoped` are fail-closed.
    """

    def __init__(
        self,
        db_pool=None,
        *,
        local_node_id: Optional[str] = None,
        default_mode: Optional[str] = None,
    ):
        self.db_pool = db_pool
        # Prefer the env identity: federation_nodes.is_self is unreliable
        # (peer registrations carry is_self=true verbatim, so several rows
        # can claim self on one node).
        self.local_node_id = (
            local_node_id
            or os.getenv("FEDERATION_LOCAL_NODE_ID")
            or os.getenv("FEDERATION_NODE_ID")
        )
        env_default = os.getenv("FEDERATION_DEFAULT_TRUST_MODE", "full")
        self.default_mode = (default_mode or env_default).lower()
        if self.default_mode not in VALID_TRUST_MODES:
            logger.warning(
                "Invalid FEDERATION_DEFAULT_TRUST_MODE %r — failing closed to 'isolated'",
                self.default_mode,
            )
            self.default_mode = "isolated"
        self._policies: Dict[str, Dict[str, Any]] = {}
        self._cache_time: float = 0.0

    # ------------------------------------------------------------------
    # Policy loading
    # ------------------------------------------------------------------

    async def get_policy(self, peer_node_id: str) -> Dict[str, Any]:
        """Return the trust policy for a peer (default policy if no row)."""
        await self._refresh_if_stale()
        policy = self._policies.get(peer_node_id)
        if policy is None:
            return {
                "trust_mode": self.default_mode,
                "publish": [],
                "consume": [],
                "is_default": True,
            }
        return policy

    async def _refresh_if_stale(self) -> None:
        now = time.monotonic()
        if self._policies and now - self._cache_time < _POLICY_CACHE_TTL:
            return
        await self.refresh()

    async def refresh(self) -> None:
        """Reload all peer trust rows for the local node from PostgreSQL."""
        if not self.db_pool:
            self._cache_time = time.monotonic()
            return
        try:
            if self.local_node_id:
                query = """
                    SELECT rn.node_id AS peer_node_id,
                           fp.trust_mode, fp.publish, fp.consume, fp.is_active
                    FROM federation_peers fp
                    JOIN federation_nodes ln ON ln.id = fp.local_node_id
                    JOIN federation_nodes rn ON rn.id = fp.remote_node_id
                    WHERE ln.node_id = $1
                """
                params = [self.local_node_id]
            else:
                query = """
                    SELECT rn.node_id AS peer_node_id,
                           fp.trust_mode, fp.publish, fp.consume, fp.is_active
                    FROM federation_peers fp
                    JOIN federation_nodes ln ON ln.id = fp.local_node_id
                    JOIN federation_nodes rn ON rn.id = fp.remote_node_id
                    WHERE ln.is_self = TRUE
                """
                params = []
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            policies: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                item = dict(row)
                mode = (item.get("trust_mode") or "full").lower()
                if mode not in VALID_TRUST_MODES:
                    # Unknown mode in DB — fail closed for this peer.
                    logger.warning(
                        "Peer %s has unknown trust_mode %r — treating as isolated",
                        item.get("peer_node_id"), mode,
                    )
                    mode = "isolated"
                if item.get("is_active") is False:
                    mode = "isolated"
                policies[item["peer_node_id"]] = {
                    "trust_mode": mode,
                    "publish": _normalize_list(item.get("publish")),
                    "consume": _normalize_list(item.get("consume")),
                    "is_default": False,
                }
            self._policies = policies
            self._cache_time = time.monotonic()
        except Exception as exc:
            # Keep serving the previous cache; do not fail open on a DB blip.
            logger.error("Failed to refresh federation trust policies: %s", exc)
            self._cache_time = time.monotonic()

    def set_policy_for_tests(self, peer_node_id: str, policy: Dict[str, Any]) -> None:
        """Inject a policy directly (unit tests only)."""
        policy.setdefault("publish", [])
        policy.setdefault("consume", [])
        policy.setdefault("is_default", False)
        self._policies[peer_node_id] = policy
        self._cache_time = time.monotonic()

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    async def visible_service_types(self, peer_node_id: str) -> Optional[Set[str]]:
        """Service types peer may SEE on us. None = all (unrestricted)."""
        policy = await self.get_policy(peer_node_id)
        mode = policy["trust_mode"]
        if mode in _ADVERTISE_ALL:
            return None
        if mode == "scoped":
            return set(policy["publish"])
        # consumer / isolated: advertise nothing
        return set()

    async def peer_may_call(
        self, peer_node_id: str, service_type: str
    ) -> Tuple[bool, str]:
        """May peer P CALL service_type on us? (inbound execution gate)"""
        policy = await self.get_policy(peer_node_id)
        mode = policy["trust_mode"]
        if mode in _INBOUND_ALL:
            return True, f"trust_mode={mode}"
        if mode == "scoped":
            if service_type in policy["consume"]:
                return True, "scoped: in consume[] ACL"
            return False, f"scoped: '{service_type}' not in consume[] ACL"
        return False, f"trust_mode={mode} blocks inbound calls"

    async def we_may_consume(
        self, peer_node_id: str, service_type: str
    ) -> Tuple[bool, str]:
        """May WE route/call service_type on peer P? (outbound routing gate)"""
        policy = await self.get_policy(peer_node_id)
        mode = policy["trust_mode"]
        if mode in _OUTBOUND_ALL:
            return True, f"trust_mode={mode}"
        if mode == "scoped":
            if service_type in policy["consume"]:
                return True, "scoped: in consume[] ACL"
            return False, f"scoped: '{service_type}' not in consume[] ACL"
        return False, f"trust_mode={mode} blocks outbound calls"

    async def filter_catalog_for_peer(
        self, catalog: List[Dict[str, Any]], peer_node_id: str
    ) -> List[Dict[str, Any]]:
        """Filter a service-catalog listing to what a peer may SEE.

        Applies the ADVERTISEMENT gate (publish[]). Used by the federation
        REST endpoints when the caller authenticated with a federation
        credential rather than as a local admin.
        """
        visible = await self.visible_service_types(peer_node_id)
        if visible is None:
            return catalog
        kept = [s for s in catalog if s.get("service_type") in visible]
        dropped = len(catalog) - len(kept)
        if dropped:
            logger.info(
                "Trust filter: hid %d of %d catalog entries from peer %s "
                "(visible service types: %s)",
                dropped, len(catalog), peer_node_id, sorted(visible) or "none",
            )
        return kept


# Module singleton ----------------------------------------------------------

_enforcer: Optional[TrustModeEnforcer] = None


def get_trust_enforcer(
    db_pool=None, *, local_node_id: Optional[str] = None
) -> TrustModeEnforcer:
    global _enforcer
    if _enforcer is None:
        _enforcer = TrustModeEnforcer(db_pool, local_node_id=local_node_id)
    else:
        # Late-bind a db_pool / node id when first available (mirrors
        # get_routing_audit_log's pattern).
        if db_pool is not None and _enforcer.db_pool is None:
            _enforcer.db_pool = db_pool
        if local_node_id and not _enforcer.local_node_id:
            _enforcer.local_node_id = local_node_id
    return _enforcer
