from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.auth.deps import current_user
from app.insights import service
from app.insights.schemas import InsightsOut, SummaryOut
from app.payment_methods.deps import get_payment_method_repo
from app.payment_methods.repository import PaymentMethodRepository
from app.shared.billing import today_ist
from app.subscriptions.deps import get_subscription_repo
from app.subscriptions.repository import SubscriptionRepository

router = APIRouter(prefix="/api", tags=["insights"], dependencies=[Depends(current_user)])

Subs = Annotated[SubscriptionRepository, Depends(get_subscription_repo)]
PaymentMethods = Annotated[PaymentMethodRepository, Depends(get_payment_method_repo)]


@router.get("/summary", response_model=SummaryOut)
def read_summary(subs: Subs, payment_methods: PaymentMethods) -> SummaryOut:
    return service.summary(subs, payment_methods, today_ist())


@router.get("/insights", response_model=InsightsOut)
def read_insights(
    subs: Subs,
    payment_methods: PaymentMethods,
    period: Literal["monthly", "yearly"] = "monthly",
) -> InsightsOut:
    return service.insights(subs, payment_methods, period, today_ist())
