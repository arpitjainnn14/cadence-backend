"""Operator CLI: `uv run python -m app.cli create-user --email E` `... seed-cards [--file F]` and `... update-cards --file F`.

Settings fail closed on weak secrets, so local runs need `COOKIE_SECURE=false` (or real secrets) in the environment.
"""

import io
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy.orm import Session

from app.auth.repository import UserRepository
from app.auth.security import hash_password
from app.core import db as core_db
from app.payment_methods.repository import PaymentMethodRepository
from app.payment_methods.service import InvalidPaymentMethod, read_image
from app.shared.enums import CardNetwork, PaymentMethodType

MIN_PASSWORD_LENGTH = 8
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_CARDS_FILE = Path(__file__).resolve().parent.parent / "seed" / "cards.json"
UPI_APPS = ("GPay", "PhonePe", "Paytm", "CRED UPI", "slice UPI")

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Cadence operator commands.")


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
    if not EMAIL_PATTERN.match(email.strip()):
        typer.echo("Enter a valid email address (local@domain.tld).", err=True)
        raise typer.Exit(1)
    with unit_of_work() as session:  # short unit of work: only the pre-check, so no transaction is open while prompting
        exists = UserRepository(session).any_exists()
    if exists:
        typer.echo("A user already exists; this app is single-user.", err=True)
        raise typer.Exit(1)
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < MIN_PASSWORD_LENGTH:
        typer.echo(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", err=True)
        raise typer.Exit(1)
    with unit_of_work() as session:
        created_email = UserRepository(session).create(email, hash_password(password)).email
    typer.echo(f"Created user {created_email}.")


@app.command("seed-cards")
def seed_cards(
    file: Annotated[Path, typer.Option(help="Card catalogue JSON; images are read from an `images/` folder beside it.")] = DEFAULT_CARDS_FILE,
) -> None:
    """Idempotently seed the card catalogue and UPI apps.

    Existing rows are matched by (type, bank, name, network). An image is only set when the row has none,
    so art uploaded later is never overwritten.
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
    typer.echo(f"Seeded: {created} new payment methods ({len(entries)} cards + {len(UPI_APPS)} UPI apps in catalogue).")


@app.command("update-cards")
def update_cards(
    file: Annotated[Path, typer.Option(help="JSON list of {match, set, image}; images are read from the file's folder.")],
) -> None:
    """One-off: rename cards and apply real card art. Idempotent; all-or-nothing on a bad image.

    A card is found by `match` (type credit_card, bank, name, network), else by `set`, so re-runs are safe.
    """
    entries = json.loads(file.read_text())
    with unit_of_work() as session:
        methods = PaymentMethodRepository(session)
        updated = missing = 0
        for entry in entries:
            match, new = entry["match"], entry["set"]
            network = CardNetwork(match["network"])
            card_type = PaymentMethodType.credit_card
            method = methods.find_by_identity(card_type, match["bank"], match["name"], network) or methods.find_by_identity(
                card_type, new["bank"], new["name"], network
            )
            if method is None:
                typer.echo(f"not found: {match['bank']} {match['name']} ({match['network']})", err=True)
                missing += 1
                continue
            try:
                image, mime = read_image(io.BytesIO((file.parent / entry["image"]).read_bytes()))
            except InvalidPaymentMethod as e:
                typer.echo(f"invalid image {entry['image']}: {e}; nothing was changed.", err=True)
                raise typer.Exit(1) from None
            methods.update(method, {"bank": new["bank"], "name": new["name"]})
            methods.set_image(method, image, mime)
            typer.echo(f"updated: {method.display_name}")
            updated += 1
    typer.echo(f"Done: {updated} updated, {missing} not found.")


if __name__ == "__main__":
    app()
