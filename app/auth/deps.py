from typing import Annotated

from fastapi import Depends, HTTPException, Request
from app.auth.models import User
from app.auth.repository import LoginAttemptRepository, RefreshTokenRepository, UserRepository
from app.auth.security import InvalidToken, decode_access_token
from app.core.db import DbSession


def get_user_repo(db: DbSession) -> UserRepository:
    return UserRepository(db)


def get_refresh_token_repo(db: DbSession) -> RefreshTokenRepository:
    return RefreshTokenRepository(db)


def get_login_attempt_repo(db: DbSession) -> LoginAttemptRepository:
    return LoginAttemptRepository(db)


def current_user(request: Request, users: Annotated[UserRepository, Depends(get_user_repo)]) -> User:
    """The user behind the access_token cookie, or 401."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user = users.get_by_id(decode_access_token(token))
    except InvalidToken:
        raise HTTPException(status_code=401, detail="Not authenticated") from None
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
