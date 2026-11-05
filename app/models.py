"""Import every feature's models here so Base.metadata is complete (tests, Alembic)."""
from app.auth.models import LoginAttempt, RefreshToken, User
from app.insights.models import AppSetting
from app.payment_methods.models import PaymentMethod
from app.reminders.models import PushSubscription, ReminderLog
from app.subscriptions.models import CATEGORIES, Subscription

__all__ = [
    "CATEGORIES",
    "AppSetting",
    "LoginAttempt",
    "PaymentMethod",
    "PushSubscription",
    "RefreshToken",
    "ReminderLog",
    "Subscription",
    "User",
]
