#!/usr/bin/env python3
"""
Federation-aware LiteLLM config sync sidecar.

Polls commander Ops-Center federation API every 30s to discover live LLM
services across the federation mesh. Generates a LiteLLM model_list config
that maps logical model names to live peer endpoints.

Uses stdlib urllib + requests (no async dependencies) for portability.

Usage:
  python3 litellm_config_sync.py [--interval 30] [--config-out /path/to/output.yaml]

Env vars:
  FEDERATION_API_BASE   - Ops-Center API base URL (default: http://localhost:8084)
  AUTH_TOKEN            - Bearer token for federation API
  LITELLM_MASTER_KEY    - LiteLLM master key for config reload
  LITELLM_ENDPOINT      - LiteLLM admin endpoint (default: http://uchub-litellm:4000)
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("litellm-sync")

DEFAULT_INTERVAL = 30
DEFAULT_CONFIG_OUT = "/tmp/litellm_federation.yaml"
FEDERATION_API_BASE = os.environ.get("FEDERATION_API_BASE", "http://localhost:8084")
DEFAULT_LITELLM_ENDPOINT = os.environ.get("LITELLM_ENDPOINT", "http://uchub-litellm:4000")

SERVICE_TYPE_MAP = {"llm": "openai", "embeddings": "openai", "image_gen": "openai"}

DEFAULT_EXTERNAL_MODELS = [
    {
        "model_name": "deepseek-chat-openrouter",
        "litellm_params": {
            "model": "openrouter/deepseek/deepseek-chat-v3-0324",
            "api_key": "os.environ/OPENROUTER_API_KEY",
            "rpm": 500, "tpm": 500000,
        },
        "model_info": {"mode": "cloud", "tier": "starter", "cost_per_1k_tokens": 0.0014,
                       "max_tokens": 65536, "node": "openrouter",
                       "description": "DeepSeek Chat V3 (OpenRouter)"},
    },
    {
        "model_name": "claude-sonnet-openrouter",
        "litellm_params": {
            "model": "openrouter/anthropic/claude-sonnet-4-20250514",
            "api_key": "os.environ/OPENROUTER_API_KEY",
            "rpm": 500, "tpm": 400000,
        },
        "model_info": {"mode": "cloud", "tier": "professional", "cost_per_1k_tokens": 0.003,
                       "max_tokens": 8192, "node": "openrouter",
                       "description": "Claude Sonnet 4 (OpenRouter)"},
    },
    {
        "model_name": "gpt-4o-openrouter",
        "litellm_params": {
            "model": "openrouter/openai/gpt-4o",
            "api_key": "os.environ/OPENROUTER_API_KEY",
            "rpm": 500, "tpm": 300000,
        },
        "model_info": {"mode": "cloud", "tier": "professional", "cost_per_1k_tokens": 0.005,
                       "max_tokens": 16384, "node": "openrouter",
                       "description": "GPT-4o (OpenRouter)"},
    },
    {
        "model_name": "deepseek-r1-openrouter",
        "litellm_params": {
            "model": "openrouter/deepseek/deepseek-r1",
            "api_key": "os.environ/OPENROUTER_API_KEY",
            "rpm": 200, "tpm": 200000,
        },
        "model_info": {"mode": "cloud", "tier": "professional", "cost_per_1k_tokens": 0.008,
                       "max_tokens": 65536, "node": "openrouter",
                       "description": "DeepSeek R1 (OpenRouter)"},
    },
    {
        "model_name": "claude-sonnet-direct",
        "litellm_params": {"model": "claude-3-5-sonnet-20241022",
                           "api_key": "os.environ/ANTHROPIC_API_KEY", "rpm": 50, "tpm": 50000},
        "model_info": {"mode": "cloud", "tier": "professional", "cost_per_1k_tokens": 0.003,
                       "max_tokens": 8192, "node": "anthropic", "description": "Claude Sonnet (direct)"},
    },
    {
        "model_name": "gpt-4o-direct",
        "litellm_params": {"model": "gpt-4o", "api_key": "os.environ/OPENAI_API_KEY", "rpm": 50, "tpm": 50000},
        "model_info": {"mode": "cloud", "tier": "professional", "cost_per_1k_tokens": 0.005,
                       "max_tokens": 16384, "node": "openai", "description": "GPT-4o (direct)"},
    },
]



def _parse_json_field(value, default=None):
    """Parse a field that might be a JSON string or already a dict/list."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default if default is not None else value
    return value


def _safe_model_name(model):
    return model.replace("/", "-").replace(" ", "_").replace(":", "-").lower()


def _normalize_api_base(endpoint_url, endpoint_path):
    base = endpoint_url.rstrip("/") if endpoint_url else ""
    path = (endpoint_path or "").lstrip("/")
    return f"{base}/{path}" if path else base


