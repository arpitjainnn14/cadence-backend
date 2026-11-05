import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.models import RefreshToken, User


def _normalise(email: str) -> str:
    return email.strip().lower()


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        """Look up by email, case-insensitively (emails are stored lowercase)."""
        return self.db.scalar(select(User).where(User.email == _normalise(email)))

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def create(self, email: str, password_hash: str) -> User:
        """Add a user with a normalised email. Flushes; the caller's unit of work commits."""
        user = User(email=_normalise(email), password_hash=password_hash)
        self.db.add(user)
        self.db.flush()
        return user


class RefreshTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, token: RefreshToken) -> RefreshToken:
        self.db.add(token)
        self.db.flush()
        return token

    def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Fetch and row-lock, so two concurrent refreshes of one token are serialised."""
        return self.db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update())

    def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        """Revoke every still-active token of a rotation family."""
        self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def mark_rotated(self, token: RefreshToken, now: datetime) -> None:
        """Retire a token because it was exchanged for a new one."""
        token.revoked_at = now
        token.replaced_at = now
        self.db.flush()

    def revoke(self, token: RefreshToken, now: datetime) -> None:
        token.revoked_at = now
        self.db.flush()
