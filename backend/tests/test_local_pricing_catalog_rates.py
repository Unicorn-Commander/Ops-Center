"""Regression tests for the metered-local catalog-rate decision."""

import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.environ.get("APP_PATH", "/app"))

import local_pricing


@pytest.mark.asyncio
async def test_metered_zero_scalar_selects_catalog_split_rates(monkeypatch):
    monkeypatch.setenv("LOCAL_PRICING_ENABLED", "true")
    monkeypatch.setattr(
        local_pricing,
        "_load_tier_pricing",
        AsyncMock(return_value={"mode": "metered"}),
    )

    decision = await local_pricing.resolve_local_pricing(
        "org-1", "uc/qwen3.6-35b-a3b", 100, tier_code="pro", is_local=True
    )

    assert decision["meter"] is True
    assert decision["local_rate_per_1k"] is None
    assert decision["use_catalog_rates"] is True
    assert decision["reason"] == "metered_catalog"


@pytest.mark.asyncio
async def test_metered_ignores_legacy_scalar_and_keeps_one_rate_source(monkeypatch):
    monkeypatch.setenv("LOCAL_PRICING_ENABLED", "true")
    monkeypatch.setattr(
        local_pricing,
        "_load_tier_pricing",
        AsyncMock(return_value={"mode": "metered", "rate": 0.003}),
    )

    decision = await local_pricing.resolve_local_pricing(
        "org-1", "uc/legacy-local", 100, tier_code="pro", is_local=True
    )

    assert decision["meter"] is True
    assert decision["local_rate_per_1k"] is None
    assert decision["use_catalog_rates"] is True
    assert decision["reason"] == "metered_catalog"
