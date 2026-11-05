from typing import Annotated

from fastapi import Depends
from sqlalchemy import text

from app.core.db import DbSession


class HealthRepository:
    """Database liveness probe."""

    def __init__(self, db: DbSession) -> None:
        self.db = db

    def ping(self) -> None:
        """Run SELECT 1; raises if the database is unreachable."""
        self.db.execute(text("SELECT 1"))

    def reset(self) -> None:
        """Roll back the session, clearing any aborted transaction."""
        self.db.rollback()


def get_health_repo(db: DbSession) -> HealthRepository:
    return HealthRepository(db)


HealthRepo = Annotated[HealthRepository, Depends(get_health_repo)]
