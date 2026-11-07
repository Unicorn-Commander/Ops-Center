"""Purchasable plan filtering uses the measured database tier shape."""

import pytest
from unittest.mock import AsyncMock

import subscription_api
import asyncpg


class FakeSubscriptionConnection:
    def __init__(self):
        self.closed = False
        self.tiers = [
            {
                "id": 1,
                "tier_code": "professional",
                "tier_name": "Professional",
                "description": "Internal zero-price tier",
                "price_monthly": 0,
                "price_yearly": 0,
                "api_calls_limit": 10,
                "lago_plan_code": None,
                "sort_order": 1,
            },
            {
                "id": 2,
                "tier_code": "byok",
                "tier_name": "Solo",
                "description": "Bring your own key",
                "price_monthly": 49,
                "price_yearly": 490,
                "api_calls_limit": 100,
                "lago_plan_code": "byok_monthly",
                "sort_order": 2,
            },
            {
                "id": 3,
                "tier_code": "founder_workspace",
                "tier_name": "Team workspace",
                "description": "Five seats",
                "price_monthly": 149,
                "price_yearly": 1490,
                "api_calls_limit": 500,
                "lago_plan_code": "founder_workspace_monthly",
                "sort_order": 3,
            },
            {
                "id": 4,
                "tier_code": "founder_friend",
                "tier_name": "Founder friend",
                "description": "Internal tier",
                "price_monthly": 0,
                "price_yearly": 0,
                "api_calls_limit": 10,
                "lago_plan_code": None,
                "sort_order": 4,
            },
        ]

    async def fetch(self, query, *params):
        if "FROM subscription_tiers" in query:
            assert "AND price_monthly > 0" in query
            excluded = set(params[0])
            return [
                row
                for row in self.tiers
                if row["tier_code"] not in excluded and row["price_monthly"] > 0
            ]
        assert "FROM tier_features" in query
        return []

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_purchasable_tiers_exclude_zero_price_and_internal_tiers(monkeypatch):
    connection = FakeSubscriptionConnection()
    monkeypatch.setattr(asyncpg, "connect", AsyncMock(return_value=connection))

    plans = await subscription_api._fetch_purchasable_tiers()

    assert [plan["tier_code"] for plan in plans] == ["byok", "founder_workspace"]
    assert connection.closed is True