def fetch_federation_services(service_types=None, auth_token=None):
    """Synchronous federation service discovery. Returns list of service dicts."""
    if service_types is None:
        service_types = list(SERVICE_TYPE_MAP.keys())

    headers = {"accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    all_services = []
    session = requests.Session()

    for st in service_types:
        url = f"{FEDERATION_API_BASE}/api/v1/federation/services?service_type={st}"
        try:
            resp = session.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            services = data.get("services", data if isinstance(data, list) else [])
            all_services.extend(services)
        except requests.exceptions.HTTPError as exc:
            logger.warning("Federation API returned %s for %s: %s",
                         exc.response.status_code if exc.response else "?", st, exc)
        except Exception as exc:
            logger.warning("Failed to reach federation API for %s: %s", st, exc)

    return all_services


def build_model_list(federation_services, external_providers):
    model_list = []
    seen = set()

    for svc in federation_services:
        node_id = svc.get("node_id", "unknown")
        display_name = svc.get("display_name", node_id)
        endpoint_url = svc.get("endpoint_url", "")
        endpoint_path = svc.get("endpoint_path", "")
        service_type = svc.get("service_type", "llm")
        node_status = svc.get("node_status", "offline")

        # Parse models (may be JSON string)
        raw_models = svc.get("models", [])
        models = _parse_json_field(raw_models, [])
        if not isinstance(models, list):
            models = []

        # Parse capabilities (may be JSON string)
        caps = _parse_json_field(svc.get("capabilities", {}), {})
        if not isinstance(caps, dict):
            caps = {}

        if node_status == "offline":
            continue
        if not models:
            continue

        api_base = _normalize_api_base(endpoint_url, endpoint_path)
        if not api_base:
            logger.warning("Node %s has no resolvable endpoint", node_id)
            continue

        litellm_prefix = SERVICE_TYPE_MAP.get(service_type, "openai")

        for model in models:
            logical_name = _safe_model_name(model)
            litellm_model = f"{litellm_prefix}/{model}"
            if logical_name in seen:
                continue
            seen.add(logical_name)

            model_list.append({
                "model_name": logical_name,
                "litellm_params": {
                    "model": litellm_model,
                    "api_base": api_base,
                    "api_key": "not-needed",
                    "rpm": caps.get("max_rpm", 200),
                    "tpm": caps.get("max_tpm", 100000),
                },
                "model_info": {
                    "mode": "federation",
                    "tier": "free",
                    "cost_per_1k_tokens": svc.get("cost_usd", 0.0),
                    "max_tokens": caps.get("max_context", 8192),
                    "node": node_id,
                    "node_display": display_name,
                    "description": f"{model} @ {display_name} ({node_id})",
                },
            })

    for ext in external_providers:
        name = ext.get("model_name", "")
        if name in seen:
            continue
        seen.add(name)
        model_list.append(ext)

    logger.info("Model list: %d federation + %d external = %d total",
                len(model_list) - len(external_providers), len(external_providers), len(model_list))
    return model_list


def generate_config_yaml(model_list):
    config = {
        "model_list": model_list,
        "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"},
        "litellm_settings": {
            "num_retries": 2, "timeout": 120, "retry_after": 5,
            "fallbacks": True, "drop_params": True, "set_verbose": False,
        },
    }
    return yaml.dump(config, default_flow_style=False, sort_keys=False, width=120)


def reload_litellm_config(litellm_endpoint, master_key=None):
    headers = {"accept": "application/json"}
    if master_key:
        headers["Authorization"] = f"Bearer {master_key}"
    try:
        resp = requests.post(f"{litellm_endpoint}/config/reload", headers=headers, timeout=10)
        if resp.status_code == 200:
            logger.info("LiteLLM config reload accepted")
            return True
        logger.warning("LiteLLM config reload returned %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.warning("Failed to reload litellm config: %s", exc)
        return False


_shutting_down = False


def _handle_signal(signum, frame):
    global _shutting_down
    logger.info("Signal %s received, shutting down...", signum)
    _shutting_down = True


def run_sync_loop(config_out, interval, auth_token, litellm_endpoint, litellm_master_key):
    last_hash = None
    while not _shutting_down:
        try:
            services = fetch_federation_services(auth_token=auth_token)
            model_list = build_model_list(services, DEFAULT_EXTERNAL_MODELS)
            yaml_str = generate_config_yaml(model_list)

            new_hash = hash(yaml_str)
            if new_hash != last_hash:
                header = (
                    f"# Auto-generated by litellm_config_sync.py\n"
                    f"# Generated: {datetime.now(timezone.utc).isoformat()}\n"
                    f"# Federation peers: {len(services)}\n"
                    f"# Total models: {len(model_list)}\n\n"
                )
                with open(config_out, "w") as fh:
                    fh.write(header)
                    fh.write(yaml_str)
                logger.info("Config written to %s (%d bytes, %d models)",
                            config_out, len(yaml_str), len(model_list))
                reload_litellm_config(litellm_endpoint, litellm_master_key)
                last_hash = new_hash
            else:
                logger.debug("Config unchanged, skipping reload")
        except Exception as exc:
            logger.error("Error in sync loop: %s", exc, exc_info=True)

        for _ in range(interval):
            if _shutting_down:
                break
            time.sleep(1)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    parser = argparse.ArgumentParser(description="Federation-aware LiteLLM config sync")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--config-out", default=DEFAULT_CONFIG_OUT)
    parser.add_argument("--auth-token", default=os.environ.get("AUTH_TOKEN"))
    parser.add_argument("--litellm-master-key", default=os.environ.get("LITELLM_MASTER_KEY"))
    parser.add_argument("--litellm-endpoint", default=DEFAULT_LITELLM_ENDPOINT)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.once:
        services = fetch_federation_services(auth_token=args.auth_token)
        model_list = build_model_list(services, DEFAULT_EXTERNAL_MODELS)
        yaml_str = generate_config_yaml(model_list)
        header = f"# Generated: {datetime.now(timezone.utc).isoformat()}\n"
        with open(args.config_out, "w") as fh:
            fh.write(header)
            fh.write(yaml_str)
        print(f"Written {len(model_list)} models to {args.config_out}")
        print(f"  Federation services discovered: {len(services)}")
        print(f"  External providers: {len(DEFAULT_EXTERNAL_MODELS)}")
        reload_litellm_config(args.litellm_endpoint, args.litellm_master_key)
    else:
        logger.info("Starting litellm_config_sync (interval=%ds, output=%s)", args.interval, args.config_out)
        run_sync_loop(
            config_out=args.config_out,
            interval=args.interval,
            auth_token=args.auth_token,
            litellm_endpoint=args.litellm_endpoint,
            litellm_master_key=args.litellm_master_key,
        )
