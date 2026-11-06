from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.auth import ratelimit, service
from app.auth.cookies import clear_auth_cookies, set_auth_cookies
from app.auth.deps import current_user, get_login_attempt_repo, get_refresh_token_repo, get_user_repo
from app.auth.models import User
from app.auth.repository import LoginAttemptRepository, RefreshTokenRepository, UserRepository
from app.auth.schemas import ChangePasswordRequest, LoginRequest, UserOut
from app.auth.security import verify_password
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
    attempts.lock_for(body.email)  # serialise concurrent logins per email until this transaction ends
    now = service.now()
    if ratelimit.is_locked(attempts, body.email, ip, now):
        return JSONResponse(status_code=429, content={"detail": "Too many attempts. Try again later."})
    user = service.authenticate(users, body.email, body.password)
    ratelimit.record_attempt(attempts, body.email, ip, success=user is not None, at=now)
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
    except service.RefreshRaced:
        # No Set-Cookie either way: the winning request already set fresh cookies, and clearing them
        # here would log the winner out.
        return JSONResponse(status_code=409, content={"detail": "Refresh already in progress"})
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


@router.post("/change-password", response_model=UserOut)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    users: Users,
    tokens: Tokens,
    attempts: Attempts,
    settings: SettingsDep,
) -> User | JSONResponse:
    # Same rate limit and response-not-raise pattern as login: a wrong current password must persist its attempt.
    ip = ratelimit.client_ip(request)
    attempts.lock_for(user.email)
    now = service.now()
    if ratelimit.is_locked(attempts, user.email, ip, now):
        return JSONResponse(status_code=429, content={"detail": "Too many attempts. Try again later."})
    correct = verify_password(body.current_password, user.password_hash)
    ratelimit.record_attempt(attempts, user.email, ip, success=correct, at=now)
    if not correct:
        return JSONResponse(status_code=400, content={"detail": "Current password is incorrect"})
    if body.new_password == body.current_password:
        return JSONResponse(status_code=422, content={"detail": "New password must be different"})
    access, refresh = service.change_password(users, tokens, user, body.new_password, now)
    set_auth_cookies(response, settings, access, refresh)
    return user
