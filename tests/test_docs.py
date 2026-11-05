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
