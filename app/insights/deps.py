from app.core.db import DbSession
from app.insights.repository import SettingsRepository


def get_settings_repo(db: DbSession) -> SettingsRepository:
    return SettingsRepository(db)
