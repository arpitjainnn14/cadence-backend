def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_db_ok(client):
    resp = client.get("/api/health/db")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_repository_ping(db):
    from app.core.health import HealthRepository

    HealthRepository(db).ping()


def test_health_db_unavailable_hides_error(client, caplog):
    from sqlalchemy import text

    from app.core.health import HealthRepository, get_health_repo

    class Broken(HealthRepository):
        def ping(self):
            self.db.execute(text("SELECT 1/0"))  # aborts the transaction; only reset() makes get_db's commit safe

    client.app.dependency_overrides[get_health_repo] = lambda: Broken(client_db(client))
    try:
        with caplog.at_level("ERROR", logger="app.health"):
            resp = client.get("/api/health/db")
    finally:
        client.app.dependency_overrides.pop(get_health_repo, None)
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
    client_db(client).execute(text("SELECT 1"))  # fails with InFailedSqlTransaction unless reset() rolled back
    assert "division by zero" not in resp.text
    assert "db health check failed" in caplog.text


def client_db(client):
    from app.core.db import get_db

    return client.app.dependency_overrides[get_db]()


def test_health_db_503_even_if_reset_fails(client):
    from sqlalchemy import text

    from app.core.health import HealthRepository, get_health_repo

    class Broken(HealthRepository):
        def ping(self):
            raise RuntimeError("down")

        def reset(self):
            raise RuntimeError("rollback failed")

    client.app.dependency_overrides[get_health_repo] = lambda: Broken(client_db(client))
    try:
        resp = client.get("/api/health/db")
    finally:
        client.app.dependency_overrides.pop(get_health_repo, None)
    assert resp.status_code == 503
