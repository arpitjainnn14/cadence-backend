import base64
import binascii
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
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
            self._validate_vapid_keys()
        return self

    def _validate_vapid_keys(self) -> None:
        """Fail at startup, not at the first push, when the VAPID keys are malformed."""
        try:
            Vapid.from_string(self.vapid_private_key)
        except Exception as exc:  # py_vapid raises assorted types for bad input
            raise ValueError(
                "vapid_private_key must be a raw base64url key (npx web-push generate-vapid-keys) "
                "or the base64url DER body from `vapid --gen`, without PEM headers"
            ) from exc
        try:
            public = base64.urlsafe_b64decode(self.vapid_public_key + "=" * (-len(self.vapid_public_key) % 4))
        except (binascii.Error, ValueError) as exc:
            raise ValueError("vapid_public_key must be base64url") from exc
        if len(public) != 65 or public[0] != 0x04:
            raise ValueError("vapid_public_key must decode to a 65-byte uncompressed P-256 point")
        derived = Vapid.from_string(self.vapid_private_key).public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        if derived != public:
            raise ValueError("vapid_public_key does not match vapid_private_key")


@lru_cache
def get_settings() -> Settings:
    return Settings()
