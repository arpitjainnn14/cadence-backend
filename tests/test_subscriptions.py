import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.payment_methods.repository import PaymentMethodRepository
from app.shared.billing import today_ist
from app.shared.enums import BillingCycle, Currency, PaymentMethodType, SubscriptionStatus
from app.subscriptions import merchants
from app.subscriptions.repository import SubscriptionRepository
from tests.conftest import csrf_headers, login

URL = "/api/subscriptions"


@pytest.fixture
def auth(client, user):
    assert login(client).status_code == 200
    return client


def body(**over):
    data = {
        "merchant_name": "Netflix",
        "amount": "649.00",
        "currency": "INR",
        "billing_cycle": "monthly",
        "next_billing_date": (today_ist() + timedelta(days=10)).isoformat(),
        "category": "Streaming",
        "status": "active",
        **over,
    }
    return {k: v for k, v in data.items() if v is not Ellipsis}


def create(client, **over):
    return client.post(URL, json=body(**over), headers=csrf_headers(client))


# --- merchants ---


@pytest.mark.parametrize(
    "name, domain",
    [
        ("Netflix", "netflix.com"),
        ("  NETFLIX!! ", "netflix.com"),
        ("Amazon Prime Video", "primevideo.com"),
        ("YouTube Premium Family", "youtube.com"),
        ("iCloud+", "apple.com"),
        ("Cult.fit", "cult.fit"),
        ("JioHotstar", "hotstar.com"),
        ("ChatGPT Plus", "openai.com"),
        ("Corner Gym", None),
        ("", None),
    ],
)
def test_resolve_domain(name, domain):
    assert merchants.resolve_domain(name) == domain


def test_known_merchants_cover_brief():
    for key in ("netflix", "spotify", "notion", "audible", "zee5", "sonyliv", "swiggy one", "zomato gold",
                "google one", "linkedin premium", "apple", "prime video", "amazon prime", "cult", "hotstar"):
        assert key in merchants.KNOWN_MERCHANTS


def test_logo_url():
    assert merchants.logo_url("netflix.com") == "https://www.google.com/s2/favicons?domain=netflix.com&sz=128"


def test_resolve_endpoint(auth):
    r = auth.get("/api/merchants/resolve", params={"name": "Spotify Premium"})
    assert r.json() == {"domain": "spotify.com", "logo_url": merchants.logo_url("spotify.com")}
    assert auth.get("/api/merchants/resolve", params={"name": "Nope"}).json() == {"domain": None, "logo_url": None}


def test_resolve_name_too_long_422(auth):
    assert auth.get("/api/merchants/resolve", params={"name": "x" * 81}).status_code == 422
    assert auth.get("/api/merchants/resolve", params={"name": "x" * 80}).status_code == 200


def test_unknown_category_filter_422(auth):
    assert auth.get(URL, params={"category": "Bogus"}).status_code == 422
    assert auth.get(URL, params={"category": "News"}).status_code == 200


@pytest.mark.parametrize("sort", ["name", "renewal", "cost"])
def test_sort_ties_broken_by_id(auth, sort):
    for _ in range(4):
        assert create(auth, merchant_name="Same").status_code == 201
    ids = [s["id"] for s in auth.get(URL, params={"sort": sort}).json()]
    assert ids == sorted(ids)


# --- repository ---


def test_amount_check_constraint_rejects_zero(db):
    from sqlalchemy.exc import IntegrityError

    repo = SubscriptionRepository(db)
    fields = dict(
        merchant_name="Zero", merchant_domain=None, amount=Decimal("0"), currency=Currency.INR,
        billing_cycle=BillingCycle.monthly, billing_anchor_date=date(2026, 1, 1), payment_method_id=None,
        category="Other", notes=None, status=SubscriptionStatus.active,
    )
    with pytest.raises(IntegrityError):
        repo.add(**fields)


