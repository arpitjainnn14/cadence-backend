import uuid
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, field_validator, StringConstraints, model_validator

from app.shared.enums import CardNetwork, PaymentMethodType

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Bank = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


def _blank_to_none(value: str | None) -> str | None:
    """Blank (empty or whitespace-only) means null; for multipart forms, where null cannot be sent."""
    return value.strip() or None if isinstance(value, str) else value


class PaymentMethodCreate(BaseModel):
    type: PaymentMethodType
    bank: Bank | None = None
    name: Name
    network: CardNetwork | None = None
    color: Color | None = None

    _blank = field_validator("bank", "network", "color", mode="before")(_blank_to_none)

    @model_validator(mode="after")
    def _network_matches_type(self) -> Self:
        check_network(self.type, self.network)
        return self


class PaymentMethodUpdate(BaseModel):
    """Any subset of fields. `bank` and `network` may be set to null; `name` and `is_active` may not."""

    bank: Bank | None = None
    name: Name | None = None
    network: CardNetwork | None = None
    is_active: bool | None = None
    color: Color | None = None

    _blank = field_validator("bank", "network", "color", mode="before")(_blank_to_none)

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> Self:
        for field in ("name", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class PaymentMethodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: PaymentMethodType
    bank: str | None
    name: str
    network: CardNetwork | None
    display_name: str
    color: str | None
    has_image: bool
    is_active: bool


def check_network(type: PaymentMethodType, network: CardNetwork | None) -> None:
    """Credit cards need a network; upi/other must not have one."""
    if type == PaymentMethodType.credit_card and network is None:
        raise ValueError("credit_card requires a network")
    if type != PaymentMethodType.credit_card and network is not None:
        raise ValueError(f"{type.value} must not have a network")
