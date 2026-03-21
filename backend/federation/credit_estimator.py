"""
Credit estimation for federation-routed inference requests.

Maps service types and cloud GPU costs to credit amounts,
so users can see the cost before confirming a request.
"""

from __future__ import annotations

from typing import Any, Dict

# Base credit costs per service type (1 credit ~ $0.001)
SERVICE_CREDIT_COSTS: Dict[str, Dict[str, float]] = {
    "llm": {
        "base_per_request": 5,        # minimum
        "per_1k_input_tokens": 2,
        "per_1k_output_tokens": 4,
    },
    "tts": {
        "base_per_request": 3,
        "per_minute_audio": 5,
    },
    "stt": {
        "base_per_request": 3,
        "per_minute_audio": 10,
    },
    "embeddings": {
        "base_per_request": 1,
        "per_1k_tokens": 0.5,
    },
    "reranker": {
        "base_per_request": 1,
        "per_document": 0.2,
    },
    "image_gen": {
        "base_per_request": 20,       # FLUX generation
        "per_megapixel": 10,
    },
    "music_gen": {
        "base_per_request": 50,       # ACE-Step generation
        "per_minute_audio": 30,
    },
}


def estimate_credits(
    service_type: str,
    route_target: str,  # "local", "peer", "cloud", "cloud_gpu"
    cloud_cost_per_hour: float = 0.0,
    estimated_duration_seconds: float = 30.0,
    tier_markup_percentage: float = 0.0,
    **kwargs: Any,  # tokens, duration, documents, etc.
) -> Dict[str, Any]:
    """Estimate credit cost for a federation-routed request.

    Args:
        service_type: The type of inference service (e.g. "llm", "tts").
        route_target: Where the request will be routed ("local", "peer",
            "cloud", or "cloud_gpu").
        cloud_cost_per_hour: Hourly cost of the cloud GPU in USD.
        estimated_duration_seconds: Expected request duration in seconds.
        tier_markup_percentage: Percentage markup to apply based on user tier.
        **kwargs: Additional parameters like token counts, audio duration, etc.

    Returns:
        Dict with keys:
            - credits (int): Total estimated credits.
            - cost_usd (float): Equivalent USD cost.
            - breakdown (dict): Itemised credit components.
            - free (bool): True if routed to self-hosted infrastructure.
    """
    if route_target in ("local", "peer"):
        # Self-hosted = free (or internal cost accounting)
        return {"credits": 0, "cost_usd": 0.0, "breakdown": {}, "free": True}

    base = SERVICE_CREDIT_COSTS.get(service_type, {})
    base_credits = int(base.get("base_per_request", 5))

    # Add compute cost for cloud GPU
    compute_credits = 0
    if route_target == "cloud_gpu" and cloud_cost_per_hour > 0:
        compute_cost_usd = (estimated_duration_seconds / 3600) * cloud_cost_per_hour
        compute_credits = int(compute_cost_usd * 1000)  # $0.001 per credit

    # Apply tier markup
    subtotal = base_credits + compute_credits
    markup_credits = int(subtotal * tier_markup_percentage / 100)

    total = subtotal + markup_credits

    return {
        "credits": total,
        "cost_usd": total / 1000,
        "breakdown": {
            "base_credits": base_credits,
            "compute_credits": compute_credits,
            "markup_credits": markup_credits,
        },
        "free": False,
    }
