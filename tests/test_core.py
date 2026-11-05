import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core import db as db_module
from app.core.config import Settings


@pytest.fixture
def probe_table(engine, monkeypatch):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE uow_probe (id int)"))
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    yield
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE uow_probe"))


def _count(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM uow_probe")).scalar_one()


def test_get_db_commits_on_normal_exit(engine, probe_table):
    gen = db_module.get_db()
    session = next(gen)
    session.execute(text("INSERT INTO uow_probe VALUES (1)"))
    with pytest.raises(StopIteration):
        next(gen)
    assert _count(engine) == 1


def test_get_db_rolls_back_and_reraises_on_exception(engine, probe_table):
    gen = db_module.get_db()
    session = next(gen)
    session.execute(text("INSERT INTO uow_probe VALUES (1)"))
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))
    assert _count(engine) == 0


def test_dev_secret_rejected_when_cookie_secure():
    with pytest.raises(ValidationError):
        Settings(cookie_secure=True)


def test_short_secret_rejected_when_cookie_secure():
    with pytest.raises(ValidationError):
        Settings(cookie_secure=True, jwt_secret="x" * 31, scheduler_secret="y" * 32)


def test_strong_secrets_allowed_when_cookie_secure():
    Settings(cookie_secure=True, jwt_secret="x" * 32, scheduler_secret="y" * 32)


def test_dev_secret_allowed_when_cookie_insecure(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")  # conftest sets a long test secret; check the built-in default
    assert Settings(_env_file=None, cookie_secure=False).jwt_secret == "dev-insecure"
