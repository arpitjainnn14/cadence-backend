import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pywebpush import WebPushException

from app.core.config import Settings, get_settings
from app.payment_methods.repository import PaymentMethodRepository
from app.reminders import service
from app.reminders.deps import get_push_sender
from app.reminders.repository import PushSubscriptionRepository, ReminderLogRepository
from app.shared.enums import BillingCycle, Currency, PaymentMethodType, SubscriptionStatus
from app.subscriptions.repository import SubscriptionRepository
from tests.conftest import TEST_DATABASE_URL, csrf_headers, login

TODAY = date(2026, 11, 5)
DUE = TODAY + timedelta(days=2)
SECRET = "test-scheduler-secret"


class FakeSender:
    def __init__(self, fail: dict[str, int] | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail or {}
        self.error = error

    def __call__(self, push_sub, payload) -> None:
        if self.error:
            raise self.error
        if push_sub.endpoint in self.fail:
            raise WebPushException("gone", response=type("R", (), {"status_code": self.fail[push_sub.endpoint]})())
        self.calls.append((push_sub.endpoint, payload))


@pytest.fixture
def repos(db):
    return {
        "subs": SubscriptionRepository(db),
        "push": PushSubscriptionRepository(db),
        "log": ReminderLogRepository(db),
        "methods": PaymentMethodRepository(db),
    }


def run(repos, sender, today=TODAY):
    return service.run_reminders(repos["subs"], repos["push"], repos["log"], repos["methods"], today, sender)


def add_sub(repos, **over):
    """A yearly sub renewing on DUE unless overridden."""
    fields = {
        "merchant_name": "Netflix",
        "amount": Decimal("649"),
        "currency": Currency.INR,
        "billing_cycle": BillingCycle.yearly,
        "start_date": DUE.replace(year=DUE.year - 1),
        "payment_method_id": None,
        **over,
    }
    return repos["subs"].add(**fields)


def add_card(repos, bank="ICICI", name="Sapphiro"):
    return repos["methods"].add(PaymentMethodType.credit_card, bank, name, None)


def add_push(repos, endpoint="https://push.example/a"):
    return repos["push"].upsert(endpoint, "p256", "authkey")


# --- repositories ---


def test_push_repo_upsert_updates_keys(repos):
    first = add_push(repos)
    again = repos["push"].upsert(first.endpoint, "new-p256", "new-auth")
    assert again.id == first.id
    assert (again.p256dh, again.auth) == ("new-p256", "new-auth")
    assert len(repos["push"].list()) == 1


def test_push_repo_delete_by_endpoint(repos):
    add_push(repos)
    repos["push"].delete_by_endpoint("https://push.example/a")
    repos["push"].delete_by_endpoint("https://push.example/a")  # absent: no error
    assert repos["push"].list() == []


def test_log_repo_claim_once(repos):
    sub = add_sub(repos)
    assert repos["log"].claim(sub.id, DUE) is True
    assert repos["log"].claim(sub.id, DUE) is False
    assert repos["log"].claim(sub.id, DUE + timedelta(days=30)) is True


# --- service ---


def test_due_exactly_two_days(repos):
    card = add_card(repos)
    add_sub(repos, payment_method_id=card.id)
    add_sub(repos, merchant_name="Tomorrow", start_date=date(2025, 11, 6))
    add_sub(repos, merchant_name="In3", start_date=date(2025, 11, 8))
    add_push(repos)
    sender = FakeSender()

    assert run(repos, sender) == {"due": 1, "sent": 1, "removed": 0}
    assert sender.calls == [
        (
            "https://push.example/a",
            {"title": "Netflix", "body": "Netflix renews in 2 days · ₹649 · ICICI Sapphiro", "url": "/"},
        )
    ]


def test_usd_body(repos):
    card = add_card(repos, "HDFC", "Moneyback+")
    add_sub(repos, merchant_name="ChatGPT Plus", amount=Decimal("20"), currency=Currency.USD, payment_method_id=card.id)
    add_push(repos)
    sender = FakeSender()
    run(repos, sender)
    assert sender.calls[0][1]["body"] == "ChatGPT Plus renews in 2 days · $20 · HDFC Moneyback+"


def test_no_card_body(repos):
    add_sub(repos, amount=Decimal("199.50"))
    add_push(repos)
    sender = FakeSender()
    run(repos, sender)
    assert sender.calls[0][1]["body"] == "Netflix renews in 2 days · ₹199.50 · no card"


def test_run_twice_no_duplicate(repos):
    add_sub(repos)
    add_push(repos)
    sender = FakeSender()
    assert run(repos, sender)["sent"] == 1
    assert run(repos, sender) == {"due": 0, "sent": 0, "removed": 0}
    assert len(sender.calls) == 1


def test_gone_subscription_removed(repos):
    add_sub(repos)
    add_push(repos, "https://push.example/gone")
    add_push(repos, "https://push.example/ok")
    sender = FakeSender(fail={"https://push.example/gone": 410})
    assert run(repos, sender) == {"due": 1, "sent": 1, "removed": 1}
    assert [c[0] for c in sender.calls] == ["https://push.example/ok"]
    assert [p.endpoint for p in repos["push"].list()] == ["https://push.example/ok"]


def test_other_errors_logged_and_kept(repos, caplog):
    add_sub(repos)
    add_push(repos)
    sender = FakeSender(error=WebPushException("boom", response=type("R", (), {"status_code": 500})()))
    with caplog.at_level(logging.WARNING, logger="app.reminders"):
        assert run(repos, sender) == {"due": 1, "sent": 0, "removed": 0}
    assert len(repos["push"].list()) == 1
    assert "push failed" in caplog.text


def test_network_error_does_not_abort(repos):
    add_sub(repos)
    add_push(repos)
    assert run(repos, FakeSender(error=ConnectionError("down")))["sent"] == 0


@pytest.mark.parametrize("status", [SubscriptionStatus.paused, SubscriptionStatus.cancelled])
def test_inactive_not_reminded(repos, status):
    add_sub(repos, status=status)
    add_push(repos)
    sender = FakeSender()
    assert run(repos, sender) == {"due": 0, "sent": 0, "removed": 0}
    assert sender.calls == []


# --- HTTP ---


@pytest.fixture
def sender(client):
    fake = FakeSender()
    client.app.dependency_overrides[get_push_sender] = lambda: fake
    client.app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=TEST_DATABASE_URL, cookie_secure=False, scheduler_secret=SECRET, vapid_public_key="PUBKEY"
    )
    return fake


