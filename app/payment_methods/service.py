import uuid
from typing import BinaryIO

from app.payment_methods.models import PaymentMethod
from app.payment_methods.repository import PaymentMethodRepository
from app.payment_methods.schemas import PaymentMethodCreate, PaymentMethodUpdate, check_network

MAX_IMAGE_BYTES = 2 * 1024 * 1024


class PaymentMethodNotFound(Exception):
    pass


class ImageNotFound(Exception):
    pass


class InvalidPaymentMethod(Exception):
    """Business-rule violation (bad image, inconsistent type/network); maps to 422."""


def sniff_image_mime(data: bytes) -> str | None:
    """The image MIME type from magic bytes (png, jpeg, webp), or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_image(upload: BinaryIO) -> tuple[bytes, str]:
    """Read an upload (at most 2 MB + 1 byte) and validate it; returns (bytes, detected mime)."""
    data = upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidPaymentMethod("Image must be at most 2 MB")
    mime = sniff_image_mime(data)
    if mime is None:
        raise InvalidPaymentMethod("Image must be PNG, JPEG or WebP")
    return data, mime


def list_methods(repo: PaymentMethodRepository, include_inactive: bool) -> list[PaymentMethod]:
    """Payment methods in display order."""
    return repo.list(include_inactive)


def get_method(repo: PaymentMethodRepository, method_id: uuid.UUID) -> PaymentMethod:
    """The payment method, or PaymentMethodNotFound."""
    method = repo.get(method_id)
    if method is None:
        raise PaymentMethodNotFound
    return method


def create_method(
    repo: PaymentMethodRepository, data: PaymentMethodCreate, image: tuple[bytes, str] | None
) -> PaymentMethod:
    """Create a payment method, optionally with already-validated card art."""
    method = repo.add(data.type, data.bank, data.name, data.network, data.color)
    if image:
        repo.set_image(method, *image)
    return method


def update_method(repo: PaymentMethodRepository, method_id: uuid.UUID, data: PaymentMethodUpdate) -> PaymentMethod:
    """Apply the fields present in `data`; keeps the type/network rule intact."""
    method = get_method(repo, method_id)
    changes = data.model_dump(exclude_unset=True)
    try:
        check_network(method.type, changes.get("network", method.network))
    except ValueError as e:
        raise InvalidPaymentMethod(str(e)) from None
    repo.update(method, changes)
    return method


def replace_image(repo: PaymentMethodRepository, method_id: uuid.UUID, image: tuple[bytes, str]) -> PaymentMethod:
    """Replace the card art."""
    method = get_method(repo, method_id)
    repo.set_image(method, *image)
    return method


def get_image(repo: PaymentMethodRepository, method_id: uuid.UUID) -> tuple[bytes, str]:
    """(bytes, mime) of the card art, or ImageNotFound if there is none."""
    method = get_method(repo, method_id)
    if method.image is None or method.image_mime is None:
        raise ImageNotFound
    return method.image, method.image_mime
