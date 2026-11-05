import hmac

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
EXEMPT = ("/api/auth/login", "/api/internal/")  # login has no session yet; internal uses a shared secret


class CSRFMiddleware:
    """Double-submit check: X-CSRF-Token header must equal the csrf_token cookie on unsafe /api/ requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._needs_check(scope) and not self._valid(Request(scope)):
            response = JSONResponse({"detail": "CSRF check failed"}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _needs_check(scope: Scope) -> bool:
        path = scope["path"]
        return (
            scope["method"] in UNSAFE_METHODS
            and path.startswith("/api/")
            and not any(path == e or (e.endswith("/") and path.startswith(e)) for e in EXEMPT)
        )

    @staticmethod
    def _valid(request: Request) -> bool:
        header = request.headers.get("x-csrf-token", "")
        cookie = request.cookies.get("csrf_token", "")
        # Bytes, so non-ASCII input cannot make compare_digest raise.
        return bool(cookie) and hmac.compare_digest(header.encode(), cookie.encode())
