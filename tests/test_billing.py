from datetime import UTC, date, datetime
from decimal import Decimal

from app.shared.billing import (
    add_months,
    monthly_equivalent,
    next_renewal,
    yearly_amount,
    today_ist,
)
from app.shared.enums import BillingCycle


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1, 31) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 31), 2, 31) == date(2026, 3, 31)
    assert add_months(date(2026, 11, 15), 3, 15) == date(2027, 2, 15)


def test_month_end_anchor():
    s = date(2026, 1, 31)
    assert next_renewal(s, BillingCycle.monthly, date(2026, 2, 1)) == date(2026, 2, 28)
    assert next_renewal(s, BillingCycle.monthly, date(2026, 3, 1)) == date(2026, 3, 31)
    assert next_renewal(s, BillingCycle.monthly, date(2026, 4, 1)) == date(2026, 4, 30)


def test_leap_year():
    assert next_renewal(
        date(2027, 1, 31), BillingCycle.monthly, date(2028, 2, 1)
    ) == date(2028, 2, 29)


def test_renewal_today_is_today():
    assert next_renewal(
        date(2026, 1, 10), BillingCycle.monthly, date(2026, 5, 10)
    ) == date(2026, 5, 10)


def test_future_start():
    assert next_renewal(
        date(2026, 12, 1), BillingCycle.yearly, date(2026, 11, 4)
    ) == date(2026, 12, 1)


def test_quarterly_half_yearly_yearly():
    assert next_renewal(
        date(2026, 1, 15), BillingCycle.quarterly, date(2026, 4, 16)
    ) == date(2026, 7, 15)
    assert next_renewal(
        date(2026, 1, 15), BillingCycle.half_yearly, date(2026, 1, 16)
    ) == date(2026, 7, 15)
    assert next_renewal(
        date(2024, 2, 29), BillingCycle.yearly, date(2025, 1, 1)
    ) == date(2025, 2, 28)


def test_monthly_equivalent():
    assert monthly_equivalent(Decimal("1499"), BillingCycle.yearly) == Decimal("124.92")
    assert monthly_equivalent(Decimal("899"), BillingCycle.quarterly) == Decimal("299.67")
    assert monthly_equivalent(Decimal("199"), BillingCycle.monthly) == Decimal("199.00")


def test_yearly_amount():
    assert yearly_amount(Decimal("649"), BillingCycle.monthly) == Decimal("7788.00")
    assert yearly_amount(Decimal("899"), BillingCycle.quarterly) == Decimal("3596.00")
    assert yearly_amount(Decimal("1499"), BillingCycle.yearly) == Decimal("1499.00")
    assert yearly_amount(Decimal("100"), BillingCycle.half_yearly) == Decimal("200.00")
    assert yearly_amount(Decimal("10.01"), BillingCycle.quarterly) == Decimal("40.04")


def test_today_ist_crosses_midnight():
    # 19:00 UTC is 00:30 IST the next day
    assert today_ist(datetime(2026, 11, 4, 19, 0, tzinfo=UTC)) == date(2026, 11, 5)


def test_monthly_unrounded_keeps_precision():
    from app.shared.billing import monthly_unrounded

    got = monthly_unrounded(Decimal("1499"), BillingCycle.yearly)
    assert got != Decimal("124.92") and abs(got - Decimal("124.9166667")) < Decimal("0.000001")
    assert monthly_unrounded(Decimal("20"), BillingCycle.monthly) == Decimal("20")
