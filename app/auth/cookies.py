import secrets

from fastapi import Response

from app.core.config import Settings

# (name, path, httpOnly). The csrf cookie must be readable by JS so the SPA can echo it in a header.
_COOKIES = (("access_token", "/api", True), ("refresh_token", "/api/auth", True), ("csrf_token", "/", False))


def set_auth_cookies(response: Response, settings: Settings, access: str, refresh: str) -> None:
    values = {"access_token": access, "refresh_token": refresh, "csrf_token": secrets.token_urlsafe(32)}
    max_ages = {
        "access_token": settings.access_token_minutes * 60,
        "refresh_token": settings.refresh_token_days * 86400,
        "csrf_token": settings.refresh_token_days * 86400,
    }
    for name, path, http_only in _COOKIES:
        response.set_cookie(
            name, values[name], max_age=max_ages[name], path=path,
            httponly=http_only, secure=settings.cookie_secure, samesite="lax",
        )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name, path, http_only in _COOKIES:
        response.delete_cookie(
            name, path=path, httponly=http_only, secure=settings.cookie_secure, samesite="lax"
        )
