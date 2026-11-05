import os
from collections.abc import Iterator, Mapping
from typing import Annotated, Any

from fastapi import Depends

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

def engine_options(env: Mapping[str, str]) -> dict[str, Any]:
    """create_engine kwargs for the current runtime.

    On Vercel (VERCEL is set) every invocation may run in a fresh or frozen instance, so an in-process pool
    would hold connections that Neon has already dropped: use NullPool and let Neon's pooled endpoint
    (PgBouncer) do the pooling. Elsewhere (Cloud Run, local) keep a regular pool.
    """
    options: dict[str, Any] = {
        # Never use server-side prepared statements (psycopg 3 would otherwise prepare after 5 executes,
        # which breaks when PgBouncer hands each transaction a different backend).
        "connect_args": {"prepare_threshold": None},
    }
    if env.get("VERCEL"):
        options["poolclass"] = NullPool
    else:
        # Neon closes idle connections: ping before use and recycle before it drops them.
        options["pool_pre_ping"] = True
        options["pool_recycle"] = 300
    return options


engine = create_engine(get_settings().database_url, **engine_options(os.environ))
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
