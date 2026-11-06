from sqlalchemy.orm import Session

from app.insights.models import AppSetting


class SettingsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, key: str) -> str | None:
        """The setting's value, or None if it was never set."""
        setting = self.db.get(AppSetting, key)
        return setting.value if setting else None

    def set(self, key: str, value: str) -> None:
        """Insert or overwrite a setting. Flushes; the caller's unit of work commits."""
        self.db.merge(AppSetting(key=key, value=value))
        self.db.flush()

    def delete(self, key: str) -> None:
        """Remove a setting; a no-op if it isn't set."""
        setting = self.db.get(AppSetting, key)
        if setting is not None:
            self.db.delete(setting)
            self.db.flush()
