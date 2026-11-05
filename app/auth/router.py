from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import JSONResponse

from app.auth import service
from app.auth.cookies import clear_auth_cookies, set_auth_cookies
from app.auth.deps import current_user, get_refresh_token_repo, get_user_repo
from app.auth.models import User
from app.auth.repository import RefreshTokenRepository, UserRepository
from app.auth.schemas import LoginRequest, UserOut
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

Users = Annotated[UserRepository, Depends(get_user_repo)]
Tokens = Annotated[RefreshTokenRepository, Depends(get_refresh_token_repo)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, users: Users, tokens: Tokens, settings: SettingsDep) -> User:
    user = service.authenticate(users, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access, refresh = service.issue_session(tokens, user)
    set_auth_cookies(response, settings, access, refresh)
    return user


@router.post("/refresh", response_model=UserOut)
def refresh(
    response: Response,
    users: Users,
    tokens: Tokens,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> User | JSONResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user, access, new_refresh = service.rotate_refresh(users, tokens, refresh_token, service.now())
    except service.RefreshInvalid:
        raise HTTPException(status_code=401, detail="Not authenticated") from None
    except service.RefreshReused:
        # Return, don't raise: get_db rolls back on exceptions, and the family revocation must be committed.
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
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
