from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.auth import ratelimit, service
from app.auth.cookies import clear_auth_cookies, set_auth_cookies
from app.auth.deps import current_user, get_login_attempt_repo, get_refresh_token_repo, get_user_repo
from app.auth.models import User
from app.auth.repository import LoginAttemptRepository, RefreshTokenRepository, UserRepository
from app.auth.schemas import LoginRequest, UserOut
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

Users = Annotated[UserRepository, Depends(get_user_repo)]
Attempts = Annotated[LoginAttemptRepository, Depends(get_login_attempt_repo)]
Tokens = Annotated[RefreshTokenRepository, Depends(get_refresh_token_repo)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    users: Users,
    tokens: Tokens,
    attempts: Attempts,
    settings: SettingsDep,
) -> User | JSONResponse:
    # Failures return a response instead of raising: get_db rolls back on exceptions, and the
    # recorded attempt must be committed or the lockout would never accumulate.
    ip = ratelimit.client_ip(request)
    if ratelimit.is_locked(attempts, body.email, ip, service.now()):
        return JSONResponse(status_code=429, content={"detail": "Too many attempts. Try again later."})
    user = service.authenticate(users, body.email, body.password)
    ratelimit.record_attempt(attempts, body.email, ip, success=user is not None)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "Invalid email or password"})
    access, refresh = service.issue_session(tokens, user)
    set_auth_cookies(response, settings, access, refresh)
    return user


def _refresh_rejected(settings: Settings) -> JSONResponse:
    """401 that also clears the auth cookies, so the browser stops replaying a dead session.

    Returned, not raised: get_db rolls back on exceptions (and a reuse must keep its family revocation).
    """
    response = JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    clear_auth_cookies(response, settings)
    return response


@router.post("/refresh", response_model=UserOut)
def refresh(
    response: Response,
    users: Users,
    tokens: Tokens,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> User | JSONResponse:
    if not refresh_token:
        return _refresh_rejected(settings)
    try:
        user, access, new_refresh = service.rotate_refresh(users, tokens, refresh_token, service.now())
    except (service.RefreshInvalid, service.RefreshReused):
        return _refresh_rejected(settings)
    set_auth_cookies(response, settings, access, new_refresh)
    return user


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    tokens: Tokens,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> None:
    if refresh_token:
        service.revoke_refresh(tokens, refresh_token)
    clear_auth_cookies(response, settings)


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user
