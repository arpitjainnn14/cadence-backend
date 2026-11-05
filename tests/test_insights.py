from datetime import timedelta
from decimal import Decimal

import pytest

from app.insights.repository import SettingsRepository
from app.insights.service import USD_RATE_KEY, get_usd_rate
from app.payment_methods.repository import PaymentMethodRepository
from app.shared.billing import CYCLE_MONTHS, today_ist
from app.shared.enums import BillingCycle, Currency, PaymentMethodType
from app.subscriptions.repository import SubscriptionRepository
from app.subscriptions.merchants import resolve_domain
from tests.conftest import csrf_headers, login

M, Q, Y = BillingCycle.monthly, BillingCycle.quarterly, BillingCycle.yearly
INR, USD = Currency.INR, Currency.USD

# (name, amount, currency, cycle, category)
SAMPLE = [
    ("Netflix", "649", INR, M, "Streaming"),
    ("Spotify", "119", INR, M, "Music"),
    ("YouTube", "149", INR, M, "Streaming"),
    ("Prime", "1499", INR, Y, "Shopping"),
    ("iCloud", "75", INR, M, "Cloud storage"),
    ("ChatGPT", "20", USD, M, "Software/AI"),
    ("cult", "1299", INR, M, "Fitness"),
    ("Swiggy", "899", INR, Q, "Food delivery"),
    ("Zomato", "299", INR, Q, "Food delivery"),
    ("Notion", "10", USD, M, "Software/AI"),
]


@pytest.fixture
def auth(client, user):
    assert login(client).status_code == 200
    return client


def add(db, name, amount, currency=INR, cycle=M, category="Other", status="active", pm=None, start=None):
    sub = SubscriptionRepository(db).add(
        merchant_name=name, merchant_domain=resolve_domain(name), amount=Decimal(amount), currency=currency, billing_cycle=cycle,
        start_date=start or today_ist(), category=category, status=status, payment_method_id=pm,
    )
    db.commit()
    return sub


def seed(db, rows=SAMPLE):
    return [add(db, n, a, c, cy, cat) for n, a, c, cy, cat in rows]


def expected_monthly(rows=SAMPLE, rate=Decimal("88")):
    total = sum(
        (Decimal(a) * (rate if c == USD else 1) / CYCLE_MONTHS[cy] for _, a, c, cy, _ in rows), Decimal(0)
    )
    return total.quantize(Decimal("0.01"))


def get(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text
    return r.json()


# --- settings ---


def test_settings_default_and_put(auth):
    assert get(auth, "/api/settings") == {"usd_inr_rate": "88.00"}
    r = auth.put("/api/settings", json={"usd_inr_rate": "83.5"}, headers=csrf_headers(auth))
    assert r.status_code == 200 and r.json() == {"usd_inr_rate": "83.50"}
    assert get(auth, "/api/settings") == {"usd_inr_rate": "83.50"}
    r = auth.put("/api/settings", json={"usd_inr_rate": 84.1234}, headers=csrf_headers(auth))
    assert r.json() == {"usd_inr_rate": "84.1234"}


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "NaN", "Infinity", "10000.01", "1.23456", None, ""])
def test_settings_rejects_invalid_rate(auth, bad):
    r = auth.put("/api/settings", json={"usd_inr_rate": bad}, headers=csrf_headers(auth))
    assert r.status_code == 422
    assert get(auth, "/api/settings") == {"usd_inr_rate": "88.00"}


def test_settings_requires_auth_and_csrf(client, user):
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/insights").status_code == 401
    assert login(client).status_code == 200
    assert client.put("/api/settings", json={"usd_inr_rate": "90"}).status_code == 403


@pytest.mark.parametrize("stored", ["garbage", "NaN", "Infinity", "-5", "0", "99999999", ""])
def test_get_usd_rate_falls_back_when_stored_value_malformed(db, stored):
    repo = SettingsRepository(db)
    repo.set(USD_RATE_KEY, stored)
    assert get_usd_rate(repo) == Decimal("88")


# --- summary ---


def test_summary_sample_totals(auth, db):
    seed(db)
    s = get(auth, "/api/summary")
    monthly = expected_monthly()
    assert monthly == Decimal("5455.25")
    assert s["monthly"] == "5455.25"
    assert s["approx"] is True
    # Rounded once from the unrounded sum, not 6x / 12x the rounded monthly.
    exact = sum(
        (Decimal(a) * (88 if c == USD else 1) / CYCLE_MONTHS[cy] for _, a, c, cy, _ in SAMPLE), Decimal(0)
    )
    assert s["half_yearly"] == str((exact * 6).quantize(Decimal("0.01")))
    assert s["yearly"] == str((exact * 12).quantize(Decimal("0.01")))


def test_summary_quarterly_sub_is_prorated_from_unrounded_monthly(auth, db):
    add(db, "Quarterly", "100", INR, Q)
    s = get(auth, "/api/summary")
    assert (s["monthly"], s["half_yearly"], s["yearly"]) == ("33.33", "200.00", "400.00")


def test_summary_no_usd_not_approx(auth, db):
    seed(db, [r for r in SAMPLE if r[2] == INR])
    assert get(auth, "/api/summary")["approx"] is False


def test_summary_empty(auth):
    assert get(auth, "/api/summary") == {
        "monthly": "0.00", "half_yearly": "0.00", "yearly": "0.00", "approx": False, "upcoming": [],
    }


