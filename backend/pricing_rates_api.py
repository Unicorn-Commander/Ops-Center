"""
Pricing & Rates API — the editable cost-plus rate book for Unicorn Commander inference resale.

Single source of truth for: provider per-token COSTS, your MARKUP, a safety BUFFER, the CREDIT
value, the local-inference strategy, and per-model overrides. The GUI ("Pricing & Rates") reads the
computed table (provider cost vs your rate vs margin vs credits/1M) and writes edits back here.

Never-lose-money model: metering bills `measured_cost * (1 + markup)`, so margin holds even if a
provider changes prices; `buffer_pct` absorbs cost-map lag; per-model overrides let you bump a rate
instantly if a provider hikes. This module is the config those mechanisms read.

Stored as JSON (no DB schema dependency) at PRICING_CONFIG_PATH so it persists on the bind-mount.

Endpoints (admin):
- GET  /api/v1/admin/pricing/rates  -> computed rate book + settings
- PUT  /api/v1/admin/pricing/rates  -> edit settings and/or per-provider/per-model overrides (GUI)
- POST /api/v1/admin/pricing/seed   -> replace provider COST table (the rate-research job), keep overrides
"""

import os
import json
import copy
from typing import Dict, Any
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1/admin/pricing", tags=["pricing-rates"])

PRICING_CONFIG_PATH = os.getenv("PRICING_CONFIG_PATH", "/app/data/pricing_config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "credit_value_usd": 0.01,     # $ per credit (1 credit = 1 cent)
    "default_markup_pct": 20.0,   # margin on top of provider cost
    "buffer_pct": 10.0,           # safety cushion for cost-map lag (never-lose-money)
    "local": {
        "strategy": "bundled",    # bundled ($0, fair-use throttle) | metered
        "rate_per_million_usd": 0.0,
        "label": "Self-hosted (Unicorn GPUs)",
    },
    "providers": {
        # minimal seed; the rate-research job (POST /seed) fills the full, real table
        "anthropic": {"label": "Anthropic", "markup_pct": None, "source_url": "", "as_of": "", "models": {
            "claude-sonnet-4": {"input_per_million_usd": 3.0, "output_per_million_usd": 15.0, "override_markup_pct": None},
        }},
        "deepseek": {"label": "DeepSeek", "markup_pct": None, "source_url": "", "as_of": "", "models": {
            "deepseek-chat": {"input_per_million_usd": 0.27, "output_per_million_usd": 1.10, "override_markup_pct": None},
        }},
    },
}


def _load() -> Dict[str, Any]:
    try:
        with open(PRICING_CONFIG_PATH) as f:
            cfg = json.load(f)
        merged = copy.deepcopy(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)


def _save(cfg: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(PRICING_CONFIG_PATH), exist_ok=True)
    tmp = PRICING_CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, PRICING_CONFIG_PATH)


def _effective_markup(cfg: Dict[str, Any], provider_key: str, model: Dict[str, Any]) -> float:
    prov = cfg["providers"].get(provider_key, {})
    m = model.get("override_markup_pct")
    if m is None:
        m = prov.get("markup_pct")
    if m is None:
        m = cfg.get("default_markup_pct", 20.0)
    return float(m)


def _compute(cfg: Dict[str, Any]) -> Dict[str, Any]:
    credit = float(cfg.get("credit_value_usd", 0.01)) or 0.01
    buffer = float(cfg.get("buffer_pct", 0.0)) / 100.0
    rows = []
    for pkey, prov in cfg.get("providers", {}).items():
        for mname, m in prov.get("models", {}).items():
            cin = float(m.get("input_per_million_usd", 0.0))
            cout = float(m.get("output_per_million_usd", 0.0))
            mk = _effective_markup(cfg, pkey, m) / 100.0
            rin = cin * (1 + mk) * (1 + buffer)
            rout = cout * (1 + mk) * (1 + buffer)
            rows.append({
                "provider": pkey,
                "provider_label": prov.get("label", pkey),
                "model": mname,
                "cost_input_per_m": round(cin, 4),
                "cost_output_per_m": round(cout, 4),
                "your_input_per_m": round(rin, 4),
                "your_output_per_m": round(rout, 4),
                "markup_pct": round(mk * 100, 1),
                "margin_input_per_m": round(rin - cin, 4),
                "margin_output_per_m": round(rout - cout, 4),
                "credits_per_m_input": round(rin / credit, 1),
                "credits_per_m_output": round(rout / credit, 1),
                "source_url": prov.get("source_url", ""),
                "as_of": prov.get("as_of", ""),
            })
    loc = cfg.get("local", {})
    if loc:
        lr = float(loc.get("rate_per_million_usd", 0.0))
        rows.append({
            "provider": "local", "provider_label": loc.get("label", "Self-hosted"),
            "model": "(all local models)",
            "cost_input_per_m": 0.0, "cost_output_per_m": 0.0,
            "your_input_per_m": lr, "your_output_per_m": lr,
            "markup_pct": None, "margin_input_per_m": lr, "margin_output_per_m": lr,
            "credits_per_m_input": round(lr / credit, 1), "credits_per_m_output": round(lr / credit, 1),
            "source_url": "", "as_of": loc.get("strategy", ""),
        })
    rows.sort(key=lambda r: (r["provider"] != "local", r["provider"], r["model"]))
    return {
        "settings": {k: cfg[k] for k in ("credit_value_usd", "default_markup_pct", "buffer_pct", "local") if k in cfg},
        "rows": rows,
        "provider_count": len(cfg.get("providers", {})),
        "model_count": sum(len(p.get("models", {})) for p in cfg.get("providers", {}).values()),
    }


@router.get("/rates")
async def get_rates():
    return JSONResponse(_compute(_load()))


@router.put("/rates")
async def update_rates(patch: Dict[str, Any] = Body(...)):
    cfg = _load()
    for k in ("credit_value_usd", "default_markup_pct", "buffer_pct", "local"):
        if k in patch:
            cfg[k] = patch[k]
    for pkey, pv in (patch.get("providers") or {}).items():
        prov = cfg["providers"].setdefault(pkey, {"label": pkey, "models": {}})
        if "markup_pct" in pv:
            prov["markup_pct"] = pv["markup_pct"]
        if "label" in pv:
            prov["label"] = pv["label"]
        for mname, mv in (pv.get("models") or {}).items():
            prov["models"].setdefault(mname, {}).update(mv)
    _save(cfg)
    return JSONResponse(_compute(cfg))


@router.post("/seed")
async def seed_costs(payload: Dict[str, Any] = Body(...)):
    """Replace/merge the provider COST table (rate-research job). Preserves markup overrides."""
    cfg = _load()
    for pkey, pv in (payload.get("providers") or {}).items():
        prov = cfg["providers"].setdefault(pkey, {"label": pv.get("label", pkey), "models": {}})
        prov["label"] = pv.get("label", prov.get("label", pkey))
        prov["source_url"] = pv.get("source_url", prov.get("source_url", ""))
        prov["as_of"] = pv.get("as_of", prov.get("as_of", ""))
        for mname, mv in (pv.get("models") or {}).items():
            mm = prov["models"].setdefault(mname, {})
            mm["input_per_million_usd"] = mv.get("input_per_million_usd", mm.get("input_per_million_usd", 0.0))
            mm["output_per_million_usd"] = mv.get("output_per_million_usd", mm.get("output_per_million_usd", 0.0))
            mm.setdefault("override_markup_pct", None)
    _save(cfg)
    return JSONResponse(_compute(cfg))
