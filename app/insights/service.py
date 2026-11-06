import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from app.insights.repository import SettingsRepository
from app.insights.schemas import (
    Budget,
    CategoryTotal,
    ExpensiveSubscription,
    InsightsOut,
    PaymentMethodRef,
    PaymentMethodTotal,
    SummaryOut,
    Totals,
    UpcomingRenewal,
    UsdSubscription,
)
from app.payment_methods.models import PaymentMethod
from app.payment_methods.repository import PaymentMethodRepository
from app.shared.billing import monthly_unrounded, round_money, yearly_amount
from app.shared.enums import Currency, SubscriptionStatus
from app.subscriptions.models import Subscription
from app.subscriptions.repository import SubscriptionRepository
from app.subscriptions.service import to_out

UPCOMING_LIMIT = 20
MOST_EXPENSIVE_LIMIT = 10
UNASSIGNED = "Unassigned"
BUDGET_KEY = "monthly_budget_inr"
MAX_BUDGET = Decimal(10_000_000)
_CENT = Decimal("0.01")


def get_budget(settings: SettingsRepository) -> Decimal | None:
    """The stored monthly budget, or None if unset or the stored value is malformed or out of range."""
    raw = settings.get(BUDGET_KEY)
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() and 0 < value <= MAX_BUDGET else None


def set_budget(settings: SettingsRepository, value: Decimal | None) -> Decimal | None:
    """Store the budget normalised to 2 places (None clears it). Returns what is now stored."""
    if value is None:
        settings.delete(BUDGET_KEY)
        return None
    value = value.quantize(_CENT, ROUND_HALF_UP)
    settings.set(BUDGET_KEY, str(value))
    return value


def _budget(monthly: Decimal | None, used: Decimal) -> Budget | None:
    if monthly is None:
        return None
    percent = int((used * 100 / monthly).quantize(Decimal(1), ROUND_HALF_UP))
    return Budget(monthly=monthly, used=used, remaining=monthly - used, percent_used=percent, over=used > monthly)


def _active(subs_repo: SubscriptionRepository) -> list[Subscription]:
    return subs_repo.list(status=SubscriptionStatus.active)


def _monthly(sub: Subscription) -> Decimal:
    return monthly_unrounded(sub.amount, sub.billing_cycle)


def _totals(subs: list[Subscription]) -> Totals:
    """Monthly, half-yearly and yearly totals of `subs` (one currency), each rounded once from the unrounded sum."""
    monthly = sum((_monthly(s) for s in subs), Decimal(0))
    return Totals(monthly=round_money(monthly), half_yearly=round_money(monthly * 6), yearly=round_money(monthly * 12))


def _ref(method: PaymentMethod | None) -> PaymentMethodRef | None:
    return PaymentMethodRef(id=method.id, name=method.display_name, has_image=method.has_image) if method else None


def summary(
    subs_repo: SubscriptionRepository,
    pm_repo: PaymentMethodRepository,
    settings: SettingsRepository,
    today: date,
) -> SummaryOut:
    """Active totals (INR subs at the top level, USD subs under `usd`), the budget, and the next 20 renewals."""
    subs = _active(subs_repo)
    methods = {m.id: m for m in pm_repo.list(include_inactive=True)}
    inr_subs = [s for s in subs if s.currency == Currency.INR]
    usd_subs = [s for s in subs if s.currency == Currency.USD]

    upcoming = sorted(
        (to_out(s, today) for s in subs),
        key=lambda o: (o.next_renewal, o.merchant_name.lower(), str(o.id)),
    )[:UPCOMING_LIMIT]
    inr_totals = _totals(inr_subs)
    return SummaryOut(
        **inr_totals.model_dump(),
        usd=_totals(usd_subs) if usd_subs else None,
        budget=_budget(get_budget(settings), inr_totals.monthly),
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
    subs: list[Subscription], factor: int, key
) -> list[tuple[object, Decimal, list[uuid.UUID]]]:
    """(key, rounded amount, subscription ids) per group; each group's sum is rounded once."""
    totals: dict[object, Decimal] = {}
    ids: dict[object, list[uuid.UUID]] = {}
    for s in sorted(subs, key=lambda s: (s.merchant_name.lower(), str(s.id))):
        k = key(s)
        totals[k] = totals.get(k, Decimal(0)) + _monthly(s)
        ids.setdefault(k, []).append(s.id)
    return [(k, round_money(total * factor), ids[k]) for k, total in totals.items()]


def insights(
    subs_repo: SubscriptionRepository,
    pm_repo: PaymentMethodRepository,
    period: Literal["monthly", "yearly"],
    today: date,
) -> InsightsOut:
    """Active INR spend by category and payment method, the 10 priciest by yearly INR, and the USD subs apart."""
    all_active = _active(subs_repo)
    subs = [s for s in all_active if s.currency == Currency.INR]
    usd_subs = sorted(
        (s for s in all_active if s.currency == Currency.USD),
        key=lambda s: (-yearly_amount(s.amount, s.billing_cycle), s.merchant_name.lower(), str(s.id)),
    )
    names = {m.id: m.display_name for m in pm_repo.list(include_inactive=True)}
    factor = 12 if period == "yearly" else 1

    by_category = sorted(
        (
            CategoryTotal(category=k, amount=a, subscription_ids=i)
            for k, a, i in _groups(subs, factor, lambda s: s.category)
        ),
        key=lambda g: (-g.amount, g.category),
    )
    by_method = sorted(
        (
            PaymentMethodTotal(
                payment_method_id=k, name=names.get(k, UNASSIGNED) if k else UNASSIGNED, amount=a, subscription_ids=i
            )
            for k, a, i in _groups(subs, factor, lambda s: s.payment_method_id)
        ),
        key=lambda g: (-g.amount, g.name),
    )
    priciest = sorted(subs, key=lambda s: (-_monthly(s), s.merchant_name.lower(), str(s.id)))
    return InsightsOut(
        by_category=by_category,
        by_payment_method=by_method,
        most_expensive=[
            ExpensiveSubscription(
                subscription_id=s.id, merchant_name=s.merchant_name, yearly_inr=round_money(_monthly(s) * 12)
            )
            for s in priciest[:MOST_EXPENSIVE_LIMIT]
        ],
        usd_subscriptions=[
            UsdSubscription(
                subscription_id=s.id, merchant_name=s.merchant_name, yearly_amount=yearly_amount(s.amount, s.billing_cycle)
            )
            for s in usd_subs
        ],
    )
