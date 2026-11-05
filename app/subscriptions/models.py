import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.shared.db_types import pg_enum
from app.shared.enums import BillingCycle, Currency, SubscriptionStatus

CATEGORIES = [
    "Streaming",
    "Music",
    "Software/AI",
    "Cloud storage",
    "Fitness",
    "Food delivery",
    "Shopping",
    "News",
    "Other",
]


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_subscriptions_amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    merchant_name: Mapped[str] = mapped_column(String)
    merchant_domain: Mapped[str | None] = mapped_column(String)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[Currency] = mapped_column(pg_enum(Currency, "currency"))
    billing_cycle: Mapped[BillingCycle] = mapped_column(pg_enum(BillingCycle, "billing_cycle"))
    start_date: Mapped[date] = mapped_column(Date)
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String, default="Other", server_default="Other")
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SubscriptionStatus] = mapped_column(
        pg_enum(SubscriptionStatus, "subscription_status"),
        default=SubscriptionStatus.active,
        server_default=SubscriptionStatus.active.value,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
