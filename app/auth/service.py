import uuid
from datetime import UTC, datetime, timedelta
from functools import cache

from app.auth.models import RefreshToken, User
from app.auth.repository import RefreshTokenRepository, UserRepository
from app.auth.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.core.config import get_settings

REFRESH_GRACE = timedelta(seconds=10)  # a just-rotated token may be replayed by a racing request


class RefreshInvalid(Exception):
    """Unknown or expired refresh token. Nothing to clean up."""


class RefreshRaced(Exception):
    """A just-rotated token replayed within the grace window: a concurrent refresh already won."""


class RefreshReused(Exception):
    """A rotated or revoked token came back after the grace window; its family has been revoked."""


def now() -> datetime:
    """The service clock. Tests monkeypatch this."""
    return datetime.now(UTC)


@cache
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-timing")


def authenticate(users: UserRepository, email: str, password: str) -> User | None:
    """Return the user if the credentials match. Hashes even for unknown emails to equalise timing."""
    user = users.get_by_email(email)
    if user is None:
        verify_password(password, _dummy_hash())
        return None
    return user if verify_password(password, user.password_hash) else None


def issue_session(tokens: RefreshTokenRepository, user: User, family_id: uuid.UUID | None = None) -> tuple[str, str]:
    """Create an access JWT and a stored refresh token. Returns (access, refresh); a new family unless given."""
    issued = now()
    raw = new_refresh_token()
    tokens.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_token(raw),
            expires_at=issued + timedelta(days=get_settings().refresh_token_days),
        )
    )
    return create_access_token(user.id, now=issued), raw


def rotate_refresh(
    users: UserRepository, tokens: RefreshTokenRepository, raw: str, at: datetime
) -> tuple[User, str, str]:
    """Exchange a refresh token for a new session in the same family.

    Raises RefreshInvalid (reject, change nothing), RefreshRaced (lost a benign race, change nothing) or RefreshReused (family revoked; the caller must
    make sure that revocation is committed).
    """
    token = tokens.get_by_hash(hash_token(raw))
    if token is None:
        raise RefreshInvalid
    if token.revoked_at is not None:
        if token.replaced_at is not None and at - token.replaced_at <= REFRESH_GRACE:
            raise RefreshRaced
        tokens.revoke_family(token.family_id, at)
        raise RefreshReused
    user = users.get_by_id(token.user_id)
    if token.expires_at <= at or user is None:
        raise RefreshInvalid
    tokens.mark_rotated(token, at)
    access, refresh = issue_session(tokens, user, family_id=token.family_id)
    return user, access, refresh


def revoke_refresh(tokens: RefreshTokenRepository, raw: str) -> None:
    """Server-side logout: revoke the presented refresh token. Unknown or already-revoked is a no-op."""
    token = tokens.get_by_hash(hash_token(raw))
    if token is not None and token.revoked_at is None:
        tokens.revoke(token, now())
