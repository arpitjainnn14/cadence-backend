import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.enums import SubscriptionStatus
from app.subscriptions.models import Subscription


class SubscriptionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, **fields: object) -> Subscription:
        """Add a subscription. Flushes; the caller's unit of work commits."""
        sub = Subscription(**fields)
        self.db.add(sub)
        self.db.flush()
        self.db.refresh(sub)  # load server defaults (created_at, updated_at)
        return sub

    def get(self, sub_id: uuid.UUID) -> Subscription | None:
        """The subscription with this id, or None."""
        return self.db.get(Subscription, sub_id)

    def list(
        self,
        status: SubscriptionStatus | None = None,
        payment_method_id: uuid.UUID | None = None,
        category: str | None = None,
    ) -> list[Subscription]:
        """Subscriptions matching all given filters, in no particular order."""
        stmt = select(Subscription)
        if status is not None:
            stmt = stmt.where(Subscription.status == status)
        if payment_method_id is not None:
            stmt = stmt.where(Subscription.payment_method_id == payment_method_id)
        if category is not None:
            stmt = stmt.where(Subscription.category == category)
        return list(self.db.scalars(stmt))

    def update(self, sub: Subscription, changes: dict[str, object]) -> None:
        """Set the given attributes."""
        for field, value in changes.items():
            setattr(sub, field, value)
        self.db.flush()
        self.db.refresh(sub)  # pick up the new updated_at

    def delete(self, sub: Subscription) -> None:
        self.db.delete(sub)
        self.db.flush()
