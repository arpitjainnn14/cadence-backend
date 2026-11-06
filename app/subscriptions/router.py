import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth.deps import current_user
from app.payment_methods.deps import get_payment_method_repo
from app.payment_methods.repository import PaymentMethodRepository
from app.shared.billing import today_ist
from app.shared.enums import SubscriptionStatus
from app.subscriptions import service
from app.subscriptions.deps import get_subscription_repo
from app.subscriptions.models import CATEGORIES
from app.subscriptions.repository import SubscriptionRepository
from app.subscriptions.schemas import MerchantResolution, SubscriptionIn, SubscriptionOut, SubscriptionUpdate

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"], dependencies=[Depends(current_user)])
merchants_router = APIRouter(prefix="/api/merchants", tags=["subscriptions"], dependencies=[Depends(current_user)])

Repo = Annotated[SubscriptionRepository, Depends(get_subscription_repo)]
PaymentMethods = Annotated[PaymentMethodRepository, Depends(get_payment_method_repo)]


def _out(sub) -> SubscriptionOut:
    return service.to_out(sub, today_ist())


def _write(fn, *args):
    """Run a service write, mapping its domain errors to HTTP errors."""
    try:
        return fn(*args)
    except service.SubscriptionNotFound:
        raise HTTPException(status_code=404, detail="Subscription not found") from None
    except service.InvalidDates as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except service.UnknownPaymentMethod:
        raise HTTPException(status_code=422, detail="Unknown payment method") from None


@merchants_router.get("/resolve", response_model=MerchantResolution)
def resolve_merchant(name: Annotated[str, Query(max_length=80)]) -> MerchantResolution:
    return service.resolve_merchant(name)


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(
    repo: Repo,
    status: SubscriptionStatus | None = None,
    payment_method_id: uuid.UUID | None = None,
    category: Annotated[str | None, Query(description="One of the known categories")] = None,
    sort: service.SortKey = "name",
) -> list[SubscriptionOut]:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown category")
    return service.list_subscriptions(repo, today_ist(), status, payment_method_id, category, sort)


@router.post("", status_code=201, response_model=SubscriptionOut)
def create_subscription(data: SubscriptionIn, repo: Repo, payment_methods: PaymentMethods):
    return _out(_write(service.create_subscription, repo, payment_methods, data, today_ist()))


@router.get("/{sub_id}", response_model=SubscriptionOut)
def get_subscription(sub_id: uuid.UUID, repo: Repo):
    return _out(_write(service.get_subscription, repo, sub_id))


@router.put("/{sub_id}", response_model=SubscriptionOut)
def replace_subscription(
    sub_id: uuid.UUID, data: SubscriptionUpdate, repo: Repo, payment_methods: PaymentMethods
):
    return _out(_write(service.replace_subscription, repo, payment_methods, sub_id, data, today_ist()))


@router.delete("/{sub_id}", status_code=204)
def delete_subscription(sub_id: uuid.UUID, repo: Repo) -> Response:
    _write(service.delete_subscription, repo, sub_id)
    return Response(status_code=204)
