"""
Federation gateway bridge — carry the per-org gateway key across the hop.

The per-org LiteLLM virtual key (gateway_key_provisioning.py, user_id ==
org_id) is the proven inference-billing contract: the gateway runs with
LITELLM_SUCCESS_CALLBACK=lago and charge_by=user_id, so a call made with
that key fires exactly one Lago `ai_api_call` event (response_cost ×
markup) keyed to the org's subscription on UC-1 Hub.

Until now that contract broke at the federation boundary: the inference
router proxied to peers with the shared federation credential, so the
publisher's gateway had no org identity to meter under. This module is
the PUBLISHER side of the fix:

    consumer node                         publisher node (this code)
    -------------                         --------------------------
    proxy_to_node(..., org_id=X) ───────▶ POST /api/v1/federation/inference
      X-Federation-Org-Id: X                1. federation auth (peer JWT)
                                            2. trust gate: peer_may_call()
                                            3. provision_org_gateway_key(X)
                                               on the LOCAL gateway (reuse,
                                               never a second key system)
                                            4. forward payload to the local
                                               gateway with the org's key
                                            5. gateway fires the ONE Lago
                                               event keyed to org X

Because the publisher's own gateway meters the call, the response is
marked gateway_metered=True so FederationMeter never double-fires Lago
for it (see federation/metering.py).
"""

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("federation.gateway_bridge")

# Same service-type → gateway path mapping the router uses for cloud routing.
GATEWAY_PATHS = {
    "llm": "/v1/chat/completions",
    "embeddings": "/v1/embeddings",
    "reranker": "/v1/rerank",
    "image_gen": "/v1/images/generations",
    "tts": "/v1/audio/speech",
    "stt": "/v1/audio/transcriptions",
}

ORG_HEADER = "X-Federation-Org-Id"


class FederatedInferenceError(Exception):
    """Base error; http_status tells the API layer what to return."""
    http_status = 500


class TrustDenied(FederatedInferenceError):
    http_status = 403


class BadFederatedRequest(FederatedInferenceError):
    http_status = 400


class GatewayKeyUnavailable(FederatedInferenceError):
    http_status = 503


async def serve_federated_inference(
    *,
    peer_node_id: str,
    org_id: Optional[str],
    service_type: str,
    payload: Dict[str, Any],
    db_pool=None,
    local_node_id: Optional[str] = None,
    trust_enforcer: Any = None,
    key_provisioner: Any = None,
    gateway_url: Optional[str] = None,
    http_client: Any = None,
) -> Dict[str, Any]:
    """Serve an inbound federated inference call under the org's gateway key.

    Args:
        peer_node_id: Authenticated calling peer (from federation auth).
        org_id: The CONSUMING org's id — becomes the metering identity.
        service_type: Federation service type (must map to a gateway path).
        payload: OpenAI-style request body, forwarded verbatim.
        trust_enforcer/key_provisioner/gateway_url/http_client: injectable
            for tests; default to the real singletons.

    Returns:
        {data, status_code, org_id, key_id, gateway_metered: True}

    Raises:
        TrustDenied / BadFederatedRequest / GatewayKeyUnavailable.
    """
    if not org_id:
        raise BadFederatedRequest(
            f"Federated inference requires the consuming org identity "
            f"({ORG_HEADER} header or org_id field)"
        )
    path = GATEWAY_PATHS.get(service_type)
    if not path:
        raise BadFederatedRequest(
            f"Service type '{service_type}' is not gateway-servable "
            f"(supported: {sorted(GATEWAY_PATHS)})"
        )

    # 1. Trust gate — the peer must be allowed to CALL this service on us.
    if trust_enforcer is None:
        from federation.trust import get_trust_enforcer
        trust_enforcer = get_trust_enforcer(db_pool, local_node_id=local_node_id)
    allowed, reason = await trust_enforcer.peer_may_call(peer_node_id, service_type)
    if not allowed:
        raise TrustDenied(
            f"Trust mode denies peer '{peer_node_id}' calling "
            f"'{service_type}': {reason}"
        )

    # 2. Per-org key on OUR gateway (idempotent; the one key system).
    if key_provisioner is None:
        from gateway_key_provisioning import provision_org_gateway_key
        key_provisioner = provision_org_gateway_key
    key_info = await key_provisioner(org_id=org_id)
    if not key_info:
        raise GatewayKeyUnavailable(
            f"Gateway key provisioning unavailable for org {org_id} "
            f"(gateway unreachable or LITELLM_MASTER_KEY unset)"
        )
    org_key = key_info.get("key")
    if not org_key:
        # Key exists on the gateway but its secret isn't retrievable on this
        # node (created without ENCRYPTION_KEY at-rest storage). Without the
        # raw value we cannot attribute the call — fail explicitly rather
        # than fall back to an unmetered credential.
        raise GatewayKeyUnavailable(
            f"Org {org_id} has gateway key {key_info.get('key_id', '?')[:12]} "
            f"but its secret is not retrievable on this node; re-key or set "
            f"ENCRYPTION_KEY so the value persists"
        )

    # 3. Resolve the LOCAL gateway URL (DB-first, same as provisioning).
    if gateway_url is None:
        from gateway_key_provisioning import _resolve_gateway_creds
        gateway_url, _ = await _resolve_gateway_creds()
    gateway_url = (gateway_url or "").rstrip("/")
    if not gateway_url:
        raise GatewayKeyUnavailable("No gateway URL configured on this node")

    # 4. Forward under the org's key — the gateway meters this call to Lago
    #    keyed user_id == org_id with the configured markup. Exactly one
    #    billable event, fired by the gateway, not by us.
    timeout = float(os.getenv("FEDERATION_PROXY_TIMEOUT", "120"))
    url = f"{gateway_url}{path}"
    headers = {
        "Authorization": f"Bearer {org_key}",
        "Content-Type": "application/json",
    }
    own_client = False
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=timeout)
        own_client = True
    try:
        response = await http_client.post(url, json=payload, headers=headers)
    finally:
        if own_client:
            await http_client.aclose()

    logger.info(
        "Federated inference: peer=%s org=%s %s -> %s [%d]",
        peer_node_id, org_id, service_type, url, response.status_code,
    )
    return {
        "data": response.json(),
        "status_code": response.status_code,
        "org_id": org_id,
        "key_id": key_info.get("key_id"),
        "gateway_metered": response.status_code < 400,
    }
