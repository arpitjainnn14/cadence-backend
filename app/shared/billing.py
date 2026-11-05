"""Pure billing math: renewal dates, monthly and yearly cost. No currency conversion."""

import calendar
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.shared.enums import BillingCycle

IST = ZoneInfo("Asia/Kolkata")
_CENT = Decimal("0.01")

CYCLE_MONTHS: dict[BillingCycle, int] = {
    BillingCycle.monthly: 1,
    BillingCycle.quarterly: 3,
    BillingCycle.half_yearly: 6,
    BillingCycle.yearly: 12,
}


def _round(value: Decimal) -> Decimal:
    return value.quantize(_CENT, ROUND_HALF_UP)


def add_months(d: date, months: int, anchor_day: int) -> date:
    """Shift `d` by `months`; the day is `anchor_day` clamped to the month's length."""
    year, month_index = divmod(d.year * 12 + d.month - 1 + months, 12)
    month = month_index + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor_day, last_day))


def next_renewal(start: date, cycle: BillingCycle, today: date) -> date:
    """Earliest `start + k*cycle` (k >= 0, anchored to start.day) that is >= today."""
    step = CYCLE_MONTHS[cycle]
    month_diff = (today.year - start.year) * 12 + today.month - start.month
    k = max(0, month_diff // step)
    candidate = add_months(start, k * step, start.day)
    if candidate < today:
        candidate = add_months(start, (k + 1) * step, start.day)
    return candidate


def monthly_equivalent(amount: Decimal, cycle: BillingCycle) -> Decimal:
    """Per-month cost of a subscription, rounded to 2 places."""
    return _round(amount / CYCLE_MONTHS[cycle])


def yearly_amount(amount: Decimal, cycle: BillingCycle) -> Decimal:
    """Per-year cost in the subscription's own currency (amount * 12 / cycle months), rounded to 2 places."""
    return _round(amount * 12 / CYCLE_MONTHS[cycle])


def today_ist(now: datetime | None = None) -> date:
    """Current calendar date in Asia/Kolkata (`now` must be tz-aware if given)."""
    return (now or datetime.now(IST)).astimezone(IST).date()


def monthly_unrounded(amount: Decimal, cycle: BillingCycle) -> Decimal:
    """Per-month cost with no rounding, so sums can be rounded once at the end."""
    return amount / CYCLE_MONTHS[cycle]


def round_money(value: Decimal) -> Decimal:
    """Round to 2 places, half up."""
    return _round(value)
