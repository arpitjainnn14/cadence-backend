import uuid
from datetime import UTC, date, datetime
from typing import Literal

from app.payment_methods.repository import PaymentMethodRepository
from app.shared.billing import next_renewal, yearly_amount
from app.shared.enums import Currency, SubscriptionStatus
from app.subscriptions.merchants import logo_url, resolve_domain
from app.subscriptions.models import Subscription
from app.subscriptions.repository import SubscriptionRepository
from app.subscriptions.schemas import MerchantResolution, SubscriptionIn, SubscriptionOut

SortKey = Literal["cost", "renewal", "name"]
_STORED_FIELDS = tuple(
    f for f in SubscriptionOut.model_fields if f not in ("next_renewal", "logo_url", "yearly_amount", "amount_inr", "yearly_inr")
)


class SubscriptionNotFound(Exception):
    pass


class UnknownPaymentMethod(Exception):
    pass


def resolve_merchant(name: str) -> MerchantResolution:
    """Domain and logo URL for a merchant name; both None if unknown."""
    domain = resolve_domain(name)
    return MerchantResolution(domain=domain, logo_url=logo_url(domain) if domain else None)


def to_out(sub: Subscription, today: date) -> SubscriptionOut:
    """The subscription plus derived fields. The INR fields are null for USD subscriptions (nothing is converted)."""
    yearly = yearly_amount(sub.amount, sub.billing_cycle)
    is_inr = sub.currency == Currency.INR
    return SubscriptionOut(
        **{f: getattr(sub, f) for f in _STORED_FIELDS},
        next_renewal=next_renewal(sub.start_date, sub.billing_cycle, today),
        logo_url=logo_url(sub.merchant_domain) if sub.merchant_domain else None,
        yearly_amount=yearly,
        amount_inr=sub.amount if is_inr else None,
        yearly_inr=yearly if is_inr else None,
    )


def _domain(data: SubscriptionIn, current: Subscription | None) -> str | None:
    """The stored domain, or one resolved from the name.

    On a rename where the client echoed the old domain back, the domain is stale: re-resolve it from the new
    name (null if unknown). A domain that differs from the stored one was typed on purpose and is kept.
    """
    renamed = current is not None and data.merchant_name != current.merchant_name
    if renamed and data.merchant_domain == current.merchant_domain:
        return resolve_domain(data.merchant_name)
    return data.merchant_domain or resolve_domain(data.merchant_name)


def _fields(data: SubscriptionIn, payment_methods: PaymentMethodRepository, current: Subscription | None) -> dict:
    """Column values for `data`, after validating the payment method and deriving domain and cancelled_at."""
    if data.payment_method_id is not None and payment_methods.get(data.payment_method_id) is None:
        raise UnknownPaymentMethod
    fields = data.model_dump()
    fields["merchant_domain"] = _domain(data, current)
    if data.status != SubscriptionStatus.cancelled:
        fields["cancelled_at"] = None
    elif current is not None and current.cancelled_at is not None:
        fields["cancelled_at"] = current.cancelled_at
    else:
        fields["cancelled_at"] = datetime.now(UTC)
    return fields


def get_subscription(repo: SubscriptionRepository, sub_id: uuid.UUID) -> Subscription:
    """The subscription, or SubscriptionNotFound."""
    sub = repo.get(sub_id)
    if sub is None:
        raise SubscriptionNotFound
    return sub


def create_subscription(
    repo: SubscriptionRepository, payment_methods: PaymentMethodRepository, data: SubscriptionIn
) -> Subscription:
    """Create a subscription; fills the domain from the merchant name if omitted."""
    return repo.add(**_fields(data, payment_methods, None))


def replace_subscription(
    repo: SubscriptionRepository, payment_methods: PaymentMethodRepository, sub_id: uuid.UUID, data: SubscriptionIn
) -> Subscription:
    """Full replace; cancelled_at is set on entering cancelled and cleared on leaving it."""
    sub = get_subscription(repo, sub_id)
    repo.update(sub, _fields(data, payment_methods, sub))
    return sub


def delete_subscription(repo: SubscriptionRepository, sub_id: uuid.UUID) -> None:
    repo.delete(get_subscription(repo, sub_id))


def list_subscriptions(
    repo: SubscriptionRepository,
    today: date,
    status: SubscriptionStatus | None = None,
    payment_method_id: uuid.UUID | None = None,
    category: str | None = None,
    sort: SortKey = "name",
) -> list[SubscriptionOut]:
    """Filtered subscriptions with derived fields.

    Sorted by cost (INR subs by yearly_inr desc, then USD subs by yearly_amount desc; ties by name, id),
    renewal, or name.
    """
    items = [to_out(s, today) for s in repo.list(status, payment_method_id, category)]
    if sort == "cost":
        items.sort(key=lambda s: (s.currency != Currency.INR, -s.yearly_amount, s.merchant_name.lower(), str(s.id)))
    elif sort == "renewal":
        items.sort(key=lambda s: (s.next_renewal, s.merchant_name.lower(), str(s.id)))
    else:
        items.sort(key=lambda s: (s.merchant_name.lower(), str(s.id)))
    return items
