import logging
from collections.abc import Callable
from datetime import date, timedelta
from urllib.parse import urlparse

from pywebpush import WebPushException

from app.payment_methods.repository import PaymentMethodRepository
from app.reminders.models import PushSubscription
from app.reminders.repository import PushSubscriptionRepository, ReminderLogRepository
from app.shared.billing import next_renewal
from app.shared.enums import Currency, SubscriptionStatus
from app.shared.money import format_inr, format_usd
from app.subscriptions.models import Subscription
from app.subscriptions.repository import SubscriptionRepository

logger = logging.getLogger("app.reminders")

Sender = Callable[[PushSubscription, dict], None]
GONE_STATUSES = {404, 410}
REMINDER_DAYS = 2


def _describe(push_sub: PushSubscription) -> str:
    """Subscription id and endpoint host only (the full endpoint is a bearer capability)."""
    return f"{push_sub.id} ({urlparse(push_sub.endpoint).hostname})"


def send_to_all(
    push_repo: PushSubscriptionRepository,
    sender: Sender,
    payload: dict,
    targets: list[PushSubscription] | None = None,
) -> tuple[int, int]:
    """Send `payload` to every push subscription. Returns (sent, removed).

    Subscriptions the push service reports gone (404/410) are deleted. Other failures are
    logged and skipped, so one bad endpoint never blocks the rest.
    """
    sent = removed = 0
    for push_sub in list(push_repo.list() if targets is None else targets):
        try:
            sender(push_sub, payload)
            sent += 1
        except WebPushException as exc:
            if exc.status_code in GONE_STATUSES:
                push_repo.delete(push_sub)
                if targets is not None:
                    targets.remove(push_sub)
                removed += 1
            else:
                logger.warning("push failed for %s: %s", _describe(push_sub), exc)
        except Exception as exc:  # network errors etc.: never abort the run
            logger.warning("push failed for %s: %s", _describe(push_sub), exc)
    return sent, removed


def _body(sub: Subscription, method_name: str | None) -> str:
    amount = format_usd(sub.amount) if sub.currency == Currency.USD else format_inr(sub.amount)
    return f"{sub.merchant_name} renews in {REMINDER_DAYS} days · {amount} · {method_name or 'no card'}"


def run_reminders(
    subs: SubscriptionRepository,
    push_repo: PushSubscriptionRepository,
    reminder_log: ReminderLogRepository,
    payment_methods: PaymentMethodRepository,
    today: date,
    sender: Sender,
) -> dict[str, int]:
    """Remind about active subscriptions renewing exactly 2 days from `today`.

    Each (subscription, renewal date) is claimed in the reminder log before sending, so it is
    reminded at most once. Trade-off: if every delivery fails, the claim stays and there is no retry.
    If the request raises mid-run, the claims roll back but sends already made stay sent,
    so a same-day re-run may duplicate.
    """
    target = today + timedelta(days=REMINDER_DAYS)
    due = sent = removed = 0
    targets = push_repo.list()
    for sub in subs.list(status=SubscriptionStatus.active):
        if next_renewal(sub.start_date, sub.billing_cycle, today) != target:
            continue
        if not reminder_log.claim(sub.id, target):
            continue
        due += 1
        method = payment_methods.get(sub.payment_method_id) if sub.payment_method_id else None
        payload = {"title": sub.merchant_name, "body": _body(sub, method.display_name if method else None), "url": "/"}
        s, r = send_to_all(push_repo, sender, payload, targets)
        sent += s
        removed += r
    return {"due": due, "sent": sent, "removed": removed}
