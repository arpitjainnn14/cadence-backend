from decimal import Decimal

from app.core.config import get_settings
from app.insights.repository import SettingsRepository

USD_RATE_KEY = "usd_inr_rate"


def get_usd_rate(settings_repo: SettingsRepository) -> Decimal:
    """The USD to INR rate from app_settings, or the configured default if never set."""
    value = settings_repo.get(USD_RATE_KEY)
    return Decimal(value) if value is not None else get_settings().default_usd_rate
