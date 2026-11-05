import uuid

from sqlalchemy import case, select
from sqlalchemy.orm import Session, defer

from app.payment_methods.models import PaymentMethod
from app.shared.enums import CardNetwork, PaymentMethodType


class PaymentMethodRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, include_inactive: bool) -> list[PaymentMethod]:
        """Payment methods: credit cards, then upi, then other; by bank (NULLs last), then name."""
        type_rank = case(
            (PaymentMethod.type == PaymentMethodType.credit_card, 0),
            (PaymentMethod.type == PaymentMethodType.upi, 1),
            else_=2,
        )
        stmt = (
            select(PaymentMethod)
            .options(defer(PaymentMethod.image))
            .order_by(type_rank, PaymentMethod.bank.asc().nulls_last(), PaymentMethod.name)
        )
        if not include_inactive:
            stmt = stmt.where(PaymentMethod.is_active.is_(True))
        return list(self.db.scalars(stmt))

    def get(self, method_id: uuid.UUID) -> PaymentMethod | None:
        """The payment method with this id, or None. The image blob loads lazily on access."""
        return self.db.scalar(
            select(PaymentMethod).options(defer(PaymentMethod.image)).where(PaymentMethod.id == method_id)
        )

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
        self,
        type: PaymentMethodType,
        bank: str | None,
        name: str,
        network: CardNetwork | None,
        color: str | None = None,
    ) -> PaymentMethod:
        """Add a payment method. Flushes; the caller's unit of work commits."""
        method = PaymentMethod(type=type, bank=bank, name=name, network=network, color=color)
        self.db.add(method)
        self.db.flush()
        return method

    def set_image(self, method: PaymentMethod, image: bytes, mime: str) -> None:
        """Store the card art bytes and their MIME type."""
        method.image = image
        method.image_mime = mime
        self.db.flush()

    def update(self, method: PaymentMethod, changes: dict[str, object]) -> None:
        """Set the given attributes (bank, name, network, is_active)."""
        for field, value in changes.items():
            setattr(method, field, value)
        self.db.flush()
