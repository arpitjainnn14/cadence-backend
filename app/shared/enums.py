from enum import StrEnum


class BillingCycle(StrEnum):
    monthly = "monthly"
    quarterly = "quarterly"
    half_yearly = "half_yearly"
    yearly = "yearly"


class Currency(StrEnum):
    INR = "INR"
    USD = "USD"


class SubscriptionStatus(StrEnum):
    active = "active"
    paused = "paused"
    cancelled = "cancelled"


class PaymentMethodType(StrEnum):
    credit_card = "credit_card"
    upi = "upi"
    other = "other"


class CardNetwork(StrEnum):
    visa = "visa"
    mastercard = "mastercard"
    rupay = "rupay"
