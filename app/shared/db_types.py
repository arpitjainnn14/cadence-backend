from sqlalchemy import Enum


def pg_enum(cls: type, name: str) -> Enum:
    """Native Postgres enum storing the StrEnum *values*."""
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])
