from datetime import datetime, timedelta

from fastapi import Request

from app.auth.repository import LoginAttemptRepository

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)


def client_ip(request: Request) -> str:
    """First X-Forwarded-For entry, else the socket peer.

    In production the request comes through Vercel -> Cloud Run, so the real client is the first
    X-Forwarded-For entry, but a client can send its own header and spoof it. The per-IP limit is
    therefore best-effort; the per-email limit (keyed on the submitted email) is the non-spoofable one.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_locked(attempts: LoginAttemptRepository, email: str, ip: str, now: datetime) -> bool:
    """True once the email OR the IP has MAX_FAILURES failed logins within the window."""
    since = now - WINDOW
    return (
        attempts.count_failures_by_email(email, since) >= MAX_FAILURES
        or attempts.count_failures_by_ip(ip, since) >= MAX_FAILURES
    )


def record_attempt(attempts: LoginAttemptRepository, email: str, ip: str, success: bool) -> None:
    attempts.add(email, ip, success)
