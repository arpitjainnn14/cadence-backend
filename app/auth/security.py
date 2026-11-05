import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

ALGORITHM = "HS256"
_hasher = PasswordHash.recommended()  # argon2id


class InvalidToken(Exception):
    """The access token is missing a claim, expired, forged, or of the wrong type/algorithm."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


def create_access_token(user_id: uuid.UUID, now: datetime | None = None) -> str:
    settings = get_settings()
    issued = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": issued,
        "exp": issued + timedelta(minutes=settings.access_token_minutes),
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id, or raise InvalidToken. The algorithm is pinned, never read from the token."""
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat", "jti", "type"]},
        )
        if claims["type"] != "access":
            raise InvalidToken("not an access token")
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidToken(str(exc)) from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """sha256 hex. Refresh tokens are high-entropy random strings, so a fast hash is enough."""
    return hashlib.sha256(token.encode()).hexdigest()
