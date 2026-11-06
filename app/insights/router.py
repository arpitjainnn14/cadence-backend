from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.auth.deps import current_user
from app.insights import service
from app.insights.deps import get_settings_repo
from app.insights.repository import SettingsRepository
from app.insights.schemas import InsightsOut, SettingsIn, SettingsOut, SummaryOut
from app.payment_methods.deps import get_payment_method_repo
from app.payment_methods.repository import PaymentMethodRepository
from app.shared.billing import today_ist
from app.subscriptions.deps import get_subscription_repo
from app.subscriptions.repository import SubscriptionRepository

router = APIRouter(prefix="/api", tags=["insights"], dependencies=[Depends(current_user)])

Subs = Annotated[SubscriptionRepository, Depends(get_subscription_repo)]
PaymentMethods = Annotated[PaymentMethodRepository, Depends(get_payment_method_repo)]
SettingsRepo = Annotated[SettingsRepository, Depends(get_settings_repo)]


@router.get("/summary", response_model=SummaryOut)
def read_summary(subs: Subs, payment_methods: PaymentMethods, settings: SettingsRepo) -> SummaryOut:
    return service.summary(subs, payment_methods, settings, today_ist())


@router.get("/insights", response_model=InsightsOut)
def read_insights(
    subs: Subs,
    payment_methods: PaymentMethods,
    period: Literal["monthly", "yearly"] = "monthly",
) -> InsightsOut:
    return service.insights(subs, payment_methods, period, today_ist())


@router.get("/settings", response_model=SettingsOut)
def read_settings(settings: SettingsRepo) -> SettingsOut:
    return SettingsOut(monthly_budget_inr=service.get_budget(settings))


@router.put("/settings", response_model=SettingsOut)
def write_settings(body: SettingsIn, settings: SettingsRepo) -> SettingsOut:
    return SettingsOut(monthly_budget_inr=service.set_budget(settings, body.monthly_budget_inr))
