from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import RefreshToken
from app.auth.repository import RefreshTokenRepository, UserRepository
from app.auth.security import (
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.core.config import get_settings
from tests.conftest import EMAIL, PASSWORD, csrf_headers, login, set_refresh_cookie

# --- security primitives ---


def test_password_hash_is_argon2():
    h = hash_password("x")
    assert h.startswith("$argon2")
    assert verify_password("x", h)
    assert not verify_password("y", h)


def test_refresh_token_is_random_and_hashed():
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b and len(a) >= 43
    assert hash_token(a) == hash_token(a) != a and len(hash_token(a)) == 64


def test_access_token_roundtrip_and_claims(user):
    token = create_access_token(user.id)
    assert decode_access_token(token) == user.id
    claims = jwt.decode(token, options={"verify_signature": False})
    assert set(claims) == {"sub", "exp", "iat", "jti", "type"}
    assert claims["type"] == "access"


def test_decode_rejects_garbage():
    with pytest.raises(InvalidToken):
        decode_access_token("not-a-jwt")


# --- HTTP ---


def test_login_sets_httponly_cookies(client, user):
    r = login(client)
    assert r.status_code == 200
    assert r.json() == {"email": EMAIL}
    cookies = {h.split("=", 1)[0]: h for h in r.headers.get_list("set-cookie")}
    assert "HttpOnly" in cookies["access_token"] and "Path=/api;" in cookies["access_token"]
    assert "HttpOnly" in cookies["refresh_token"] and "Path=/api/auth" in cookies["refresh_token"]
    assert "Max-Age=900" in cookies["access_token"]
    assert "Max-Age=2592000" in cookies["refresh_token"]
    assert "HttpOnly" not in cookies["csrf_token"] and "Path=/;" in cookies["csrf_token"]
    assert all("SameSite=lax" in c for c in cookies.values())
    for name in ("access_token", "refresh_token"):
        assert client.cookies[name] not in r.text


def test_login_email_is_case_insensitive(client, user):
    assert login(client, email="  Arpit@Example.COM ").status_code == 200


def test_login_wrong_password_401(client, user):
    r = login(client, password="nope")
    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid email or password"}


def test_login_unknown_email_401(client, user):
    wrong_pw = login(client, password="nope").json()
    unknown = login(client, email="who@example.com")
    assert unknown.status_code == 401
    assert unknown.json() == wrong_pw


def test_me_requires_auth(client, user):
    assert client.get("/api/auth/me").status_code == 401
    login(client)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"email": EMAIL}


def test_expired_access_token_401(client, user):
    token = create_access_token(user.id, now=datetime.now(UTC) - timedelta(minutes=16))
    client.cookies.set("access_token", token, path="/api")
    assert client.get("/api/auth/me").status_code == 401


def test_token_with_wrong_alg_or_type_rejected(client, user):
    now = datetime.now(UTC)
    claims = {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=5), "jti": "x"}
    secret = get_settings().jwt_secret
    bad = [
        jwt.encode({**claims, "type": "refresh"}, secret, algorithm="HS256"),
        jwt.encode({**claims, "type": "access"}, secret * 2, algorithm="HS512"),
        jwt.encode({**claims, "type": "access"}, None, algorithm="none"),
        jwt.encode({**claims, "type": "access"}, "x" * 40, algorithm="HS256"),
    ]
    for token in bad:
        client.cookies.clear()
        client.cookies.set("access_token", token, path="/api")
        assert client.get("/api/auth/me").status_code == 401, token


def test_refresh_without_cookie_401(client, user):
    assert client.post("/api/auth/refresh", headers=csrf_headers(client)).status_code == 401


def test_refresh_rotates(real_uow_client, engine, clock):
    client = real_uow_client
    login(client)
    old = client.cookies["refresh_token"]

    r = client.post("/api/auth/refresh", headers=csrf_headers(client))
    assert r.status_code == 200
    new = client.cookies["refresh_token"]
    assert new != old
    assert client.get("/api/auth/me").status_code == 200

    # Old token replayed after the grace window: 401 and the whole family is revoked.
    clock["now"] += timedelta(seconds=11)
    set_refresh_cookie(client, old)
    assert client.post("/api/auth/refresh", headers=csrf_headers(client)).status_code == 401

    # The revocation must have been COMMITTED despite the 401 response (verified from a fresh session).
    with Session(engine) as s:
        rows = s.scalars(select(RefreshToken)).all()
        assert len(rows) == 2 and all(t.revoked_at is not None for t in rows)

    set_refresh_cookie(client, new)
    assert client.post("/api/auth/refresh", headers=csrf_headers(client)).status_code == 401


def test_refresh_race_within_grace(real_uow_client, engine, clock):
    client = real_uow_client
    login(client)
    old = client.cookies["refresh_token"]
    client.post("/api/auth/refresh", headers=csrf_headers(client))
    new = client.cookies["refresh_token"]

    clock["now"] += timedelta(seconds=10)
    set_refresh_cookie(client, old)
    assert client.post("/api/auth/refresh", headers=csrf_headers(client)).status_code == 401

    set_refresh_cookie(client, new)
    assert client.post("/api/auth/refresh", headers=csrf_headers(client)).status_code == 200


def test_expired_refresh_token_401(client, user, clock):
    login(client)
    clock["now"] += timedelta(days=31)
    assert client.post("/api/auth/refresh", headers=csrf_headers(client)).status_code == 401


def test_logout_revokes(client, user):
    login(client)
    old = client.cookies["refresh_token"]
    r = client.post("/api/auth/logout", headers=csrf_headers(client))
    assert r.status_code == 204
    cleared = " ".join(r.headers.get_list("set-cookie"))
    for name in ("access_token", "refresh_token", "csrf_token"):
        assert f"{name}=" in cleared and "Max-Age=0" in cleared
    set_refresh_cookie(client, old)
    assert client.post("/api/auth/refresh", headers=csrf_headers(client)).status_code == 401


def test_logout_without_cookie_is_204(client, user):
    assert client.post("/api/auth/logout", headers=csrf_headers(client)).status_code == 204


# --- repositories ---


def test_user_repository(db):
    repo = UserRepository(db)
    u = repo.create("  Mixed@Case.com ", "hash")
    assert u.email == "mixed@case.com"
    assert repo.get_by_email("MIXED@case.COM").id == u.id
    assert repo.get_by_id(u.id).id == u.id
    assert repo.get_by_email("none@x.com") is None


def test_refresh_token_repository(db, user):
    repo = RefreshTokenRepository(db)
    t0 = datetime(2030, 1, 1, tzinfo=UTC)
    family = user.id  # any uuid works as a family id

    def mk(raw):
        return repo.add(
            RefreshToken(user_id=user.id, family_id=family, token_hash=hash_token(raw), expires_at=t0 + timedelta(days=30))
        )

    a, b, c = mk("a"), mk("b"), mk("c")
    assert repo.get_by_hash(hash_token("a")).id == a.id
    assert repo.get_by_hash(hash_token("zzz")) is None

    repo.mark_rotated(a, t0)
    assert a.revoked_at == t0 and a.replaced_at == t0

    repo.revoke(b, t0)
    assert b.revoked_at == t0 and b.replaced_at is None

    repo.revoke_family(family, t0 + timedelta(seconds=5))
    db.refresh(a), db.refresh(b), db.refresh(c)
    assert c.revoked_at == t0 + timedelta(seconds=5)
    assert a.revoked_at == t0 and b.revoked_at == t0  # already revoked: untouched
