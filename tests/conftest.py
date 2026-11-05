import os

# Must be set before app modules import: Settings fails closed on dev secrets when cookie_secure=True.
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-0123456789abcdef")  # >= 32 bytes: no HMAC length warnings

from datetime import UTC, datetime

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.auth import service
from app.auth.repository import UserRepository
from app.auth.security import hash_password
from app.core.config import Settings, get_settings
from app.core.db import Base, get_db
from app.main import create_app
from tests.migrations import alembic_config, reset_schema

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/subs_test",
)

if not make_url(TEST_DATABASE_URL).database.endswith("_test"):
    # reset_schema drops the public schema and `db` truncates every table: never aim that at a real database.
    raise RuntimeError(f"Refusing to run tests: TEST_DATABASE_URL database must end with '_test' ({TEST_DATABASE_URL!r})")


@pytest.fixture(scope="session")
def engine():
    import app.models  # noqa: F401  (registers every feature's tables on Base.metadata)

    eng = create_engine(TEST_DATABASE_URL)
    reset_schema(eng)
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session
        session.rollback()
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    if tables:
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client(db):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=TEST_DATABASE_URL, cookie_secure=False
    )
    with TestClient(app) as c:
        yield c


def csrf_headers(client) -> dict[str, str]:
    """X-CSRF-Token header matching the client's csrf_token cookie (sets a cookie if there is none yet)."""
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "test-csrf-token"
        client.cookies.set("csrf_token", token, path="/")
    return {"X-CSRF-Token": token}


EMAIL = "arpit@example.com"
PASSWORD = "correct-horse"


def use_test_sessions(monkeypatch, engine) -> None:
    """Point `app.core.db.SessionLocal` (used by get_db and the CLI) at the test engine."""
    monkeypatch.setattr("app.core.db.SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))


@pytest.fixture
def user(db):
    u = UserRepository(db).create(EMAIL, hash_password(PASSWORD))
    db.commit()
    return u


def login(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


@pytest.fixture
def clock(monkeypatch):
    state = {"now": datetime.now(UTC)}  # real "now" so JWT iat/exp validation (real clock) stays consistent
    monkeypatch.setattr(service, "now", lambda: state["now"])
    return state


def set_refresh_cookie(client, value):
    client.cookies.clear()
    client.cookies.set("refresh_token", value, path="/api/auth")


@pytest.fixture
def real_uow_client(engine, user, monkeypatch):
    """Client using the REAL get_db (commit on success, rollback on exception) on the test DB."""
    use_test_sessions(monkeypatch, engine)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(cookie_secure=False)
    assert get_db not in app.dependency_overrides
    with TestClient(app) as c:
        yield c
