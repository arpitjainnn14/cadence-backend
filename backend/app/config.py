from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from environment variables. Defaults are for local development only."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/subs"
    jwt_secret: str = "dev-insecure"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cookie_secure: bool = True
    scheduler_secret: str = "dev-insecure"
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:dev@example.com"
    default_usd_rate: Decimal = Decimal("88")


@lru_cache
def get_settings() -> Settings:
    return Settings()
