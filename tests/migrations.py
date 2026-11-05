"""Helpers to run Alembic against a given database URL (used by conftest and migration tests)."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

ROOT = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False  # keep Alembic from resetting logging during tests
    return cfg


def reset_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