@pytest.fixture
def auth(client, user):
    assert login(client).status_code == 200
    return client


def internal(client, secret=SECRET):
    headers = {} if secret is None else {"X-Scheduler-Secret": secret}
    return client.post("/api/internal/run-reminders", headers=headers)


@pytest.mark.parametrize("secret", [None, "wrong", ""])
def test_secret_required(client, sender, secret):
    r = internal(client, secret)
    assert r.status_code == 403
    assert r.json() == {"detail": "Forbidden"}


def test_internal_needs_no_cookie_or_csrf(client, sender, repos, db, monkeypatch):
    monkeypatch.setattr("app.reminders.router.today_ist", lambda: TODAY)
    add_sub(repos)
    add_push(repos)
    db.commit()
    assert internal(client).json() == {"due": 1, "sent": 1, "removed": 0}


def test_uses_ist_date(client, sender, repos, db, monkeypatch):
    # 2026-11-04T19:00Z is 2026-11-05 00:30 IST, so Nov 7 is due.
    real = __import__("app.shared.billing", fromlist=["today_ist"]).today_ist
    monkeypatch.setattr(
        "app.reminders.router.today_ist", lambda: real(datetime(2026, 11, 4, 19, 0, tzinfo=UTC))
    )
    add_sub(repos, start_date=date(2025, 11, 7))
    add_push(repos)
    db.commit()
    assert internal(client).json()["due"] == 1


