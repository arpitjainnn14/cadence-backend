import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, LargeBinary, String, Uuid, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.shared.db_types import pg_enum
from app.shared.enums import CardNetwork, PaymentMethodType


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[PaymentMethodType] = mapped_column(pg_enum(PaymentMethodType, "payment_method_type"))
    bank: Mapped[str | None] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    network: Mapped[CardNetwork | None] = mapped_column(pg_enum(CardNetwork, "card_network"))
    image: Mapped[bytes | None] = mapped_column(LargeBinary)
    image_mime: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def display_name(self) -> str:
        """`bank name`, unless the name already starts with the bank (case-insensitive)."""
        if self.bank and not self.name.lower().startswith(self.bank.lower()):
            return f"{self.bank} {self.name}"
        return self.name
