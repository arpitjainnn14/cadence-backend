from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """Unit of work per request: commit on success, roll back and re-raise on error."""
    with SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# scope="function": the commit/rollback in get_db runs as soon as the endpoint returns, i.e. BEFORE the
# response is sent. With the default (request) scope it would run after, so a client could receive a 200
# and read stale data, and a failed commit could not turn into an error response.
DbSession = Annotated[Session, Depends(get_db, scope="function")]
