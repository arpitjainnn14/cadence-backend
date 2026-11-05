import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer

from app.shared.enums import Currency

# Decimals go over the wire as strings with 2 places, e.g. "5455.25".
Money = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.2f}", return_type=str)]
_PLACES = Decimal("0.0001")


def format_rate(rate: Decimal) -> str:
    """Normalised text: trailing zeros dropped but at least 2 decimal places ("88.00", "83.4567")."""
    text = f"{rate.quantize(_PLACES):f}".rstrip("0")
    whole, _, frac = text.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


Rate = Annotated[Decimal, PlainSerializer(format_rate, return_type=str)]


class SettingsIn(BaseModel):
    usd_inr_rate: Annotated[Decimal, Field(gt=0, le=10000, decimal_places=4, allow_inf_nan=False)]


class SettingsOut(BaseModel):
    usd_inr_rate: Rate


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
    amount_inr: Money
    renewal_date: date
    days_until: int
    payment_method: PaymentMethodRef | None


class SummaryOut(BaseModel):
    monthly: Money
    half_yearly: Money
    yearly: Money
    approx: bool
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


class InsightsOut(BaseModel):
    approx: bool
    by_category: list[CategoryTotal]
    by_payment_method: list[PaymentMethodTotal]
    most_expensive: list[ExpensiveSubscription]
