"""Regression coverage for task 13 public catalog ordering."""

from catalog_ordering import model_order_by


def test_default_orders_local_then_direct_then_openrouter():
    normalized = " ".join(model_order_by("representative").lower().split())
    assert "p.type = 'local'" in normalized
    assert "lower(p.name) = 'openrouter' then 2" in normalized
    assert "lower(p.name), avg_cost asc nulls last, lower(m.name), m.id" in normalized


def test_explicit_sort_modes_are_preserved():
    assert model_order_by("cost") == " ORDER BY avg_cost ASC"
    assert model_order_by("latency") == " ORDER BY m.avg_latency_ms ASC NULLS LAST"
    assert model_order_by("context") == " ORDER BY m.context_length DESC"
    assert model_order_by("popularity") == " ORDER BY m.name"
    assert model_order_by("name") == " ORDER BY m.name"
