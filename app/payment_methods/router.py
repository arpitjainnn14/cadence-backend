import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile

from app.auth.deps import current_user
from app.payment_methods import service
from app.payment_methods.deps import get_payment_method_repo
from app.payment_methods.models import PaymentMethod
from app.payment_methods.repository import PaymentMethodRepository
from app.payment_methods.schemas import PaymentMethodCreate, PaymentMethodOut, PaymentMethodUpdate

router = APIRouter(prefix="/api/payment-methods", tags=["payment-methods"], dependencies=[Depends(current_user)])

Repo = Annotated[PaymentMethodRepository, Depends(get_payment_method_repo)]


def _image(upload: UploadFile | None) -> tuple[bytes, str] | None:
    if upload is None:
        return None
    try:
        return service.read_image(upload.file)
    except service.InvalidPaymentMethod as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


def _call(fn, *args) -> PaymentMethod:
    """Run a service function, mapping its domain errors to HTTP errors."""
    try:
        return fn(*args)
    except service.PaymentMethodNotFound:
        raise HTTPException(status_code=404, detail="Payment method not found") from None
    except service.InvalidPaymentMethod as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


@router.get("", response_model=list[PaymentMethodOut])
def list_payment_methods(repo: Repo, include_inactive: bool = False) -> list[PaymentMethod]:
    return service.list_methods(repo, include_inactive)


@router.post("", status_code=201, response_model=PaymentMethodOut)
def create_payment_method(
    repo: Repo,
    data: Annotated[PaymentMethodCreate, Form()],
    image: Annotated[UploadFile | None, File()] = None,
) -> PaymentMethod:
    return service.create_method(repo, data, _image(image))


@router.patch("/{method_id}", response_model=PaymentMethodOut)
def update_payment_method(method_id: uuid.UUID, data: PaymentMethodUpdate, repo: Repo) -> PaymentMethod:
    return _call(service.update_method, repo, method_id, data)


@router.put("/{method_id}/image", response_model=PaymentMethodOut)
def replace_payment_method_image(method_id: uuid.UUID, image: Annotated[UploadFile, File()], repo: Repo) -> PaymentMethod:
    _call(service.get_method, repo, method_id)  # not-found takes precedence over image errors
    return _call(service.replace_image, repo, method_id, _image(image))


@router.get("/{method_id}/image")
def get_payment_method_image(
    method_id: uuid.UUID, repo: Repo, if_none_match: Annotated[str | None, Header()] = None
) -> Response:
    try:
        data, mime = service.get_image(repo, method_id)
    except service.PaymentMethodNotFound:
        raise HTTPException(status_code=404, detail="Payment method not found") from None
    except service.ImageNotFound:
        raise HTTPException(status_code=404, detail="Image not found") from None
    # no-cache + ETag: the browser revalidates every time (cheap 304) so replaced art shows up immediately.
    etag = f'"{hashlib.sha256(data).hexdigest()}"'
    headers = {"Cache-Control": "private, no-cache", "ETag": etag, "X-Content-Type-Options": "nosniff"}
    if _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=mime, headers=headers)


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    """True if any listed validator (weak or strong) equals etag, or the header is `*`."""
    if not if_none_match:
        return False
    candidates = [c.strip().removeprefix("W/") for c in if_none_match.split(",")]
    return "*" in candidates or etag in candidates
