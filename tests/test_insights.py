from datetime import timedelta
from decimal import Decimal

import pytest

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
        billing_anchor_date=start or today_ist(), category=category, status=status, payment_method_id=pm,
    )
    db.commit()
    return sub


def seed(db, rows=SAMPLE):
    return [add(db, n, a, c, cy, cat) for n, a, c, cy, cat in rows]


def expected_monthly(rows=SAMPLE, currency=INR):
    total = sum((Decimal(a) / CYCLE_MONTHS[cy] for _, a, c, cy, _ in rows if c == currency), Decimal(0))
    return total.quantize(Decimal("0.01"))


def get(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text
    return r.json()


# --- auth / removed settings ---


def test_requires_auth(client, user):
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/insights").status_code == 401


def test_settings_unknown_rate_field_does_not_set_anything(auth):
    """The old USD-rate setting is gone: only the budget is accepted."""
    assert auth.put("/api/settings", json={"usd_inr_rate": "90"}, headers=csrf_headers(auth)).status_code == 422


# --- summary ---


def test_summary_sample_totals(auth, db):
    seed(db)
    s = get(auth, "/api/summary")
    assert expected_monthly() == Decimal("2815.25")
    assert (s["monthly"], s["half_yearly"], s["yearly"]) == ("2815.25", "16891.50", "33783.00")
    assert s["usd"] == {"monthly": "30.00", "half_yearly": "180.00", "yearly": "360.00"}
    assert "approx" not in s


def test_summary_quarterly_sub_is_prorated_from_unrounded_monthly(auth, db):
    add(db, "Quarterly", "100", INR, Q)
    s = get(auth, "/api/summary")
    assert (s["monthly"], s["half_yearly"], s["yearly"]) == ("33.33", "200.00", "400.00")


def test_summary_usd_null_without_usd_subs(auth, db):
    seed(db, [r for r in SAMPLE if r[2] == INR])
    s = get(auth, "/api/summary")
    assert s["usd"] is None and s["monthly"] == "2815.25"


def test_summary_usd_only(auth, db):
    add(db, "Notion", "10", currency=USD)
    s = get(auth, "/api/summary")
    assert (s["monthly"], s["half_yearly"], s["yearly"]) == ("0.00", "0.00", "0.00")
    assert s["usd"] == {"monthly": "10.00", "half_yearly": "60.00", "yearly": "120.00"}


def test_summary_empty(auth):
    assert get(auth, "/api/summary") == {
        "monthly": "0.00", "half_yearly": "0.00", "yearly": "0.00", "usd": None, "budget": None, "upcoming": [],
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


def test_paused_usd_excluded_from_usd_totals(auth, db):
    add(db, "Netflix", "649")
    add(db, "Paused USD", "10", currency=USD, status="paused")
    assert get(auth, "/api/summary")["usd"] is None
    assert get(auth, "/api/insights")["usd_subscriptions"] == []


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


def test_upcoming_usd_amount_inr_is_null(auth, db):
    add(db, "ChatGPT", "20", currency=USD)
    u = get(auth, "/api/summary")["upcoming"][0]
    assert (u["amount"], u["currency"], u["amount_inr"]) == ("20.00", "USD", None)


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
    assert "Software/AI" not in {c["category"] for c in cats}  # USD subs are not in the INR charts
    assert "approx" not in ins


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


def test_insights_inr_only_and_usd_listed_separately(auth, db):
    seed(db)
    ins = get(auth, "/api/insights?period=yearly")
    assert {m["merchant_name"] for m in ins["most_expensive"]} == {n for n, _, c, _, _ in SAMPLE if c == INR}
    assert sum(len(g["subscription_ids"]) for g in ins["by_payment_method"]) == 8
    assert ins["usd_subscriptions"] == [
        {"subscription_id": ins["usd_subscriptions"][0]["subscription_id"], "merchant_name": "ChatGPT", "yearly_amount": "240.00"},
        {"subscription_id": ins["usd_subscriptions"][1]["subscription_id"], "merchant_name": "Notion", "yearly_amount": "120.00"},
    ]


def test_insights_usd_subscriptions_empty_without_usd(auth, db):
    seed(db, SAMPLE[:1])
    assert get(auth, "/api/insights")["usd_subscriptions"] == []


# --- settings and budget ---

SETTINGS = "/api/settings"


def put_budget(client, value):
    return client.put(SETTINGS, json={"monthly_budget_inr": value}, headers=csrf_headers(client))


def test_settings_require_auth_and_csrf(client, user):
    assert client.get(SETTINGS).status_code == 401
    assert client.put(SETTINGS, json={"monthly_budget_inr": "1"}).status_code in (401, 403)
    login(client)
    assert client.put(SETTINGS, json={"monthly_budget_inr": "1"}, headers={"X-CSRF-Token": "bad"}).status_code == 403


def test_budget_set_get_clear(auth):
    assert get(auth, SETTINGS) == {"monthly_budget_inr": None}
    r = put_budget(auth, "3000")
    assert (r.status_code, r.json()) == (200, {"monthly_budget_inr": "3000.00"})
    assert get(auth, SETTINGS) == {"monthly_budget_inr": "3000.00"}
    assert put_budget(auth, "1234.5").json() == {"monthly_budget_inr": "1234.50"}
    assert put_budget(auth, None).json() == {"monthly_budget_inr": None}
    assert get(auth, SETTINGS) == {"monthly_budget_inr": None}
    assert put_budget(auth, None).status_code == 200  # clearing an unset budget is fine


@pytest.mark.parametrize("value", ["0", "-5", "10000000.01", "1.234", "abc", "NaN", "Infinity", ""])
def test_budget_validation_422(auth, value):
    assert put_budget(auth, value).status_code == 422


def test_budget_upper_bound_allowed_and_body_required(auth):
    assert put_budget(auth, "10000000").json() == {"monthly_budget_inr": "10000000.00"}
    assert auth.put(SETTINGS, json={}, headers=csrf_headers(auth)).status_code == 422


def test_summary_budget_null_when_unset(auth, db):
    seed(db)
    assert get(auth, "/api/summary")["budget"] is None


def test_summary_budget_maths(auth, db):
    add(db, "A", "1000")
    add(db, "B", "500", USD)  # not counted
    put_budget(auth, "3000")
    assert get(auth, "/api/summary")["budget"] == {
        "monthly": "3000.00", "used": "1000.00", "remaining": "2000.00", "percent_used": 33, "over": False,
    }


def test_summary_budget_percent_rounds_half_up(auth, db):
    add(db, "A", "1")
    put_budget(auth, "200")  # 0.5% -> 1
    assert get(auth, "/api/summary")["budget"]["percent_used"] == 1
    put_budget(auth, "8")  # 12.5% -> 13
    assert get(auth, "/api/summary")["budget"]["percent_used"] == 13


def test_summary_budget_over(auth, db):
    add(db, "A", "4500")
    put_budget(auth, "3000")
    assert get(auth, "/api/summary")["budget"] == {
        "monthly": "3000.00", "used": "4500.00", "remaining": "-1500.00", "percent_used": 150, "over": True,
    }


def test_summary_budget_exactly_used_is_not_over(auth, db):
    add(db, "A", "3000")
    put_budget(auth, "3000")
    b = get(auth, "/api/summary")["budget"]
    assert (b["remaining"], b["percent_used"], b["over"]) == ("0.00", 100, False)


@pytest.mark.parametrize("stored", ["garbage", "-1", "0", "NaN", "Infinity", "99999999999"])
def test_malformed_stored_budget_is_treated_as_unset(auth, db, stored):
    from app.insights.repository import SettingsRepository

    SettingsRepository(db).set("monthly_budget_inr", stored)
    db.commit()
    assert get(auth, SETTINGS) == {"monthly_budget_inr": None}
    assert get(auth, "/api/summary")["budget"] is None
