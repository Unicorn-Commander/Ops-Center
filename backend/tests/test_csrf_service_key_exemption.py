"""CSRF middleware: header-authenticated machine calls (service key / Bearer, no session cookie)
skip the CSRF check; anything carrying a session cookie is still checked like a browser request."""

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from csrf_protection import CSRFMiddleware, CSRFProtection

PATH = "/api/v1/admin/orgs/00000000-0000-0000-0000-000000000001/features"


def _client() -> TestClient:
    async def handler(request):  # noqa: ANN001
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route(PATH, handler, methods=["POST"])])
    app.add_middleware(
        CSRFMiddleware,
        csrf_protect=CSRFProtection(secret_key="t" * 32),
        exempt_urls={"/never-matches/"},
        enabled=True,
        sessions_store={},
    )
    return TestClient(app)


def test_post_without_session_or_key_is_refused():
    assert _client().post(PATH, json={}).status_code == 403


def test_service_key_header_without_session_skips_csrf():
    response = _client().post(PATH, json={}, headers={"X-Ops-Center-Service-Key": "not-a-real-key"})
    assert response.status_code == 200


def test_bearer_header_without_session_skips_csrf():
    response = _client().post(PATH, json={}, headers={"Authorization": "Bearer not-a-real-key"})
    assert response.status_code == 200


def test_service_key_header_with_session_cookie_is_still_checked():
    client = _client()
    client.cookies.set("session_token", "browser-session")
    response = client.post(PATH, json={}, headers={"X-Ops-Center-Service-Key": "not-a-real-key"})
    assert response.status_code == 403
