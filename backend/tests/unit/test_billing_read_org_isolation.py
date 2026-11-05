"""Registered Lago billing routes never fall back to another org sharing email."""
import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock
import sys

import httpx
import pytest
from fastapi import FastAPI, HTTPException

BACKEND = Path(__file__).resolve().parents[2]
ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def billing(monkeypatch):
    import billing_org_identity as identity
    # Provider tests authenticate one subject with persisted membership in both
    # fixture tenants. Selected context still chooses exactly one tenant.
    monkeypatch.setattr(identity, "_membership_orgs", AsyncMock(return_value=[
        {"org_id": ORG_A, "role": "owner"}, {"org_id": ORG_B, "role": "owner"},
    ]))
    # Execute the complete modules and mount their real router; only import-time
    # credential access and provider I/O are replaced, so no services are used.
    credentials = ModuleType("get_credential")
    credentials.get_credential = lambda name: None
    monkeypatch.setitem(sys.modules, "get_credential", credentials)
    modules = []
    for name in ("lago_integration", "billing_api"):
        spec = importlib.util.spec_from_file_location(name, BACKEND / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    lago, api = modules
    invoice = {"lago_id": "invoice-a", "number": "A", "file_url": "https://example.invalid/a.pdf"}
    async def invoices(org, limit=10):
        return [invoice] if org == f"org_{ORG_A}" else []
    async def subscription(org):
        return {"status": "active"} if org == f"org_{ORG_A}" else None
    monkeypatch.setattr(lago, "get_invoices", AsyncMock(side_effect=invoices))
    monkeypatch.setattr(lago, "get_subscription", AsyncMock(side_effect=subscription))
    monkeypatch.setattr(lago, "get_invoices_by_email", AsyncMock(return_value=[invoice]))
    monkeypatch.setattr(lago, "get_subscription_by_email", AsyncMock(return_value={"status": "active"}))
    monkeypatch.setattr(api, "lago_get_invoice", AsyncMock(return_value=invoice))
    monkeypatch.setattr(api, "lago_download_invoice_pdf", AsyncMock(return_value=b"pdf"))
    monkeypatch.setattr(api, "lago_retry_invoice_payment", AsyncMock(return_value={"ok": True, "detail": "retried"}))
    session = {"org_id": ORG_B, "user": {"sub": "subject", "email": "same@example.test"}}
    monkeypatch.setattr(api, "_load_session", lambda request: session)
    app = FastAPI()
    app.include_router(api.router)
    return lago, api, session, app


@pytest.mark.asyncio
@pytest.mark.parametrize("org", [ORG_B, f"org_{ORG_B}"])
async def test_real_helpers_do_not_fall_back_to_shared_email(billing, org):
    lago, _, _, _ = billing
    assert await lago.get_subscription_for(org, "same@example.test") is None
    assert await lago.get_invoices_for(org, "same@example.test") == []
    lago.get_subscription.assert_awaited_once_with(f"org_{ORG_B}")
    lago.get_invoices.assert_awaited_once_with(f"org_{ORG_B}", limit=10)
    lago.get_subscription_by_email.assert_not_called()
    lago.get_invoices_by_email.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("org", [None, "org_same_example_test", "cus_example"])
async def test_helpers_reject_missing_or_fabricated_org_before_provider(billing, org):
    lago, _, _, _ = billing
    for helper in (lago.get_subscription_for, lago.get_invoices_for):
        with pytest.raises(HTTPException) as exc:
            await helper(org, "same@example.test")
        assert exc.value.status_code == 409
    lago.get_subscription.assert_not_called()
    lago.get_invoices.assert_not_called()
    lago.get_subscription_by_email.assert_not_called()
    lago.get_invoices_by_email.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method", [("invoices", "GET"), ("cycle", "GET"), ("summary", "GET"), ("download-invoice/invoice-a", "POST"), ("invoices/invoice-a/pdf", "GET"), ("invoices/invoice-a/retry", "POST")])
async def test_registered_routes_isolate_shared_email(billing, path, method):
    lago, api, _, app = billing
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, f"/api/v1/billing/{path}")
    if path == "invoices":
        assert response.status_code == 200 and response.json() == []
    elif path == "cycle":
        assert response.status_code == 200 and response.json()["has_cycle"] is False
    elif path == "summary":
        assert response.status_code == 200 and response.json()["invoice_count"] == 0
    else:
        assert response.status_code == 404
    lago.get_invoices_by_email.assert_not_called()
    lago.get_subscription_by_email.assert_not_called()
    api.lago_download_invoice_pdf.assert_not_called()
    api.lago_retry_invoice_payment.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method", [("invoices", "GET"), ("invoices/invoice-a/pdf", "GET"), ("invoices/invoice-a/retry", "POST")])
@pytest.mark.parametrize("context", ["missing", "conflicting"])
async def test_registered_routes_fail_closed_on_invalid_context(billing, path, method, context):
    lago, _, session, app = billing
    if context == "missing":
        session.pop("org_id")
    else:
        session["user"]["org_id"] = ORG_A
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, f"/api/v1/billing/{path}")
    assert response.status_code == 409
    lago.get_invoices.assert_not_called()
    lago.get_invoices_by_email.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method", [("invoices/invoice-a/pdf", "GET"), ("invoices/invoice-a/retry", "POST")])
async def test_org_admin_does_not_bypass_selected_org(billing, path, method):
    _, api, session, app = billing
    session["user"]["role"] = "admin"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, f"/api/v1/billing/{path}")
    assert response.status_code == 404
    api.lago_get_invoice.assert_not_called()
    api.lago_download_invoice_pdf.assert_not_called()
    api.lago_retry_invoice_payment.assert_not_called()


@pytest.mark.asyncio
async def test_authorized_invoice_access_and_retry_use_same_org(billing):
    lago, api, session, app = billing
    session.pop("org_id")
    session["user"]["attributes"] = {"org_id": [ORG_A]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/billing/invoices/invoice-a/pdf")).status_code == 200
        for _ in range(2):
            assert (await client.post("/api/v1/billing/invoices/invoice-a/retry")).status_code == 200
    assert api.lago_retry_invoice_payment.await_count == 2
    assert all(call.args == (f"org_{ORG_A}",) for call in lago.get_invoices.await_args_list)
    lago.get_invoices_by_email.assert_not_called()
