"""API docs served under /api and gated by login.

They live under /api because the access_token cookie only has path=/api, so the browser
sends it here. FastAPI's own /docs and /openapi.json are disabled in create_app.
"""
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse

from app.auth.deps import current_user

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)], include_in_schema=False)

OPENAPI_URL = "/api/openapi.json"

# Swagger "Try it out" sends cookies automatically (same origin), but CSRFMiddleware also wants an
# X-CSRF-Token header equal to the csrf_token cookie (not httpOnly) on unsafe methods. FastAPI's
# swagger_ui_parameters is serialised to JSON and cannot carry a JS function, so the interceptor
# is spliced into the generated HTML.
CSRF_INTERCEPTOR = """requestInterceptor: (req) => {
        const m = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
        if (m && req.method !== 'GET') req.headers['X-CSRF-Token'] = decodeURIComponent(m[1]);
        return req;
    },
    """


@router.get("/openapi.json")
def openapi_json(request: Request) -> dict[str, Any]:
    return request.app.openapi()


@router.get("/docs")
def swagger_ui() -> HTMLResponse:
    page = get_swagger_ui_html(openapi_url=OPENAPI_URL, title="Cadence API")
    html = page.body.decode().replace("SwaggerUIBundle({", "SwaggerUIBundle({\n    " + CSRF_INTERCEPTOR, 1)
    return HTMLResponse(html)


@router.get("/redoc")
def redoc() -> HTMLResponse:
    return get_redoc_html(openapi_url=OPENAPI_URL, title="Cadence API")
