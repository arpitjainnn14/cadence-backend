import json
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from app.auth.models import User
from app.cli import app
from app.insights.repository import SettingsRepository
from app.payment_methods.models import PaymentMethod
from app.payment_methods.repository import PaymentMethodRepository
from app.shared.enums import CardNetwork, PaymentMethodType
from tests.conftest import use_test_sessions

PASSWORD = "a-long-enough-pass"
runner = CliRunner()


@pytest.fixture
def cli_db(engine, db, monkeypatch):
    """`db` (which truncates after the test) plus the CLI's sessions pointed at the test DB."""
    use_test_sessions(monkeypatch, engine)
    return db


def create_user(email="arpit@example.com", password=PASSWORD, confirm=None):
    return runner.invoke(app, ["create-user", "--email", email], input=f"{password}\n{confirm or password}\n")


# --- create-user ---


def test_create_user_once(cli_db):
    first = create_user()
    assert first.exit_code == 0, first.output
    second = create_user("other@example.com")
    assert second.exit_code != 0
    assert "already exists" in second.output
    users = cli_db.scalars(select(User)).all()
    assert [u.email for u in users] == ["arpit@example.com"]
    assert users[0].password_hash != PASSWORD


def test_create_user_rejects_short_password(cli_db):
    result = create_user(password="short-pass")  # 10 chars
    assert result.exit_code != 0
    assert "at least 12" in result.output
    assert cli_db.scalars(select(User)).all() == []


def test_create_user_password_mismatch(cli_db):
    result = create_user(confirm="a-different-password")
    assert result.exit_code != 0
    assert cli_db.scalars(select(User)).all() == []


# --- seed-cards ---


def cards(db):
    return db.scalars(select(PaymentMethod).where(PaymentMethod.type == PaymentMethodType.credit_card)).all()


def test_seed_idempotent(cli_db):
    for _ in range(2):
        result = runner.invoke(app, ["seed-cards"])
        assert result.exit_code == 0, result.output
    cli_db.expire_all()
    assert len(cards(cli_db)) == 11
    upi = cli_db.scalars(select(PaymentMethod).where(PaymentMethod.type == PaymentMethodType.upi)).all()
    assert sorted(p.name for p in upi) == ["GPay", "Paytm", "PhonePe"]
    assert all(p.bank is None and p.network is None and p.image is None for p in upi)
    assert all(c.image and c.image_mime == "image/webp" for c in cards(cli_db))
    sapphiros = [c for c in cards(cli_db) if c.name == "Sapphiro"]
    assert {c.network for c in sapphiros} == {CardNetwork.rupay, CardNetwork.visa}


def test_seed_keeps_existing_image(cli_db):
    runner.invoke(app, ["seed-cards"])
    card = cards(cli_db)[0]
    card.image = b"custom-upload"
    card.image_mime = "image/png"
    cli_db.commit()
    runner.invoke(app, ["seed-cards"])
    cli_db.expire_all()
    same = cli_db.get(PaymentMethod, card.id)
    assert same.image == b"custom-upload" and same.image_mime == "image/png"


def test_seed_custom_file(cli_db, tmp_path: Path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "x.webp").write_bytes(b"webp-bytes")
    f = tmp_path / "cards.json"
    f.write_text(json.dumps([{"type": "credit_card", "bank": "HDFC", "name": "Test", "network": "visa", "image": "x.webp"}]))
    result = runner.invoke(app, ["seed-cards", "--file", str(f)])
    assert result.exit_code == 0, result.output
    cli_db.expire_all()
    [card] = cards(cli_db)
    assert card.name == "Test" and card.image == b"webp-bytes"


def test_seed_sets_usd_rate(cli_db):
    runner.invoke(app, ["seed-cards"])
    assert SettingsRepository(cli_db).get("usd_inr_rate") == "88"


def test_seed_never_overwrites_usd_rate(cli_db):
    SettingsRepository(cli_db).set("usd_inr_rate", "91.5")
    cli_db.commit()
    runner.invoke(app, ["seed-cards"])
    cli_db.expire_all()
    assert SettingsRepository(cli_db).get("usd_inr_rate") == "91.5"


# --- repositories ---


def test_payment_method_repository(db):
    repo = PaymentMethodRepository(db)
    assert repo.find_by_identity(PaymentMethodType.upi, None, "GPay", None) is None
    upi = repo.add(PaymentMethodType.upi, None, "GPay", None)
    card = repo.add(PaymentMethodType.credit_card, "SBI", "Cashback", CardNetwork.visa)
    assert repo.find_by_identity(PaymentMethodType.upi, None, "GPay", None) == upi
    assert repo.find_by_identity(PaymentMethodType.credit_card, "SBI", "Cashback", CardNetwork.visa) == card
    assert repo.find_by_identity(PaymentMethodType.credit_card, "SBI", "Cashback", CardNetwork.rupay) is None
    repo.set_image(card, b"img", "image/webp")
    db.expire_all()
    assert (card.image, card.image_mime) == (b"img", "image/webp")


def test_settings_repository(db):
    repo = SettingsRepository(db)
    assert repo.get("k") is None
    repo.set("k", "1")
    repo.set("k", "2")  # overwrite
    db.expire_all()
    assert repo.get("k") == "2"
