import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import ratelimit, service
from app.auth.models import LoginAttempt, RefreshToken
from app.auth.repository import LoginAttemptRepository
from tests.conftest import csrf_headers
from tests.test_auth import EMAIL, PASSWORD, clock, login, real_uow_client, user  # noqa: F401

LOCKED = {"detail": "Too many attempts. Try again later."}


def login_from(client, ip, email=EMAIL, password="wrong"):
    return client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers={"X-Forwarded-For": ip}
    )


# --- CSRF ---


def test_mutation_without_csrf_header_403(client, user):
    login(client)
    r = client.post("/api/auth/logout")
    assert r.status_code == 403
    assert r.json() == {"detail": "CSRF check failed"}
    assert client.post("/api/auth/logout", headers=csrf_headers(client)).status_code == 204


def test_csrf_header_mismatch_403(client, user):
    login(client)
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403


def test_csrf_missing_cookie_403(client, user):
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": ""}).status_code == 403


def test_csrf_non_ascii_header_is_403_not_500(client, user):
    login(client)
    r = client.post("/api/auth/logout", headers={"X-CSRF-Token": "é".encode("latin-1")})
    assert r.status_code == 403


def test_csrf_applies_to_all_unsafe_methods(client, user):
    login(client)
    for method in ("PUT", "PATCH", "DELETE"):
        assert client.request(method, "/api/anything").status_code == 403


def test_csrf_exempt_paths(client, user):
    assert client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    # /api/internal/* is exempt (not 403); the route does not exist yet so 404.
    assert client.post("/api/internal/anything").status_code == 404


def test_get_requests_need_no_csrf(client, user):
    login(client)
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_non_api_paths_not_checked(client):
    assert client.post("/other").status_code == 404


# --- rate limiting ---


def test_client_ip_prefers_first_forwarded_entry(client, user):
    class Req:
        headers = {"x-forwarded-for": " 1.2.3.4 , 5.6.7.8"}
        client = type("C", (), {"host": "9.9.9.9"})()

    assert ratelimit.client_ip(Req()) == "1.2.3.4"
    Req.headers = {}
    assert ratelimit.client_ip(Req()) == "9.9.9.9"


def test_login_lockout_after_5_failures(client, user):
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    r = login(client)  # correct password, still locked
    assert r.status_code == 429
    assert r.json() == LOCKED
    assert "access_token" not in client.cookies


def test_lockout_per_ip_across_emails(client, user):
    for i in range(5):
        assert login_from(client, "7.7.7.7", email=f"user{i}@example.com").status_code == 401
    assert login_from(client, "7.7.7.7", email="another@example.com").status_code == 429
    assert login_from(client, "8.8.8.8", email="another@example.com").status_code == 401  # other IP unaffected


def test_lockout_per_email_across_ips(client, user):
    for i in range(5):
        assert login_from(client, f"10.0.0.{i}").status_code == 401
    assert login_from(client, "10.0.0.99", password=PASSWORD).status_code == 429


def test_lockout_email_case_insensitive(client, user):
    for i in range(5):
        login_from(client, f"10.0.1.{i}", email=EMAIL.upper())
    assert login_from(client, "10.0.1.99", password=PASSWORD).status_code == 429


def test_lockout_expires(client, user, clock):
    for _ in range(5):
        login(client, password="wrong")
    assert login(client).status_code == 429
    clock["now"] += timedelta(minutes=16)
    assert login(client).status_code == 200


def test_successful_login_does_not_count(client, user):
    for _ in range(6):
        assert login(client).status_code == 200


def test_login_input_length_limits(client, user):
    assert login(client, email="a" * 257 + "@x.com").status_code == 422
    assert login(client, password="p" * 1025).status_code == 422


# --- persistence / unit of work with the real get_db ---


def test_failed_attempts_persist_despite_401_and_429(real_uow_client, engine):
    for _ in range(5):
        assert login(real_uow_client, password="wrong").status_code == 401
    assert login(real_uow_client).status_code == 429
    with Session(engine) as s:
        rows = s.scalars(select(LoginAttempt)).all()
        assert len(rows) == 5 and not any(a.success for a in rows)


def test_login_committed_before_response_is_sent(real_uow_client, engine):
    """Drive the ASGI app directly and look at the DB at the moment the response starts.

    TestClient only returns after the whole app call finished, so it cannot tell "committed before
    the response" from "committed after it"; the send() hook can.
    """
    seen: list[tuple[int, int]] = []

    async def send(message):
        if message["type"] == "http.response.start":
            with Session(engine) as s:  # fresh session, opened while the response is starting
                seen.append((len(s.scalars(select(RefreshToken)).all()), len(s.scalars(select(LoginAttempt)).all())))

    body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/api/auth/login", "raw_path": b"/api/auth/login", "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    asyncio.run(real_uow_client.app(scope, receive, send))
    assert seen == [(1, 1)]


def test_refresh_failure_clears_cookies(client, user, clock):
    login(client)
    client.cookies.set("refresh_token", "garbage", path="/api/auth")
    r = client.post("/api/auth/refresh", headers=csrf_headers(client))
    assert r.status_code == 401
    cleared = " ".join(r.headers.get_list("set-cookie"))
    for name in ("access_token", "refresh_token", "csrf_token"):
        assert f"{name}=" in cleared
    assert "Max-Age=0" in cleared


# --- repository ---


def test_login_attempt_repository(db):
    repo = LoginAttemptRepository(db)
    t0 = datetime(2030, 1, 1, tzinfo=UTC)
    repo.add("A@x.com", "1.1.1.1", False, at=t0)
    repo.add("a@x.com", "2.2.2.2", False, at=t0 + timedelta(minutes=10))
    repo.add("a@x.com", "2.2.2.2", True, at=t0 + timedelta(minutes=10))  # success: never counted
    repo.add("b@x.com", "1.1.1.1", False, at=t0 - timedelta(hours=1))
    since = t0 - timedelta(minutes=5)
    assert repo.count_failures_by_email("A@X.com", since) == 2
    assert repo.count_failures_by_ip("1.1.1.1", since) == 1
    assert repo.count_failures_by_ip("2.2.2.2", t0 + timedelta(minutes=11)) == 0


def test_is_locked_policy(db):
    repo = LoginAttemptRepository(db)
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    for _ in range(4):
        ratelimit.record_attempt(repo, "a@x.com", "1.1.1.1", False)
    assert not ratelimit.is_locked(repo, "a@x.com", "1.1.1.1", now=datetime.now(UTC))
    ratelimit.record_attempt(repo, "a@x.com", "1.1.1.1", False)
    assert ratelimit.is_locked(repo, "A@x.com", "9.9.9.9", now=datetime.now(UTC))
    assert not ratelimit.is_locked(repo, "a@x.com", "1.1.1.1", now=now + timedelta(days=3650))
