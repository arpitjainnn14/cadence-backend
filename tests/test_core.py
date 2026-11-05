import base64

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core import db as db_module
from app.core.config import Settings
from app.main import create_app


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


STRONG = {"jwt_secret": "x" * 32, "scheduler_secret": "y" * 32, "cookie_secure": True}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def vapid_keys() -> dict[str, str]:
    """A freshly generated pair in the raw base64url form `web-push generate-vapid-keys` prints."""
    key = ec.generate_private_key(ec.SECP256R1())
    return {
        "vapid_private_key": _b64url(key.private_numbers().private_value.to_bytes(32, "big")),
        "vapid_public_key": _b64url(
            key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        ),
        "vapid_subject": "mailto:a@example.com",
    }


def test_empty_vapid_rejected_when_cookie_secure():
    with pytest.raises(ValueError, match="vapid_private_key"):
        Settings(**STRONG)


def test_bad_vapid_subject_rejected_when_cookie_secure(vapid_keys):
    with pytest.raises(ValueError, match="vapid_subject"):
        Settings(**STRONG, **{**vapid_keys, "vapid_subject": "dev"})


def test_pem_private_key_rejected_when_cookie_secure(vapid_keys):
    pem = "-----BEGIN PRIVATE KEY-----\nMIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg\n-----END PRIVATE KEY-----\n"
    with pytest.raises(ValueError, match="vapid_private_key"):
        Settings(**STRONG, **{**vapid_keys, "vapid_private_key": pem})


@pytest.mark.parametrize("public", ["not-a-key", "AAAA", "!!!!"])
def test_bad_public_key_rejected_when_cookie_secure(vapid_keys, public):
    with pytest.raises(ValueError, match="vapid_public_key"):
        Settings(**STRONG, **{**vapid_keys, "vapid_public_key": public})


def test_public_key_without_uncompressed_prefix_rejected(vapid_keys):
    raw = base64.urlsafe_b64decode(vapid_keys["vapid_public_key"] + "==")
    with pytest.raises(ValueError, match="vapid_public_key"):
        Settings(**STRONG, **{**vapid_keys, "vapid_public_key": _b64url(b"\x02" + raw[1:])})


def test_dev_secret_rejected_when_cookie_secure():
    with pytest.raises(ValidationError):
        Settings(cookie_secure=True)


def test_short_secret_rejected_when_cookie_secure(vapid_keys):
    with pytest.raises(ValidationError):
        Settings(cookie_secure=True, jwt_secret="x" * 31, scheduler_secret="y" * 32, **vapid_keys)


def test_strong_secrets_and_real_vapid_keys_allowed_when_cookie_secure(vapid_keys):
    Settings(**STRONG, **vapid_keys)


def test_unpadded_and_padded_public_key_both_accepted(vapid_keys):
    Settings(**STRONG, **{**vapid_keys, "vapid_public_key": vapid_keys["vapid_public_key"] + "="})


def test_dev_secret_allowed_when_cookie_insecure(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")  # conftest sets a long test secret; check the built-in default
    assert Settings(_env_file=None, cookie_secure=False).jwt_secret == "dev-insecure"


def test_builtin_docs_disabled_in_production(vapid_keys):
    client = TestClient(create_app(Settings(**STRONG, **vapid_keys)))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/api/health").status_code == 200


def test_builtin_docs_disabled_in_development():
    client = TestClient(create_app(Settings(_env_file=None, cookie_secure=False)))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_engine_options_on_vercel_uses_nullpool():
    from sqlalchemy.pool import NullPool

    from app.core.db import engine_options

    opts = engine_options({"VERCEL": "1"})
    assert opts["poolclass"] is NullPool
    assert opts["connect_args"] == {"prepare_threshold": None}
    assert "pool_recycle" not in opts


def test_engine_options_default_keeps_pool_settings():
    from app.core.db import engine_options

    opts = engine_options({})
    assert "poolclass" not in opts
    assert opts["pool_pre_ping"] is True
    assert opts["pool_recycle"] == 300
    assert opts["connect_args"] == {"prepare_threshold": None}


def test_mismatched_vapid_pair_rejected_when_cookie_secure(vapid_keys):
    key = ec.generate_private_key(ec.SECP256R1())
    other_public = _b64url(
        key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    with pytest.raises(ValueError, match="does not match"):
        Settings(**STRONG, **{**vapid_keys, "vapid_public_key": other_public})
