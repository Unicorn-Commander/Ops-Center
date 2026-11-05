"""Tests for the public A2A and suite MCP discovery endpoints."""

import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth_middleware import AuthenticationMiddleware  # noqa: E402
from colonel import a2a_server  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    async def fake_build_card(colonel_id, base_url):
        return {
            "name": "The Colonel",
            "description": "The Colonel test card",
            "url": f"{base_url}/a2a",
            "version": "1.0.0",
            "provider": {"organization": "Test", "url": "https://example.test"},
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "skillInvocation": True,
            },
            "authentication": {"schemes": ["bearer"]},
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "skills": [],
        }

    monkeypatch.setattr(a2a_server, "_build_card_for", fake_build_card)
    app = FastAPI()
    app.include_router(a2a_server.router)
    return app


@pytest.mark.asyncio
async def test_current_agent_card_is_public_and_uses_current_shape(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    card = response.json()
    assert card["name"] == "The Colonel"
    assert card["protocolVersion"] == "0.3.0"
    assert card["preferredTransport"] == "JSONRPC"
    assert card["securitySchemes"]["bearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert card["security"] == [{"bearer": []}]
    assert card["capabilities"]["streaming"] is False
    assert card["capabilities"]["pushNotifications"] is False
    assert "tasks/get" not in card["capabilities"]
    assert card["defaultInputModes"] == ["text"]
    assert card["defaultOutputModes"] == ["text"]


@pytest.mark.asyncio
async def test_legacy_agent_card_remains_without_current_only_fields(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/agent.json")

    assert response.status_code == 200
    card = response.json()
    assert card["authentication"] == {"schemes": ["bearer"]}
    assert "protocolVersion" not in card
    assert "securitySchemes" not in card


@pytest.mark.asyncio
async def test_mcp_index_is_public_json_with_nine_https_endpoints(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/mcps.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    manifest = response.json()
    assert manifest["name"] == "Unicorn Commander"
    assert manifest["kind"] == "index"
    assert manifest["version"]
    assert len(manifest["mcps"]) == 9
    assert all(
        entry["mcp_endpoint"].startswith("https://")
        and entry["auth"]["type"] == "bearer"
        for entry in manifest["mcps"]
    )
    project_ops = next(
        entry for entry in manifest["mcps"] if entry["name"] == "project-ops"
    )
    assert (
        project_ops["manifest_url"]
        == "https://projectops.magicunicorn.dev/.well-known/mcps.json"
    )
    assert manifest["docs"].endswith("docs/P-00039-mcp-discovery.md")


def test_well_known_paths_are_public_to_session_auth_middleware():
    assert AuthenticationMiddleware._is_public("/.well-known/agent-card.json", "GET")
    assert AuthenticationMiddleware._is_public("/.well-known/mcps.json", "GET")


@pytest.mark.asyncio
async def test_reserved_card_colonel_id_returns_pointer_404():
    with pytest.raises(HTTPException) as exc_info:
        await a2a_server.agent_card_named("card", None)

    assert exc_info.value.status_code == 404
    assert "agent-card.json" in exc_info.value.detail
