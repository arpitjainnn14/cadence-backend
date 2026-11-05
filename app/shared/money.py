"""Display formatting for money amounts."""

from decimal import ROUND_HALF_UP, Decimal


def _plain(amount: Decimal) -> str:
    """Two decimals, or none when the amount is whole."""
    amount = amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
    return f"{amount:f}".removesuffix(".00")


def _indian_group(digits: str) -> str:
    """Group digits as last three, then pairs: 1245000 -> 12,45,000."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *pairs, tail])


def format_inr(amount: Decimal) -> str:
    """`₹649`, `₹1,24,500`, `₹199.50` (Indian digit grouping, decimals only when fractional)."""
    whole, _, frac = _plain(amount).partition(".")
    return "₹" + _indian_group(whole) + (f".{frac}" if frac else "")


def format_usd(amount: Decimal) -> str:
    """`$20`, `$9.99`, `$1,234.50`."""
    whole, _, frac = _plain(amount).partition(".")
    return f"${int(whole):,}" + (f".{frac}" if frac else "")
