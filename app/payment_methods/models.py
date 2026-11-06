import re
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
    color: Mapped[str | None] = mapped_column(String)
    image: Mapped[bytes | None] = mapped_column(LargeBinary)
    image_mime: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def display_name(self) -> str:
        """`bank name`, unless the bank already appears in the name as a whole word (case-insensitive)."""
        if self.bank and not re.search(rf"(?<!\w){re.escape(self.bank)}(?!\w)", self.name, re.IGNORECASE):
            return f"{self.bank} {self.name}"
        return self.name

    @property
    def has_image(self) -> bool:
        """True when card art is stored (checked via the mime so the image blob isn't loaded)."""
        return self.image_mime is not None