def test_repo_crud_and_filters(db):
    pm = PaymentMethodRepository(db).add(PaymentMethodType.upi, "Paytm", "UPI", None)
    repo = SubscriptionRepository(db)
    fields = dict(
        merchant_domain=None, amount=Decimal("10"), currency=Currency.INR, billing_cycle=BillingCycle.monthly,
        billing_anchor_date=date(2026, 1, 1), payment_method_id=None, category="Other", notes=None,
        status=SubscriptionStatus.active, cancelled_at=None,
    )
    a = repo.add(merchant_name="A", **fields)
    b = repo.add(merchant_name="B", **{**fields, "status": SubscriptionStatus.paused, "payment_method_id": pm.id})
    c = repo.add(merchant_name="C", **{**fields, "category": "News"})
    assert repo.get(a.id) is a
    assert repo.get(uuid.uuid4()) is None
    assert {s.id for s in repo.list()} == {a.id, b.id, c.id}
    assert [s.id for s in repo.list(status=SubscriptionStatus.paused)] == [b.id]
    assert [s.id for s in repo.list(payment_method_id=pm.id)] == [b.id]
    assert [s.id for s in repo.list(category="News")] == [c.id]
    repo.update(a, {"merchant_name": "A2"})
    assert repo.get(a.id).merchant_name == "A2"
    repo.delete(a)
    assert repo.get(a.id) is None


# --- API ---


def test_requires_auth(client):
    assert client.get(URL).status_code == 401
    assert create(client).status_code == 401
    assert client.get("/api/merchants/resolve", params={"name": "x"}).status_code == 401


def test_create_netflix_fills_domain_and_logo(auth):
    r = create(auth)
    assert r.status_code == 201
    out = r.json()
    assert out["merchant_domain"] == "netflix.com"
    assert "netflix.com" in out["logo_url"]
    assert out["amount_inr"] == "649.00"
    assert out["yearly_inr"] == "7788.00" and out["yearly_amount"] == "7788.00"
    assert out["cancelled_at"] is None and out["created_at"]
    assert date.fromisoformat(out["next_renewal"]) >= date(2026, 1, 15)


def test_unknown_merchant_has_null_logo(auth):
    out = create(auth, merchant_name="Corner Gym").json()
    assert out["logo_url"] is None and out["merchant_domain"] is None


def test_explicit_domain_kept_and_validated(auth):
    out = create(auth, merchant_name="Netflix", merchant_domain="Example.COM").json()
    assert out["merchant_domain"] == "example.com"
    assert create(auth, merchant_domain="not a host").status_code == 422
    assert create(auth, merchant_domain="http://x.com/").status_code == 422


def test_yearly_inr_math(auth):
    assert create(auth, merchant_name="Y", amount="1499", billing_cycle="yearly").json()["yearly_inr"] == "1499.00"
    assert create(auth, merchant_name="Q", amount="899", billing_cycle="quarterly").json()["yearly_inr"] == "3596.00"


def test_sort_cost_orders_by_yearly(auth):
    create(auth, merchant_name="Yearly", amount="1499", billing_cycle="yearly")
    create(auth, merchant_name="Monthly", amount="649")
    names = [s["merchant_name"] for s in auth.get(URL, params={"sort": "cost"}).json()]
    assert names == ["Monthly", "Yearly"]


def test_sort_cost_inr_first_then_usd_each_by_yearly_desc_then_name(auth):
    create(auth, merchant_name="Small INR", amount="10")  # 120/yr
    create(auth, merchant_name="Big USD", amount="500", currency="USD")  # 6000/yr: more than any INR, still last
    create(auth, merchant_name="Big INR", amount="100")  # 1200/yr
    create(auth, merchant_name="Small USD", amount="5", currency="USD")  # 60/yr
    create(auth, merchant_name="b tie", amount="10")  # ties with Small INR; name decides
    create(auth, merchant_name="a tie", amount="10")
    names = [s["merchant_name"] for s in auth.get(URL, params={"sort": "cost"}).json()]
    assert names == ["Big INR", "a tie", "b tie", "Small INR", "Big USD", "Small USD"]


def test_sort_name_and_renewal(auth):
    create(auth, merchant_name="b", next_billing_date=(today_ist() + timedelta(days=20)).isoformat())
    create(auth, merchant_name="a", next_billing_date=(today_ist() + timedelta(days=25)).isoformat())
    assert [s["merchant_name"] for s in auth.get(URL, params={"sort": "name"}).json()] == ["a", "b"]
    renewals = [s["next_renewal"] for s in auth.get(URL, params={"sort": "renewal"}).json()]
    assert renewals == sorted(renewals)
    assert auth.get(URL, params={"sort": "bogus"}).status_code == 422


