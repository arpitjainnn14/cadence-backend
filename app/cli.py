"""Operator CLI: `uv run python -m app.cli create-user --email E` and `... seed-cards [--file F]`.

Settings fail closed on weak secrets, so local runs need `COOKIE_SECURE=false` (or real secrets) in the environment.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy.orm import Session

from app.auth.repository import UserRepository
from app.auth.security import hash_password
from app.core import db as core_db
from app.insights.repository import SettingsRepository
from app.payment_methods.repository import PaymentMethodRepository
from app.shared.enums import CardNetwork, PaymentMethodType

MIN_PASSWORD_LENGTH = 12
DEFAULT_CARDS_FILE = Path(__file__).resolve().parent.parent / "seed" / "cards.json"
UPI_APPS = ("GPay", "PhonePe", "Paytm")
DEFAULT_USD_INR_RATE = "88"

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Subs operator commands.")


@contextmanager
def unit_of_work() -> Iterator[Session]:
    """One session per command: commit on success, roll back on error. Looked up at call time so tests can swap it."""
    with core_db.SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


@app.command("create-user")
def create_user(email: Annotated[str, typer.Option(help="Login email for the (single) user.")]) -> None:
    """Create the one and only user. Fails if a user already exists. The password is always prompted."""
    with unit_of_work() as session:
        users = UserRepository(session)
        if users.any_exists():
            typer.echo("A user already exists; this app is single-user.", err=True)
            raise typer.Exit(1)
        password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
        if len(password) < MIN_PASSWORD_LENGTH:
            typer.echo(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", err=True)
            raise typer.Exit(1)
        user = users.create(email, hash_password(password))
        created_email = user.email
    typer.echo(f"Created user {created_email}.")


@app.command("seed-cards")
def seed_cards(
    file: Annotated[Path, typer.Option(help="Card catalogue JSON; images are read from an `images/` folder beside it.")] = DEFAULT_CARDS_FILE,
) -> None:
    """Idempotently seed the card catalogue, UPI apps and the default USD to INR rate.

    Existing rows are matched by (type, bank, name, network). An image is only set when the row has none,
    so art uploaded later is never overwritten, and an existing usd_inr_rate is never changed.
    """
    entries = json.loads(file.read_text())
    with unit_of_work() as session:
        methods = PaymentMethodRepository(session)
        created = 0
        for entry in entries:
            type_, network = PaymentMethodType(entry["type"]), CardNetwork(entry["network"])
            method = methods.find_by_identity(type_, entry["bank"], entry["name"], network)
            if method is None:
                method = methods.add(type_, entry["bank"], entry["name"], network)
                created += 1
            if method.image is None:
                methods.set_image(method, (file.parent / "images" / entry["image"]).read_bytes(), "image/webp")
        for upi_app in UPI_APPS:
            if methods.find_by_identity(PaymentMethodType.upi, None, upi_app, None) is None:
                methods.add(PaymentMethodType.upi, None, upi_app, None)
                created += 1
        settings = SettingsRepository(session)
        if settings.get("usd_inr_rate") is None:
            settings.set("usd_inr_rate", DEFAULT_USD_INR_RATE)
    typer.echo(f"Seeded: {created} new payment methods ({len(entries)} cards + {len(UPI_APPS)} UPI apps in catalogue).")


if __name__ == "__main__":
    app()
