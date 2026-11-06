import pytest
from alembic import command
from sqlalchemy import create_engine

from app.models import PaymentMethod
from app.shared.enums import PaymentMethodType
from tests.conftest import TEST_DATABASE_URL
from tests.migrations import alembic_config, reset_schema


def test_migration_matches_models():
    """A fresh `upgrade head` must leave no drift between the migration and the models."""
    eng = create_engine(TEST_DATABASE_URL)
    try:
        reset_schema(eng)
        cfg = alembic_config(TEST_DATABASE_URL)
        command.upgrade(cfg, "head")
        command.check(cfg)  # raises CommandError if autogenerate finds pending changes
    finally:
        eng.dispose()


def _pm(bank, name):
    return PaymentMethod(type=PaymentMethodType.credit_card, bank=bank, name=name)


def test_display_name_prefixes_bank():
    assert _pm("ICICI", "Sapphiro").display_name == "ICICI Sapphiro"


@pytest.mark.parametrize(
    ("bank", "name", "expected"),
    [
        ("ICICI", "Amazon Pay ICICI", "Amazon Pay ICICI"),
        ("slice", "slice", "slice"),
        ("HDFC Bank", "MoneyBack+", "HDFC Bank MoneyBack+"),
        ("SBI Card", "Cashback", "SBI Card Cashback"),
        ("Axis", "Scapia", "Axis Scapia"),
        ("ICICI", "ICICIX Card", "ICICI ICICIX Card"),
        ("Scapia", "The scapia Federal", "The scapia Federal"),
    ],
)
def test_display_name_bank_as_whole_word(bank, name, expected):
    assert _pm(bank, name).display_name == expected


def test_display_name_without_bank():
    assert _pm(None, "GPay").display_name == "GPay"


def test_migration_downgrade_roundtrip():
    """Downgrade must drop tables and enum types so a re-upgrade works."""
    eng = create_engine(TEST_DATABASE_URL)
    try:
        reset_schema(eng)
        cfg = alembic_config(TEST_DATABASE_URL)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        eng.dispose()
