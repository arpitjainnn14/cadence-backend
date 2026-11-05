import json
from typing import Annotated

from fastapi import Depends
from pywebpush import webpush

from app.core.config import Settings, get_settings
from app.core.db import DbSession
from app.reminders.models import PushSubscription
from app.reminders.repository import PushSubscriptionRepository, ReminderLogRepository
from app.reminders.service import Sender


def get_push_repo(db: DbSession) -> PushSubscriptionRepository:
    return PushSubscriptionRepository(db)


def get_reminder_log_repo(db: DbSession) -> ReminderLogRepository:
    return ReminderLogRepository(db)


def get_push_sender(settings: Annotated[Settings, Depends(get_settings)]) -> Sender:
    """The real sender (tests override this dependency)."""

    def send(push_sub: PushSubscription, payload: dict) -> None:
        webpush(
            subscription_info={"endpoint": push_sub.endpoint, "keys": {"p256dh": push_sub.p256dh, "auth": push_sub.auth}},
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},  # fresh dict: pywebpush mutates it
            timeout=10,
        )

    return send
