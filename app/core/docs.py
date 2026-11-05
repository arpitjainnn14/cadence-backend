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

# Exact CDN versions, not FastAPI's floating swagger-ui-dist@5 / redoc@2: these pages are same-origin
# and logged in, so a floating version could load unexpected code next to the session.
SWAGGER_UI_VERSION = "5.34.1"
REDOC_VERSION = "2.5.4"
_CDN = "https://cdn.jsdelivr.net/npm"
SWAGGER_JS_URL = f"{_CDN}/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui-bundle.js"
SWAGGER_CSS_URL = f"{_CDN}/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui.css"
REDOC_JS_URL = f"{_CDN}/redoc@{REDOC_VERSION}/bundles/redoc.standalone.js"
SPLICE_MARKER = "SwaggerUIBundle({"

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
    page = get_swagger_ui_html(
        openapi_url=OPENAPI_URL, title="Cadence API",
        swagger_js_url=SWAGGER_JS_URL, swagger_css_url=SWAGGER_CSS_URL,
    )
    html = page.body.decode()
    if SPLICE_MARKER not in html:  # never serve Swagger without the CSRF interceptor
        raise RuntimeError(f"Swagger UI HTML has no {SPLICE_MARKER!r}; cannot add the CSRF interceptor")
    html = html.replace(SPLICE_MARKER, SPLICE_MARKER + "\n    " + CSRF_INTERCEPTOR, 1)
    return HTMLResponse(html)


@router.get("/redoc")
def redoc() -> HTMLResponse:
    return get_redoc_html(openapi_url=OPENAPI_URL, title="Cadence API", redoc_js_url=REDOC_JS_URL)
