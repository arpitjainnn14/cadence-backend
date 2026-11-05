import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app.auth.deps import current_user
from app.core.config import Settings, get_settings
from app.payment_methods.deps import get_payment_method_repo
from app.payment_methods.repository import PaymentMethodRepository
from app.reminders import service
from app.reminders.deps import get_push_repo, get_push_sender, get_reminder_log_repo
from app.reminders.repository import PushSubscriptionRepository, ReminderLogRepository
from app.reminders.schemas import (
    PublicKeyOut,
    PushResult,
    PushSubscribeIn,
    PushUnsubscribeIn,
    RunRemindersOut,
)
from app.shared.billing import today_ist
from app.subscriptions.deps import get_subscription_repo
from app.subscriptions.repository import SubscriptionRepository

router = APIRouter(prefix="/api/push", tags=["push"], dependencies=[Depends(current_user)])


def require_scheduler_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    x_scheduler_secret: Annotated[str, Header()] = "",
) -> None:
    """403 unless the X-Scheduler-Secret header matches (checked before any DB session is opened)."""
    if not x_scheduler_secret or not hmac.compare_digest(
        x_scheduler_secret.encode(), settings.scheduler_secret.encode()
    ):
        raise HTTPException(status_code=403, detail="Forbidden")


internal_router = APIRouter(
    prefix="/api/internal", tags=["internal"], dependencies=[Depends(require_scheduler_secret)]
)

AppSettings = Annotated[Settings, Depends(get_settings)]
PushRepo = Annotated[PushSubscriptionRepository, Depends(get_push_repo)]
Sender = Annotated[service.Sender, Depends(get_push_sender)]


@router.get("/public-key", response_model=PublicKeyOut)
def public_key(settings: AppSettings) -> PublicKeyOut:
    return PublicKeyOut(key=settings.vapid_public_key)


@router.post("/subscribe", status_code=204)
def subscribe(data: PushSubscribeIn, repo: PushRepo) -> Response:
    repo.upsert(data.endpoint, data.keys.p256dh, data.keys.auth)
    return Response(status_code=204)


@router.post("/unsubscribe", status_code=204)
def unsubscribe(data: PushUnsubscribeIn, repo: PushRepo) -> Response:
    repo.delete_by_endpoint(data.endpoint)
    return Response(status_code=204)


@router.post("/test", response_model=PushResult)
def test_push(repo: PushRepo, sender: Sender) -> PushResult:
    sent, removed = service.send_to_all(
        repo, sender, {"title": "Subs", "body": "Test notification from Subs", "url": "/"}
    )
    return PushResult(sent=sent, removed=removed)


@internal_router.post("/run-reminders", response_model=RunRemindersOut)
def run_reminders(
    subs: Annotated[SubscriptionRepository, Depends(get_subscription_repo)],
    push_repo: PushRepo,
    reminder_log: Annotated[ReminderLogRepository, Depends(get_reminder_log_repo)],
    payment_methods: Annotated[PaymentMethodRepository, Depends(get_payment_method_repo)],
    sender: Sender,
) -> dict[str, int]:
    """Called by the scheduler; authenticated by shared secret, not by user cookie."""
    return service.run_reminders(subs, push_repo, reminder_log, payment_methods, today_ist(), sender)
