"""Focused contract test for the public pricing tier ladder."""

from decimal import Decimal

import pytest

import pricing_packages_api


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *exc_info):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


class _PricingConnection:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, query, *params):
        normalized = " ".join(query.split())
        if "FROM subscription_tiers" in normalized:
            assert "WHERE is_active = true" in normalized
            assert "tier_code = ANY($1::text[])" in normalized
            assert "ORDER BY sort_order, price_monthly" in normalized
            allowed_codes = set(params[0])
            return sorted(
                (
                    row
                    for row in self.rows
                    if row["is_active"] and row["tier_code"] in allowed_codes
                ),
                key=lambda row: (row["sort_order"], row["price_monthly"]),
            )

        raise AssertionError(f"unexpected query: {normalized}")


def _tier(code, name, price, sort_order, *, active=True, invite_only=False):
    monthly_price = Decimal(str(price))
    return {
        "tier_code": code,
        "tier_name": name,
        "display_name": name,
        "description": f"Fictional fixture for {name}.",
        "monthly_price_usd": monthly_price,
        "annual_price_usd": None,
        "annual_discount_pct": None,
        "api_calls_limit": -1,
        "is_popular": False,
        "badge_text": None,
        "sort_order": sort_order,
        "stripe_price_monthly_configured": False,
        "stripe_price_yearly_configured": False,
        "is_active": active,
        "is_invite_only": invite_only,
        "price_monthly": monthly_price,
    }


@pytest.mark.asyncio
async def test_public_pricing_lists_active_ladder_in_sort_order(monkeypatch):
    rows = [
        _tier("free", "Free", 0, 0),
        _tier("byok", "Solo", 49, 3),
        _tier("founder_workspace", "Team workspace", 149, 3),
        _tier("fictional_retired", "Fictional retired", 999, 1, active=False),
    ]
    connection = _PricingConnection(rows)

    async def _get_pool(_request):
        return _Pool(connection)

    monkeypatch.setattr(
        pricing_packages_api,
        "PUBLIC_TIER_CODES",
        ["free", "byok", "founder_workspace", "fictional_retired"],
    )
    monkeypatch.setattr(
        pricing_packages_api,
        "get_db_pool",
        _get_pool,
    )

    tiers = await pricing_packages_api.get_public_pricing_tiers(
        object(), include_features=False
    )

    assert [tier.tier_name for tier in tiers] == ["Free", "Solo", "Team workspace"]
    assert "fictional_retired" not in {tier.tier_code for tier in tiers}
