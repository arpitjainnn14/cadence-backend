import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.shared.enums import BillingCycle, Currency, SubscriptionStatus
from app.subscriptions.models import CATEGORIES

_HOSTNAME = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"


class SubscriptionIn(BaseModel):
    merchant_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    merchant_domain: Annotated[str, StringConstraints(max_length=253, pattern=_HOSTNAME)] | None = None
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    currency: Currency
    billing_cycle: BillingCycle
    next_billing_date: date
    started_on: date | None = None
    payment_method_id: uuid.UUID | None = None
    category: str = "Other"
    notes: Annotated[str, StringConstraints(max_length=500)] | None = None
    status: SubscriptionStatus = SubscriptionStatus.active

    @field_validator("merchant_domain", mode="before")
    @classmethod
    def _clean_domain(cls, value: object) -> object:
        """Blank means no domain; hostnames are case-insensitive, stored lowercase."""
        if isinstance(value, str):
            return value.strip().lower() or None
        return value

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(CATEGORIES)}")
        return value


class SubscriptionUpdate(SubscriptionIn):
    """PUT body: like SubscriptionIn, but omitting next_billing_date keeps the stored billing anchor."""

    next_billing_date: date | None = None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_name: str
    merchant_domain: str | None
    amount: Decimal
    currency: Currency
    billing_cycle: BillingCycle
    started_on: date | None
    payment_method_id: uuid.UUID | None
    category: str
    notes: str | None
    status: SubscriptionStatus
    cancelled_at: datetime | None
    created_at: datetime
    next_renewal: date
    logo_url: str | None
    yearly_amount: Decimal
    amount_inr: Decimal | None
    yearly_inr: Decimal | None


class MerchantResolution(BaseModel):
    domain: str | None
    logo_url: str | None
