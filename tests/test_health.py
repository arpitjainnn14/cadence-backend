def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_db_ok(client):
    resp = client.get("/api/health/db")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_db_unavailable_hides_error(client):
    from app.core.health import get_health_repo

    class Broken:
        def ping(self):
            raise RuntimeError("secret connection string")

    client.app.dependency_overrides[get_health_repo] = lambda: Broken()
    resp = client.get("/api/health/db")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
    assert "secret" not in resp.text
