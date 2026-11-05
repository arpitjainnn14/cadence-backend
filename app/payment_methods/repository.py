from sqlalchemy import select
from sqlalchemy.orm import Session

from app.payment_methods.models import PaymentMethod
from app.shared.enums import CardNetwork, PaymentMethodType


class PaymentMethodRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def find_by_identity(
        self, type: PaymentMethodType, bank: str | None, name: str, network: CardNetwork | None
    ) -> PaymentMethod | None:
        """The payment method with exactly this (type, bank, name, network); None values match NULL."""
        stmt = select(PaymentMethod).where(
            PaymentMethod.type == type,
            PaymentMethod.bank.is_(None) if bank is None else PaymentMethod.bank == bank,
            PaymentMethod.name == name,
            PaymentMethod.network.is_(None) if network is None else PaymentMethod.network == network,
        )
        return self.db.scalar(stmt)

    def add(
        self, type: PaymentMethodType, bank: str | None, name: str, network: CardNetwork | None
    ) -> PaymentMethod:
        """Add a payment method. Flushes; the caller's unit of work commits."""
        method = PaymentMethod(type=type, bank=bank, name=name, network=network)
        self.db.add(method)
        self.db.flush()
        return method

    def set_image(self, method: PaymentMethod, image: bytes, mime: str) -> None:
        """Store the card art bytes and their MIME type."""
        method.image = image
        method.image_mime = mime
        self.db.flush()