def test_filters(auth):
    create(auth, merchant_name="A")
    create(auth, merchant_name="B", status="paused", category="News")
    assert [s["merchant_name"] for s in auth.get(URL, params={"status": "paused"}).json()] == ["B"]
    assert [s["merchant_name"] for s in auth.get(URL, params={"category": "News"}).json()] == ["B"]
    pm = auth.post("/api/payment-methods", data={"type": "upi", "name": "UPI"}, headers=csrf_headers(auth)).json()
    create(auth, merchant_name="C", payment_method_id=pm["id"])
    assert [s["merchant_name"] for s in auth.get(URL, params={"payment_method_id": pm["id"]}).json()] == ["C"]


@pytest.mark.parametrize(
    "over",
    [
        {"amount": "0"},
        {"amount": "-5"},
        {"category": "Bogus"},
        {"merchant_name": ""},
        {"merchant_name": "x" * 81},
        {"notes": "x" * 501},
        {"currency": "EUR"},
    ],
)
def test_validation_422(auth, over):
    assert create(auth, **over).status_code == 422


def test_unknown_payment_method_422(auth):
    r = create(auth, payment_method_id=str(uuid.uuid4()))
    assert r.status_code == 422
    assert r.json() == {"detail": "Unknown payment method"}


def test_inactive_payment_method_allowed(auth):
    pm = auth.post("/api/payment-methods", data={"type": "upi", "name": "UPI"}, headers=csrf_headers(auth)).json()
    auth.patch(f"/api/payment-methods/{pm['id']}", json={"is_active": False}, headers=csrf_headers(auth))
    assert create(auth, payment_method_id=pm["id"]).status_code == 201


def test_usd_sub_has_no_inr_conversion(auth):
    out = create(auth, merchant_name="Notion", amount="10", currency="USD").json()
    assert (out["amount"], out["yearly_amount"]) == ("10.00", "120.00")
    assert out["amount_inr"] is None and out["yearly_inr"] is None
    got = auth.get(f"{URL}/{out['id']}").json()
    assert got["amount_inr"] is None and got["yearly_inr"] is None and got["yearly_amount"] == "120.00"
    listed = auth.get(URL).json()[0]
    assert listed["amount_inr"] is None and listed["yearly_amount"] == "120.00"


def test_yearly_amount_is_own_currency(auth):
    out = create(auth, merchant_name="Q", amount="10.01", currency="USD", billing_cycle="quarterly").json()
    assert out["yearly_amount"] == "40.04" and out["yearly_inr"] is None


def test_get_put_delete_and_404(auth):
    sub = create(auth).json()
    assert auth.get(f"{URL}/{sub['id']}").json()["id"] == sub["id"]
    r = auth.put(f"{URL}/{sub['id']}", json=body(merchant_name="Spotify", amount="119"), headers=csrf_headers(auth))
    assert r.status_code == 200
    assert r.json()["merchant_name"] == "Spotify" and r.json()["merchant_domain"] == "spotify.com"
    assert auth.delete(f"{URL}/{sub['id']}", headers=csrf_headers(auth)).status_code == 204
    missing = uuid.uuid4()
    for resp in (
        auth.get(f"{URL}/{missing}"),
        auth.put(f"{URL}/{missing}", json=body(), headers=csrf_headers(auth)),
        auth.delete(f"{URL}/{missing}", headers=csrf_headers(auth)),
    ):
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Subscription not found"}


def test_put_is_full_replace_domain_refilled(auth):
    sub = create(auth, merchant_domain="custom.example").json()
    r = auth.put(f"{URL}/{sub['id']}", json=body(), headers=csrf_headers(auth)).json()
    assert r["merchant_domain"] == "netflix.com"


def test_rename_with_echoed_domain_re_resolves(auth):
    sub = create(auth).json()  # Netflix -> netflix.com
    echoed = body(merchant_name="Spotify", merchant_domain=sub["merchant_domain"])
    r = auth.put(f"{URL}/{sub['id']}", json=echoed, headers=csrf_headers(auth)).json()
    assert r["merchant_domain"] == "spotify.com"
    # An unknown new name clears the stale domain rather than keeping netflix.com.
    echoed = body(merchant_name="Local Gym", merchant_domain="spotify.com")
    r = auth.put(f"{URL}/{sub['id']}", json=echoed, headers=csrf_headers(auth)).json()
    assert r["merchant_domain"] is None and r["logo_url"] is None


