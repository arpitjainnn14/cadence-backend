import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

from app.shared.enums import Currency

# Decimals go over the wire as strings with 2 places, e.g. "5455.25".
Money = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.2f}", return_type=str)]


class PaymentMethodRef(BaseModel):
    id: uuid.UUID
    name: str
    has_image: bool


class UpcomingRenewal(BaseModel):
    subscription_id: uuid.UUID
    merchant_name: str
    logo_url: str | None
    amount: Money
    currency: Currency
    amount_inr: Money | None
    renewal_date: date
    days_until: int
    payment_method: PaymentMethodRef | None


class Totals(BaseModel):
    monthly: Money
    half_yearly: Money
    yearly: Money


class SummaryOut(Totals):
    """INR totals at the top level; `usd` totals the active USD subscriptions separately (null if none)."""

    usd: Totals | None
    upcoming: list[UpcomingRenewal]


class CategoryTotal(BaseModel):
    category: str
    amount: Money
    subscription_ids: list[uuid.UUID]


class PaymentMethodTotal(BaseModel):
    payment_method_id: uuid.UUID | None
    name: str
    amount: Money
    subscription_ids: list[uuid.UUID]


class ExpensiveSubscription(BaseModel):
    subscription_id: uuid.UUID
    merchant_name: str
    yearly_inr: Money


class UsdSubscription(BaseModel):
    subscription_id: uuid.UUID
    merchant_name: str
    yearly_amount: Money


class InsightsOut(BaseModel):
    by_category: list[CategoryTotal]
    by_payment_method: list[PaymentMethodTotal]
    most_expensive: list[ExpensiveSubscription]
    usd_subscriptions: list[UsdSubscription]