def test_paused_and_cancelled_excluded_everywhere(auth, db):
    seed(db, SAMPLE[:2])
    add(db, "Paused", "1000", status="paused", category="Fitness")
    add(db, "Gone", "1000", status="cancelled", category="Fitness")
    s = get(auth, "/api/summary")
    assert s["monthly"] == "768.00"
    assert {u["merchant_name"] for u in s["upcoming"]} == {"Netflix", "Spotify"}
    ins = get(auth, "/api/insights")
    assert {c["category"] for c in ins["by_category"]} == {"Streaming", "Music"}
    assert {m["merchant_name"] for m in ins["most_expensive"]} == {"Netflix", "Spotify"}


def test_paused_usd_does_not_make_approx(auth, db):
    add(db, "Netflix", "649")
    add(db, "Paused USD", "10", currency=USD, status="paused")
    assert get(auth, "/api/summary")["approx"] is False
    assert get(auth, "/api/insights")["approx"] is False


def test_rate_change_changes_totals(auth, db):
    seed(db)
    assert auth.put("/api/settings", json={"usd_inr_rate": "100"}, headers=csrf_headers(auth)).status_code == 200
    s = get(auth, "/api/summary")
    assert s["monthly"] == str(expected_monthly(rate=Decimal("100")))
    assert s["monthly"] != "5455.25"


def test_upcoming_item_shape_and_days_until(auth, db):
    pm = PaymentMethodRepository(db).add(PaymentMethodType.credit_card, "ICICI", "Sapphiro", None)
    db.commit()
    today = today_ist()
    sub = add(db, "Netflix", "649", pm=pm.id, start=today)
    u = get(auth, "/api/summary")["upcoming"]
    assert u == [{
        "subscription_id": str(sub.id), "merchant_name": "Netflix",
        "logo_url": u[0]["logo_url"], "amount": "649.00", "currency": "INR", "amount_inr": "649.00",
        "renewal_date": today.isoformat(), "days_until": 0,
        "payment_method": {"id": str(pm.id), "name": "ICICI Sapphiro", "has_image": False},
    }]
    assert u[0]["logo_url"] and "netflix.com" in u[0]["logo_url"]


def test_upcoming_order_limit_and_null_payment_method(auth, db):
    today = today_ist()
    for i in range(22):
        add(db, f"Sub{i:02d}", "10", start=today + timedelta(days=i % 30 + 1))
    add(db, "Zed", "10", start=today)
    add(db, "Abe", "10", start=today)
    u = get(auth, "/api/summary")["upcoming"]
    assert len(u) == 20
    assert [x["merchant_name"] for x in u[:2]] == ["Abe", "Zed"]  # same date: tie-break by name
    assert [x["renewal_date"] for x in u] == sorted(x["renewal_date"] for x in u)
    assert u[0]["payment_method"] is None
    assert all(x["days_until"] >= 0 for x in u)


def test_upcoming_usd_amount_inr(auth, db):
    add(db, "ChatGPT", "20", currency=USD)
    u = get(auth, "/api/summary")["upcoming"][0]
    assert (u["amount"], u["currency"], u["amount_inr"]) == ("20.00", "USD", "1760.00")


# --- insights ---


def test_insights_by_category_sums_to_monthly(auth, db):
    seed(db)
    ins = get(auth, "/api/insights?period=monthly")
    cats = ins["by_category"]
    amounts = [Decimal(c["amount"]) for c in cats]
    assert amounts == sorted(amounts, reverse=True)
    assert abs(sum(amounts) - expected_monthly()) <= Decimal("0.01") * len(cats)
    food = next(c for c in cats if c["category"] == "Food delivery")
    assert food["amount"] == "399.33" and len(food["subscription_ids"]) == 2
    assert ins["approx"] is True


def test_insights_yearly_is_twelve_times_unrounded(auth, db):
    seed(db)
    cats = {c["category"]: c["amount"] for c in get(auth, "/api/insights?period=yearly")["by_category"]}
    assert cats["Food delivery"] == "4792.00"  # (899+299)/3*12, rounded once
    assert cats["Shopping"] == "1499.00"


def test_insights_default_period_is_monthly_and_invalid_422(auth, db):
    seed(db, SAMPLE[:1])
    assert get(auth, "/api/insights")["by_category"][0]["amount"] == "649.00"
    assert auth.get("/api/insights?period=weekly").status_code == 422


def test_insights_by_payment_method(auth, db):
    pms = PaymentMethodRepository(db)
    card = pms.add(PaymentMethodType.credit_card, "HDFC", "Regalia", None)
    upi = pms.add(PaymentMethodType.upi, "Paytm", "UPI", None)
    db.commit()
    add(db, "A", "500", pm=card.id)
    add(db, "B", "300", pm=upi.id)
    add(db, "C", "100")
    add(db, "D", "100", pm=upi.id)
    groups = get(auth, "/api/insights")["by_payment_method"]
    assert [(g["payment_method_id"], g["name"], g["amount"]) for g in groups] == [
        (str(card.id), "HDFC Regalia", "500.00"),
        (str(upi.id), "Paytm UPI", "400.00"),
        (None, "Unassigned", "100.00"),
    ]
    assert len(groups[1]["subscription_ids"]) == 2


def test_insights_most_expensive_top_10_by_yearly(auth, db):
    for i in range(12):
        add(db, f"S{i:02d}", str(100 + i))
    add(db, "Annual", "1500", cycle=Y)  # 1500/yr outranks the priciest monthly (111 -> 1332/yr)
    top = get(auth, "/api/insights")["most_expensive"]
    assert len(top) == 10
    yearly = [Decimal(t["yearly_inr"]) for t in top]
    assert yearly == sorted(yearly, reverse=True)
    assert top[0]["merchant_name"] == "Annual" and top[0]["yearly_inr"] == "1500.00"
    assert top[1]["yearly_inr"] == "1332.00"
