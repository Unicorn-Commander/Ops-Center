"""Stripe automatic tax is opt-in (STRIPE_AUTOMATIC_TAX=1); off by default the checkout kwargs are unchanged."""
import importlib


def _reload(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("STRIPE_AUTOMATIC_TAX", raising=False)
    else:
        monkeypatch.setenv("STRIPE_AUTOMATIC_TAX", value)
    import stripe_integration
    return importlib.reload(stripe_integration)


def test_tax_off_by_default(monkeypatch):
    mod = _reload(monkeypatch, None)
    assert mod._tax_kwargs() == {}


def test_tax_on_when_flagged(monkeypatch):
    mod = _reload(monkeypatch, "1")
    kw = mod._tax_kwargs()
    assert kw["automatic_tax"] == {"enabled": True}
    assert kw["customer_update"] == {"address": "auto", "name": "auto"}
    assert kw["billing_address_collection"] == "required"


def test_tax_flag_values(monkeypatch):
    for v, expected in (("true", True), ("YES", True), ("0", False), ("", False)):
        mod = _reload(monkeypatch, v)
        assert bool(mod._tax_kwargs()) is expected
