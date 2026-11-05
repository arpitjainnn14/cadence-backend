from app.core.db import DbSession
from app.subscriptions.repository import SubscriptionRepository


def get_subscription_repo(db: DbSession) -> SubscriptionRepository:
    return SubscriptionRepository(db)
