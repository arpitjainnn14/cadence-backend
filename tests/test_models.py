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


def test_billing_anchor_migration_backfills_and_downgrades():
    from sqlalchemy import text

    eng = create_engine(TEST_DATABASE_URL)
    try:
        reset_schema(eng)
        cfg = alembic_config(TEST_DATABASE_URL)
        command.upgrade(cfg, "0003")
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO subscriptions (id, merchant_name, amount, currency, billing_cycle, start_date) "
                "VALUES (gen_random_uuid(), 'Old', 10, 'INR', 'monthly', '2025-01-31')"
            ))
        command.upgrade(cfg, "0004")
        with eng.begin() as conn:
            row = conn.execute(text("SELECT billing_anchor_date, started_on FROM subscriptions")).one()
            assert str(row.billing_anchor_date) == "2025-01-31" and str(row.started_on) == "2025-01-31"
            conn.execute(text("UPDATE subscriptions SET started_on = NULL, billing_anchor_date = '2025-02-28'"))
        command.downgrade(cfg, "0003")
        with eng.begin() as conn:
            assert str(conn.execute(text("SELECT start_date FROM subscriptions")).scalar_one()) == "2025-02-28"
    finally:
        command.upgrade(alembic_config(TEST_DATABASE_URL), "head")  # leave the shared schema at head
        eng.dispose()
