from decimal import Decimal

import pytest

from app.shared.money import format_inr, format_usd


@pytest.mark.parametrize(
    "amount, text",
    [
        ("649", "₹649"),
        ("649.00", "₹649"),
        ("199.50", "₹199.50"),
        ("1000", "₹1,000"),
        ("124500", "₹1,24,500"),
        ("1000000", "₹10,00,000"),
        ("0.5", "₹0.50"),
    ],
)
def test_format_inr(amount, text):
    assert format_inr(Decimal(amount)) == text


@pytest.mark.parametrize(
    "amount, text", [("20", "$20"), ("20.00", "$20"), ("9.99", "$9.99"), ("1234.5", "$1,234.50")]
)
def test_format_usd(amount, text):
    assert format_usd(Decimal(amount)) == text
