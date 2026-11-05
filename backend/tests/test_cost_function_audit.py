"""
Task 11 — Cost function audit regression tests.

Run (on ops-center container or with PYTHONPATH=backend):
  pytest backend/tests/test_cost_function_audit.py -q
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.environ.get("APP_PATH", "/app"))

from litellm_credit_system import (
    CreditSystem,
    CREDIT_MARKUP_MULTIPLIER,
    CONSERVATIVE_DEFAULT_USD_PER_MTOK,
    MODEL_RATES_USD_PER_MTOK,
)


def _system(db_rows=None):
    """CreditSystem with mocked pool/redis. db_rows: list of dicts returned by fetchrow."""
    # asyncpg's pool.acquire() returns an async context manager directly; it is
    # not itself awaitable. Keep the pool/context manager synchronous and only
    # mock the connection methods as async.
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    rows = list(db_rows or [])

    async def fetchrow(query, *args):
        if not rows:
            return None
        # return first matching name if present
        for r in rows:
            if args and r.get("name") == args[0]:
                return r
            if args and str(r.get("name", "")).lower() == str(args[0]).lower():
                return r
        return rows[0] if rows else None

    conn.fetchrow.side_effect = fetchrow
    redis = AsyncMock()
    return CreditSystem(pool, redis), conn


class TestFreeGuard:
    def test_is_free_model_suffix(self):
        assert CreditSystem.is_free_model("google/gemini-2.0-flash-exp:free") is True
        assert CreditSystem.is_free_model("openai/gpt-4o") is False
        assert CreditSystem.is_free_model(None, "meta-llama/llama-3.3-70b-instruct:free") is True
        # Provider echo without :free, request still free
        assert CreditSystem.is_free_model("google/gemini-2.0-flash-exp", "google/gemini-2.0-flash-exp:free") is True

    @pytest.mark.asyncio
    async def test_free_model_costs_zero_even_when_echo_strips_suffix(self):
        system, _ = _system()
        # Provider echoed without :free; request_model still free
        cost = await system.calculate_cost(
            tokens_used=10_000,
            model="google/gemini-2.0-flash-exp",
            request_model="google/gemini-2.0-flash-exp:free",
            prompt_tokens=8000,
            completion_tokens=2000,
        )
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_free_model_id_on_billed_model_alone(self):
        system, _ = _system()
        cost = await system.calculate_cost(
            tokens_used=5000,
            model="openai/gpt-oss-20b:free",
            prompt_tokens=4000,
            completion_tokens=1000,
        )
        assert cost == 0.0


class TestLedgerAttribution:
    def test_local_uses_catalog_provider_and_requested_alias(self):
        provider, model = CreditSystem.ledger_attribution(
            "Qwen_Qwen3.6-35B-A3B-Q4_K_M",
            "uc/qwen3.6-35b-a3b",
            "UC Gateway Local",
            True,
        )
        assert provider == "UC Gateway Local"
        assert model == "uc/qwen3.6-35b-a3b"

    def test_cloud_preserves_served_model_convention(self):
        provider, model = CreditSystem.ledger_attribution(
            "qwen/qwen3.6-flash",
            "qwen-flash",
            "DashScope",
            False,
        )
        assert provider == "qwen/qwen3.6-flash"
        assert model == "qwen/qwen3.6-flash"


class TestPerModelInputOutput:
    @pytest.mark.asyncio
    async def test_1b_model_near_published_rate(self):
        system, _ = _system([
            {
                "name": "meta-llama/llama-3.2-1b-instruct",
                "cost_per_1m_input_tokens": 0.005,
                "cost_per_1m_output_tokens": 0.010,
            }
        ])
        # 500k in + 500k out = 0.5*0.005 + 0.5*0.010 = 0.0025 + 0.005 = 0.0075
        cost = await system.calculate_cost(
            tokens_used=1_000_000,
            model="meta-llama/llama-3.2-1b-instruct",
            prompt_tokens=500_000,
            completion_tokens=500_000,
        )
        assert cost == pytest.approx(0.0075 * CREDIT_MARKUP_MULTIPLIER, rel=1e-6)
        # Effective blended $/Mtok = 0.0075 → far below the old ~2.52 bug
        assert cost < 0.05

    @pytest.mark.asyncio
    async def test_gpt4o_output_costs_more_than_input(self):
        system, _ = _system([
            {
                "name": "openai/gpt-4o",
                "cost_per_1m_input_tokens": 2.50,
                "cost_per_1m_output_tokens": 10.00,
            }
        ])
        in_only = await system.calculate_cost(
            tokens_used=1_000_000,
            model="openai/gpt-4o",
            prompt_tokens=1_000_000,
            completion_tokens=0,
        )
        out_only = await system.calculate_cost(
            tokens_used=1_000_000,
            model="openai/gpt-4o",
            prompt_tokens=0,
            completion_tokens=1_000_000,
        )
        assert in_only == pytest.approx(2.50 * CREDIT_MARKUP_MULTIPLIER, rel=1e-6)
        assert out_only == pytest.approx(10.00 * CREDIT_MARKUP_MULTIPLIER, rel=1e-6)
        assert out_only > in_only

    @pytest.mark.asyncio
    async def test_gpt4o_mini_hand_computed(self):
        system, _ = _system([
            {
                "name": "openai/gpt-4o-mini",
                "cost_per_1m_input_tokens": 0.15,
                "cost_per_1m_output_tokens": 0.60,
            }
        ])
        # 1000 prompt + 500 completion
        cost = await system.calculate_cost(
            tokens_used=1500,
            model="openai/gpt-4o-mini",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        expected = (1000 / 1e6) * 0.15 + (500 / 1e6) * 0.60
        assert cost == pytest.approx(round(expected * CREDIT_MARKUP_MULTIPLIER, 6), rel=1e-6)

    @pytest.mark.asyncio
    async def test_claude_sonnet_from_static_table(self):
        system, _ = _system([])  # no DB row → static
        cost = await system.calculate_cost(
            tokens_used=2_000,
            model="anthropic/claude-3.5-sonnet",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        expected = (1000 / 1e6) * 3.0 + (1000 / 1e6) * 15.0
        assert cost == pytest.approx(round(expected * CREDIT_MARKUP_MULTIPLIER, 6), rel=1e-6)

    @pytest.mark.asyncio
    async def test_local_is_free(self):
        system, _ = _system()
        cost = await system.calculate_cost(
            tokens_used=50_000,
            model="Qwen_Qwen3.6-35B-A3B-Q4_K_M",
            is_local=True,
            prompt_tokens=40_000,
            completion_tokens=10_000,
        )
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_metered_local_uses_catalog_split_rates_and_markup(self):
        system, _ = _system([
            {
                "name": "uc/qwen3.6-35b-a3b",
                "cost_per_1m_input_tokens": 0.028,
                "cost_per_1m_output_tokens": 0.20,
            }
        ])
        cost = await system.calculate_cost(
            tokens_used=1_000_000,
            model="qwen3.6-35b-a3b",
            request_model="uc/qwen3.6-35b-a3b",
            is_local=True,
            use_catalog_local_rates=True,
            prompt_tokens=500_000,
            completion_tokens=500_000,
        )
        expected = (0.5 * 0.028 + 0.5 * 0.20) * CREDIT_MARKUP_MULTIPLIER
        assert cost == pytest.approx(expected, rel=1e-6)

    @pytest.mark.asyncio
    async def test_bare_provider_not_flat_six(self):
        """Bare 'openai' must not land on the old $6/Mtok middleware rate."""
        system, _ = _system([])  # unknown → conservative default
        cost = await system.calculate_cost(
            tokens_used=1_000_000,
            model="openai",
            prompt_tokens=500_000,
            completion_tokens=500_000,
        )
        # Conservative default: 0.5*5 + 0.5*15 = 10.0, NOT 6.0
        expected = 0.5 * CONSERVATIVE_DEFAULT_USD_PER_MTOK["input"] + 0.5 * CONSERVATIVE_DEFAULT_USD_PER_MTOK["output"]
        assert cost == pytest.approx(expected * CREDIT_MARKUP_MULTIPLIER, rel=1e-6)
        assert abs(cost - 6.0) > 0.5

    @pytest.mark.asyncio
    async def test_power_level_does_not_discount(self):
        system, _ = _system([
            {
                "name": "openai/gpt-4o-mini",
                "cost_per_1m_input_tokens": 0.15,
                "cost_per_1m_output_tokens": 0.60,
            }
        ])
        a = await system.calculate_cost(
            tokens_used=10_000, model="openai/gpt-4o-mini",
            power_level="eco", prompt_tokens=5000, completion_tokens=5000,
        )
        b = await system.calculate_cost(
            tokens_used=10_000, model="openai/gpt-4o-mini",
            power_level="precision", prompt_tokens=5000, completion_tokens=5000,
        )
        assert a == b

    @pytest.mark.asyncio
    async def test_markup_multiplier_is_single_lever(self):
        system, _ = _system([
            {
                "name": "openai/gpt-4o-mini",
                "cost_per_1m_input_tokens": 0.15,
                "cost_per_1m_output_tokens": 0.60,
            }
        ])
        base = await system.calculate_cost(
            tokens_used=1_000_000, model="openai/gpt-4o-mini",
            prompt_tokens=1_000_000, completion_tokens=0,
        )
        assert base == pytest.approx(0.15 * CREDIT_MARKUP_MULTIPLIER, rel=1e-6)


class TestStaticTableCoverage:
    def test_key_models_present(self):
        for mid in [
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "anthropic/claude-3.5-sonnet",
            "meta-llama/llama-3.2-1b-instruct",
            "meta-llama/llama-3.1-8b-instruct",
            "meta-llama/llama-3.3-70b-instruct",
            "uc/chat-default",
        ]:
            assert mid in MODEL_RATES_USD_PER_MTOK
            rates = MODEL_RATES_USD_PER_MTOK[mid]
            assert "input" in rates and "output" in rates
