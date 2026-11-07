"""ASGI path aliases for the OpenAI-compatible ``/v1`` surface."""


class OpenAIV1AliasMiddleware:
    """Rewrite OpenAI SDK paths to the existing versioned API routers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path") or ""
            if path == "/v1" or path.startswith("/v1/"):
                rest = path[3:]
                if rest == "" or rest == "/":
                    new_path = "/api/v1/llm/models"
                elif rest.startswith("/audio"):
                    new_path = f"/api/v1{rest}"
                else:
                    new_path = f"/api/v1/llm{rest}"
                scope = dict(scope)
                scope["path"] = new_path
                scope["raw_path"] = new_path.encode("utf-8")
        await self.app(scope, receive, send)
