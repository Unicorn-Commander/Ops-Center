#!/usr/bin/env python3
"""Resolve and wire the live Stripe prices for the founder workspace tier.

The script is deliberately read-only unless ``--apply`` is supplied. Stripe
prices are resolved by lookup key so no live price ID is copied into source or
the migration.

Usage:
    python3 backend/scripts/wire_founder_workspace_prices.py
    python3 backend/scripts/wire_founder_workspace_prices.py --apply
"""

import argparse
import asyncio
import os
from typing import Any, Dict

import asyncpg


MONTHLY_LOOKUP_KEY = "founder_workspace_monthly"
SEAT_LOOKUP_KEY = "founder_workspace_seat_monthly"
TIER_CODE = "founder_workspace"
EXTRA_SEAT_FEATURE_KEY = "extra_seat_stripe_price"


def _field(value: Any, key: str) -> Any:
    """Read a Stripe object or mapping without depending on SDK object type."""
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _resolve_price_id(stripe_module: Any, lookup_key: str) -> str:
    """Resolve exactly one active Stripe price for a lookup key."""
    result = stripe_module.Price.list(
        lookup_keys=[lookup_key],
        active=True,
        limit=2,
    )
    prices = list(_field(result, "data") or [])
    if not prices:
        raise RuntimeError(f"No active Stripe price found for lookup key {lookup_key}")
    if len(prices) > 1:
        raise RuntimeError(f"Multiple active Stripe prices found for lookup key {lookup_key}")
    price_id = _field(prices[0], "id")
    if not price_id:
        raise RuntimeError(f"Stripe price for lookup key {lookup_key} has no ID")
    return str(price_id)


def resolve_prices(stripe_module: Any) -> Dict[str, str]:
    """Resolve both required prices from Stripe lookup keys."""
    return {
        "monthly_price_id": _resolve_price_id(stripe_module, MONTHLY_LOOKUP_KEY),
        "seat_price_id": _resolve_price_id(stripe_module, SEAT_LOOKUP_KEY),
    }


def _load_stripe() -> Any:
    """Load Stripe and configure it from the secret environment variable."""
    try:
        import stripe
    except ImportError as exc:
        raise SystemExit("Stripe library is not installed") from exc

    secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not secret_key:
        raise SystemExit("STRIPE_SECRET_KEY environment variable is required")

    # Never print or include this value in an exception. The SDK uses it for
    # authentication on the following Price.list calls only.
    stripe.api_key = secret_key
    return stripe


async def _apply_database_updates(prices: Dict[str, str]) -> None:
    """Persist resolved IDs atomically for the founder workspace tier."""
    conn = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "unicorn-postgresql"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "unicorn"),
        password=os.getenv("POSTGRES_PASSWORD", "unicorn"),
        database=os.getenv("POSTGRES_DB", "unicorn_db"),
    )
    try:
        async with conn.transaction():
            tier = await conn.fetchrow(
                "SELECT id FROM subscription_tiers WHERE tier_code = $1 FOR UPDATE",
                TIER_CODE,
            )
            if not tier:
                raise RuntimeError(f"Tier {TIER_CODE} is missing; apply its migration first")

            await conn.execute(
                """
                UPDATE subscription_tiers
                SET stripe_price_monthly = $1,
                    updated_at = NOW(),
                    updated_by = 'wire_founder_workspace_prices'
                WHERE tier_code = $2
                """,
                prices["monthly_price_id"],
                TIER_CODE,
            )
            await conn.execute(
                """
                INSERT INTO tier_features (tier_id, feature_key, feature_value, enabled)
                VALUES ($1, $2, $3, TRUE)
                ON CONFLICT (tier_id, feature_key) DO UPDATE
                SET feature_value = EXCLUDED.feature_value,
                    enabled = TRUE,
                    updated_at = NOW()
                """,
                tier["id"],
                EXTRA_SEAT_FEATURE_KEY,
                prices["seat_price_id"],
            )
    finally:
        await conn.close()


def main(argv=None) -> None:
    """Resolve prices and optionally persist them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the resolved IDs to subscription_tiers and tier_features",
    )
    args = parser.parse_args(argv)

    stripe_module = _load_stripe()
    try:
        prices = resolve_prices(stripe_module)
    except Exception as exc:
        # Do not dump SDK exception bodies: authentication errors can contain
        # request details. The exception class is enough for an operator.
        raise SystemExit(f"Stripe price lookup failed ({type(exc).__name__})") from None

    if not args.apply:
        print("Dry run: no database writes will be made.")
        print(f"{TIER_CODE}.stripe_price_monthly <- {prices['monthly_price_id']}")
        print(
            f"{EXTRA_SEAT_FEATURE_KEY} <- {prices['seat_price_id']} "
            f"({SEAT_LOOKUP_KEY})"
        )
        return

    try:
        asyncio.run(_apply_database_updates(prices))
    except Exception as exc:
        raise SystemExit(f"Database update failed ({type(exc).__name__})") from None
    print(f"Wired Stripe prices for {TIER_CODE}.")


if __name__ == "__main__":
    main()
