import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from app.core.config import get_settings
from app.insights.repository import SettingsRepository
from app.insights.schemas import (
    CategoryTotal,
    ExpensiveSubscription,
    InsightsOut,
    PaymentMethodRef,
    PaymentMethodTotal,
    SummaryOut,
    UpcomingRenewal,
    format_rate,
)
from app.payment_methods.models import PaymentMethod
from app.payment_methods.repository import PaymentMethodRepository
from app.shared.billing import monthly_inr_unrounded, round_money
from app.shared.enums import Currency, SubscriptionStatus
from app.subscriptions.models import Subscription
from app.subscriptions.repository import SubscriptionRepository
from app.subscriptions.service import to_out

USD_RATE_KEY = "usd_inr_rate"
UPCOMING_LIMIT = 20
MOST_EXPENSIVE_LIMIT = 10
UNASSIGNED = "Unassigned"
_MAX_RATE = Decimal("10000")


def _valid_rate(value: Decimal) -> bool:
    return value.is_finite() and 0 < value <= _MAX_RATE


def get_usd_rate(settings_repo: SettingsRepository) -> Decimal:
    """The USD to INR rate from app_settings; the configured default if unset or malformed."""
    default = get_settings().default_usd_rate
    value = settings_repo.get(USD_RATE_KEY)
    if value is None:
        return default
    try:
        rate = Decimal(value)
    except ArithmeticError:
        return default
    return rate if _valid_rate(rate) else default


def set_usd_rate(settings_repo: SettingsRepository, rate: Decimal) -> Decimal:
    """Store the (already validated) rate in normalised form and return it."""
    settings_repo.set(USD_RATE_KEY, format_rate(rate))
    return get_usd_rate(settings_repo)


def _active(subs_repo: SubscriptionRepository) -> list[Subscription]:
    return subs_repo.list(status=SubscriptionStatus.active)


def _monthly(sub: Subscription, rate: Decimal) -> Decimal:
    return monthly_inr_unrounded(sub.amount, sub.currency, sub.billing_cycle, rate)


def _has_usd(subs: list[Subscription]) -> bool:
    return any(s.currency == Currency.USD for s in subs)


def _ref(method: PaymentMethod | None) -> PaymentMethodRef | None:
    return PaymentMethodRef(id=method.id, name=method.display_name, has_image=method.has_image) if method else None


def summary(
    subs_repo: SubscriptionRepository,
    pm_repo: PaymentMethodRepository,
    settings_repo: SettingsRepository,
    today: date,
) -> SummaryOut:
    """Active totals (INR), the next 20 renewals, and whether USD makes the totals approximate."""
    rate = get_usd_rate(settings_repo)
    subs = _active(subs_repo)
    methods = {m.id: m for m in pm_repo.list(include_inactive=True)}
    monthly = sum((_monthly(s, rate) for s in subs), Decimal(0))

    upcoming = sorted(
        (to_out(s, rate, today) for s in subs),
        key=lambda o: (o.next_renewal, o.merchant_name.lower(), str(o.id)),
    )[:UPCOMING_LIMIT]
    return SummaryOut(
        monthly=round_money(monthly),
        half_yearly=round_money(monthly * 6),
        yearly=round_money(monthly * 12),
        approx=_has_usd(subs),
        upcoming=[
            UpcomingRenewal(
                subscription_id=o.id,
                merchant_name=o.merchant_name,
                logo_url=o.logo_url,
                amount=o.amount,
                currency=o.currency,
                amount_inr=o.amount_inr,
                renewal_date=o.next_renewal,
                days_until=(o.next_renewal - today).days,
                payment_method=_ref(methods.get(o.payment_method_id)),
            )
            for o in upcoming
        ],
    )


def _groups(
    subs: list[Subscription], rate: Decimal, factor: int, key
) -> list[tuple[object, Decimal, list[uuid.UUID]]]:
    """(key, rounded amount, subscription ids) per group; each group's sum is rounded once."""
    totals: dict[object, Decimal] = {}
    ids: dict[object, list[uuid.UUID]] = {}
    for s in sorted(subs, key=lambda s: (s.merchant_name.lower(), str(s.id))):
        k = key(s)
        totals[k] = totals.get(k, Decimal(0)) + _monthly(s, rate)
        ids.setdefault(k, []).append(s.id)
    return [(k, round_money(total * factor), ids[k]) for k, total in totals.items()]


def insights(
    subs_repo: SubscriptionRepository,
    pm_repo: PaymentMethodRepository,
    settings_repo: SettingsRepository,
    period: Literal["monthly", "yearly"],
    today: date,
) -> InsightsOut:
    """Active spend grouped by category and payment method, plus the 10 priciest by yearly INR."""
    rate = get_usd_rate(settings_repo)
    subs = _active(subs_repo)
    names = {m.id: m.display_name for m in pm_repo.list(include_inactive=True)}
    factor = 12 if period == "yearly" else 1

    by_category = sorted(
        (
            CategoryTotal(category=k, amount=a, subscription_ids=i)
            for k, a, i in _groups(subs, rate, factor, lambda s: s.category)
        ),
        key=lambda g: (-g.amount, g.category),
    )
    by_method = sorted(
        (
            PaymentMethodTotal(
                payment_method_id=k, name=names.get(k, UNASSIGNED) if k else UNASSIGNED, amount=a, subscription_ids=i
            )
            for k, a, i in _groups(subs, rate, factor, lambda s: s.payment_method_id)
        ),
        key=lambda g: (-g.amount, g.name),
    )
    priciest = sorted(subs, key=lambda s: (-_monthly(s, rate), s.merchant_name.lower(), str(s.id)))
    return InsightsOut(
        approx=_has_usd(subs),
        by_category=by_category,
        by_payment_method=by_method,
        most_expensive=[
            ExpensiveSubscription(
                subscription_id=s.id, merchant_name=s.merchant_name, yearly_inr=round_money(_monthly(s, rate) * 12)
            )
            for s in priciest[:MOST_EXPENSIVE_LIMIT]
        ],
    )
