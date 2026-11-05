import datetime as dt
import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.reminders.models import PushSubscription, ReminderLog


class PushSubscriptionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[PushSubscription]:
        """All push subscriptions, oldest first."""
        return list(self.db.scalars(select(PushSubscription).order_by(PushSubscription.created_at, PushSubscription.id)))

    def upsert(self, endpoint: str, p256dh: str, auth: str) -> PushSubscription:
        """Create the subscription for this endpoint, or refresh its keys. Flushes; does not commit."""
        row = self.db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        if row is None:
            row = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
            self.db.add(row)
        else:
            row.p256dh, row.auth = p256dh, auth
        self.db.flush()
        return row

    def delete(self, row: PushSubscription) -> None:
        self.db.delete(row)
        self.db.flush()

    def delete_by_endpoint(self, endpoint: str) -> None:
        """Delete the subscription with this endpoint; a no-op when absent."""
        row = self.db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        if row is not None:
            self.delete(row)


class ReminderLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def claim(self, subscription_id: uuid.UUID, renewal_date: dt.date) -> bool:
        """Record that this renewal is being reminded. False if it was already claimed.

        A single INSERT ... ON CONFLICT DO NOTHING, so concurrent runs cannot both win.
        """
        stmt = (
            insert(ReminderLog)
            .values(id=uuid.uuid4(), subscription_id=subscription_id, renewal_date=renewal_date)
            .on_conflict_do_nothing(index_elements=["subscription_id", "renewal_date"])
            .returning(ReminderLog.id)
        )
        return self.db.execute(stmt).scalar_one_or_none() is not None

    def release(self, subscription_id: uuid.UUID, renewal_date: dt.date) -> None:
        """Delete this renewal's claim so a later run can retry it; a no-op when there is none."""
        self.db.execute(
            delete(ReminderLog).where(
                ReminderLog.subscription_id == subscription_id, ReminderLog.renewal_date == renewal_date
            )
        )