def test_push_endpoints_require_auth(client, sender):
    assert client.get("/api/push/public-key").status_code == 401


def test_public_key(auth, sender):
    assert auth.get("/api/push/public-key").json() == {"key": "PUBKEY"}


def sub_body(endpoint="https://push.example/a", **over):
    return {"endpoint": endpoint, "keys": {"p256dh": "p", "auth": "a"}, **over}


def test_subscribe_upserts_and_unsubscribes(auth, sender, repos):
    h = csrf_headers(auth)
    assert auth.post("/api/push/subscribe", json=sub_body(), headers=h).status_code == 204
    r = auth.post("/api/push/subscribe", json={**sub_body(), "keys": {"p256dh": "p2", "auth": "a2"}}, headers=h)
    assert r.status_code == 204
    [row] = repos["push"].list()
    assert (row.p256dh, row.auth) == ("p2", "a2")
    assert auth.post("/api/push/unsubscribe", json={"endpoint": row.endpoint}, headers=h).status_code == 204
    assert auth.post("/api/push/unsubscribe", json={"endpoint": row.endpoint}, headers=h).status_code == 204
    assert repos["push"].list() == []


@pytest.mark.parametrize(
    "payload",
    [
        sub_body("http://push.example/a"),
        sub_body("https://x/" + "a" * 2048),
        {"endpoint": "https://push.example/a", "keys": {"p256dh": "", "auth": "a"}},
        {"endpoint": "https://push.example/a", "keys": {"p256dh": "p", "auth": "a" * 257}},
        {"endpoint": "https://push.example/a"},
    ],
)
def test_subscribe_validation(auth, sender, payload):
    assert auth.post("/api/push/subscribe", json=payload, headers=csrf_headers(auth)).status_code == 422


def test_push_test(auth, sender, repos):
    h = csrf_headers(auth)
    add_push(repos, "https://push.example/gone")
    add_push(repos, "https://push.example/ok")
    sender.fail = {"https://push.example/gone": 404}
    r = auth.post("/api/push/test", headers=h)
    assert r.json() == {"sent": 1, "removed": 1}
    assert sender.calls[0][1]["body"] == "Test notification from Cadence"


def test_default_sender_calls_webpush(monkeypatch, repos):
    from app.reminders import deps

    calls = []
    monkeypatch.setattr(deps, "webpush", lambda **kw: calls.append(kw))
    settings = Settings(
        cookie_secure=False, vapid_private_key="PRIV", vapid_subject="mailto:me@example.com"
    )
    send = get_push_sender(settings)
    push_sub = add_push(repos)
    send(push_sub, {"title": "T"})
    send(push_sub, {"title": "T"})

    [first, second] = calls
    assert first["subscription_info"] == {
        "endpoint": "https://push.example/a",
        "keys": {"p256dh": "p256", "auth": "authkey"},
    }
    assert first["data"] == '{"title": "T"}'
    assert first["vapid_private_key"] == "PRIV"
    assert first["vapid_claims"] == {"sub": "mailto:me@example.com"}
    assert first["vapid_claims"] is not second["vapid_claims"]
    assert first["ttl"] == deps.PUSH_TTL_SECONDS == 86400
    assert first["headers"] == {"Urgency": "normal"}


def test_push_list_loaded_once_per_run(repos, monkeypatch):
    add_sub(repos)
    add_sub(repos, merchant_name="Other")
    add_push(repos, "https://push.example/gone")
    add_push(repos, "https://push.example/ok")
    calls = []
    original = repos["push"].list
    monkeypatch.setattr(repos["push"], "list", lambda: calls.append(1) or original())
    sender = FakeSender(fail={"https://push.example/gone": 410})
    assert run(repos, sender) == {"due": 2, "sent": 2, "removed": 1}
    assert len(calls) == 1