def test_rename_with_explicit_domain_keeps_it(auth):
    sub = create(auth).json()
    r = auth.put(
        f"{URL}/{sub['id']}", json=body(merchant_name="Spotify", merchant_domain="custom.example"), headers=csrf_headers(auth)
    ).json()
    assert r["merchant_domain"] == "custom.example"


def test_edit_without_rename_keeps_custom_domain(auth):
    sub = create(auth, merchant_domain="custom.example").json()
    r = auth.put(
        f"{URL}/{sub['id']}", json=body(merchant_domain="custom.example", amount="700"), headers=csrf_headers(auth)
    ).json()
    assert r["merchant_domain"] == "custom.example"


def test_cancel_sets_and_reactivate_clears_cancelled_at(auth):
    sub = create(auth).json()
    url = f"{URL}/{sub['id']}"
    cancelled = auth.put(url, json=body(status="cancelled"), headers=csrf_headers(auth)).json()
    assert cancelled["status"] == "cancelled" and cancelled["cancelled_at"]
    again = auth.put(url, json=body(status="cancelled", notes="n"), headers=csrf_headers(auth)).json()
    assert again["cancelled_at"] == cancelled["cancelled_at"]
    back = auth.put(url, json=body(status="active"), headers=csrf_headers(auth)).json()
    assert back["cancelled_at"] is None
    assert create(auth, status="cancelled").json()["cancelled_at"]


def test_mutations_need_csrf(auth):
    assert auth.post(URL, json=body()).status_code == 403


# --- billing dates with a pinned "today" ---

PINNED = date(2027, 2, 10)


@pytest.fixture
def pinned_today(monkeypatch):
    """Pin the router's today_ist so date rules and next_renewal are deterministic."""
    monkeypatch.setattr("app.subscriptions.router.today_ist", lambda: PINNED)
    return PINNED


def test_pinned_post_past_next_billing_date_422(auth, pinned_today):
    r = create(auth, next_billing_date="2027-02-09")
    assert (r.status_code, r.json()["detail"]) == (422, "Next billing date can't be in the past")
    assert create(auth, next_billing_date="2027-02-10").status_code == 201


def test_pinned_post_future_started_on_422(auth, pinned_today):
    r = create(auth, next_billing_date="2027-03-01", started_on="2027-02-11")
    assert (r.status_code, r.json()["detail"]) == (422, "Started on can't be in the future")
    assert create(auth, next_billing_date="2027-03-01", started_on="2027-02-10").status_code == 201


def test_pinned_put_without_next_billing_date_keeps_jan_31_anchor(auth, db, pinned_today):
    sub = SubscriptionRepository(db).add(
        merchant_name="Gym", merchant_domain=None, amount=Decimal("10"), currency=Currency.INR,
        billing_cycle=BillingCycle.monthly, billing_anchor_date=date(2027, 1, 31), started_on=None,
        payment_method_id=None, category="Other", notes=None, status=SubscriptionStatus.active,
    )
    db.commit()
    url = f"{URL}/{sub.id}"
    for over in ({"next_billing_date": ...}, {"next_billing_date": None}):
        r = auth.put(url, json=body(merchant_name="Gym", **over), headers=csrf_headers(auth))
        assert r.status_code == 200
        assert r.json()["next_renewal"] == "2027-02-28"  # Feb clamp, anchor still the 31st
    db.expire_all()
    assert sub.billing_anchor_date == date(2027, 1, 31)
    from app.shared.billing import next_renewal

    assert next_renewal(sub.billing_anchor_date, BillingCycle.monthly, date(2027, 3, 1)) == date(2027, 3, 31)


def test_pinned_put_with_new_date_moves_anchor(auth, pinned_today):
    sub = create(auth, next_billing_date="2027-03-20").json()
    r = auth.put(f"{URL}/{sub['id']}", json=body(next_billing_date="2027-02-15"), headers=csrf_headers(auth))
    assert r.json()["next_renewal"] == "2027-02-15"


def test_put_omitting_started_on_clears_it(auth):
    sub = create(auth, started_on="2024-03-05").json()
    assert sub["started_on"] == "2024-03-05"
    r = auth.put(f"{URL}/{sub['id']}", json=body(), headers=csrf_headers(auth))
    assert r.json()["started_on"] is None  # PUT is a full replace of the other fields
