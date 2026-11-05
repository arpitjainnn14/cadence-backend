from decimal import Decimal
from functools import lru_cache

from pydantic import model_validator
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

    @model_validator(mode="after")
    def _secrets_must_be_strong_in_production(self) -> "Settings":
        # cookie_secure=True means production: fail closed instead of running with forgeable tokens.
        if self.cookie_secure:
            for name in ("jwt_secret", "scheduler_secret"):
                value = getattr(self, name)
                if value == "dev-insecure" or len(value) < 32:
                    raise ValueError(f"{name} must be set to a random value of at least 32 characters")
            for name in ("vapid_private_key", "vapid_public_key", "vapid_subject"):
                if not getattr(self, name):
                    raise ValueError(f"{name} must be set in production")
            if not self.vapid_subject.startswith(("mailto:", "https://")):
                raise ValueError("vapid_subject must start with mailto: or https://")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
