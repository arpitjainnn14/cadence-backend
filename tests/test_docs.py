import pytest

from tests.conftest import login

PATHS = ("/api/docs", "/api/redoc", "/api/openapi.json")


@pytest.mark.parametrize("path", PATHS)
def test_docs_require_login(client, path):
    assert client.get(path).status_code == 401


def test_docs_served_when_logged_in(client, user):
    assert login(client).status_code == 200
    assert "swagger-ui" in client.get("/api/docs").text
    assert "redoc" in client.get("/api/redoc").text.lower()
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    assert "openapi" in schema.json()
    assert not any(p in schema.json()["paths"] for p in PATHS)  # docs routes excluded from the schema


def test_swagger_html_has_csrf_interceptor(client, user):
    login(client)
    html = client.get("/api/docs").text
    assert "requestInterceptor" in html
    assert "X-CSRF-Token" in html and "csrf_token" in html
    assert "/api/openapi.json" in html


def test_assets_pinned_to_exact_versions(client, user):
    login(client)
    swagger, redoc = client.get("/api/docs").text, client.get("/api/redoc").text
    assert "swagger-ui-dist@5.34.1/" in swagger and "swagger-ui-dist@5/" not in swagger
    assert "redoc@2.5.4/" in redoc and "redoc@2/" not in redoc


def test_swagger_refuses_to_serve_without_interceptor_marker(client, user, monkeypatch):
    from fastapi.responses import HTMLResponse

    from app.core import docs

    monkeypatch.setattr(docs, "get_swagger_ui_html", lambda **kw: HTMLResponse("<html>no marker</html>"))
    login(client)
    with pytest.raises(RuntimeError, match="CSRF interceptor"):
        client.get("/api/docs")
