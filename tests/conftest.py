import os

# Must be set before app modules import: Settings fails closed on dev secrets when cookie_secure=True.
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import Base, get_db
from app.main import create_app
from tests.migrations import alembic_config, reset_schema

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/subs_test",
)


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
