import uuid

import pytest

from app.payment_methods.repository import PaymentMethodRepository
from app.shared.enums import CardNetwork, PaymentMethodType
from tests.conftest import csrf_headers, login

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
MAX = 2 * 1024 * 1024
URL = "/api/payment-methods"


@pytest.fixture
def auth(client, user):
    assert login(client).status_code == 200
    return client


def create(client, image=None, **over):
    data = {"type": "credit_card", "bank": "HDFC", "name": "Regalia", "network": "visa", **over}
    data = {k: v for k, v in data.items() if v is not None}
    files = {"image": ("art", image[0], image[1])} if image else None
    return client.post(URL, data=data, files=files, headers=csrf_headers(client))


# --- repository ---


def test_repo_list_orders_and_filters(db):
    repo = PaymentMethodRepository(db)
    repo.add(PaymentMethodType.other, None, "Cash", None)
    repo.add(PaymentMethodType.upi, "Paytm", "UPI", None)
    repo.add(PaymentMethodType.credit_card, "SBI", "Elite", CardNetwork.visa)
    repo.add(PaymentMethodType.credit_card, "HDFC", "Regalia", CardNetwork.visa)
    repo.add(PaymentMethodType.credit_card, None, "Zeta", CardNetwork.rupay)
    off = repo.add(PaymentMethodType.credit_card, "AXIS", "Old", CardNetwork.visa)
    off.is_active = False
    assert [m.name for m in repo.list(include_inactive=False)] == ["Regalia", "Elite", "Zeta", "UPI", "Cash"]
    assert len(repo.list(include_inactive=True)) == 6
    assert repo.get(off.id) is off
    assert repo.get(uuid.uuid4()) is None


# --- API ---


def test_requires_auth(client):
    assert client.get(URL).status_code == 401
    assert create(client).status_code == 401
    assert client.get(f"{URL}/{uuid.uuid4()}/image").status_code == 401


def test_create_with_image_and_fetch_it(auth):
    r = create(auth, image=(PNG, "image/png"))
    assert r.status_code == 201
    body = r.json()
    assert body["has_image"] is True and body["display_name"] == "HDFC Regalia"
    assert set(body) == {"id", "type", "bank", "name", "network", "display_name", "color", "has_image", "is_active"}
    img = auth.get(f"{URL}/{body['id']}/image")
    assert img.status_code == 200 and img.content == PNG
    assert img.headers["content-type"] == "image/png"
    assert img.headers["cache-control"] == "private, max-age=86400"
    assert img.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("data,mime", [(JPEG, "image/jpeg"), (WEBP, "image/webp")])
def test_mime_is_sniffed_not_trusted(auth, data, mime):
    pm = create(auth, image=(data, "image/png")).json()
    assert auth.get(f"{URL}/{pm['id']}/image").headers["content-type"] == mime


def test_gif_rejected(auth):
    assert create(auth, image=(GIF, "image/gif")).status_code == 422
    assert create(auth, image=(GIF, "image/png")).status_code == 422  # lying content-type
    assert auth.get(URL).json() == []


def test_oversize_rejected_and_limit_inclusive(auth):
    assert create(auth, image=(PNG + b"\x00" * (MAX - len(PNG) + 1), "image/png")).status_code == 422
    assert create(auth, image=(PNG + b"\x00" * (MAX - len(PNG)), "image/png")).status_code == 201


def test_no_image_is_404(auth):
    pm = create(auth).json()
    assert pm["has_image"] is False
    r = auth.get(f"{URL}/{pm['id']}/image")
    assert r.status_code == 404 and r.json() == {"detail": "Image not found"}


def test_put_image_replaces(auth):
    pm = create(auth, image=(PNG, "image/png")).json()
    r = auth.put(f"{URL}/{pm['id']}/image", files={"image": ("a", JPEG, "image/jpeg")}, headers=csrf_headers(auth))
    assert r.status_code == 200 and r.json()["has_image"] is True
    assert auth.get(f"{URL}/{pm['id']}/image").content == JPEG
    bad = auth.put(f"{URL}/{pm['id']}/image", files={"image": ("a", GIF, "image/png")}, headers=csrf_headers(auth))
    assert bad.status_code == 422
    assert auth.get(f"{URL}/{pm['id']}/image").content == JPEG


@pytest.mark.parametrize(
    "over",
    [
        {"network": None},  # card needs network
        {"type": "upi"},  # upi must not have network
        {"type": "other"},
        {"name": ""},
        {"name": "x" * 61},
        {"bank": "x" * 41},
        {"type": "bogus"},
        {"color": "red"},
        {"color": "#12345"},
        {"color": "#12345g"},
        {"color": "123456"},
        {"name": "   "},
    ],
)
def test_create_validation(auth, over):
    assert create(auth, **over).status_code == 422


def test_create_upi_without_network(auth):
    r = create(auth, type="upi", bank=None, name="GPay", network=None)
    assert r.status_code == 201 and r.json()["network"] is None and r.json()["display_name"] == "GPay"


def test_list_hides_inactive_and_orders(auth):
    create(auth, type="other", bank=None, name="Cash", network=None)
    create(auth, type="upi", bank=None, name="GPay", network=None)
    card = create(auth).json()
    gone = create(auth, bank="AXIS", name="Old").json()
    assert auth.patch(f"{URL}/{gone['id']}", json={"is_active": False}, headers=csrf_headers(auth)).status_code == 200
    assert [m["name"] for m in auth.get(URL).json()] == [card["name"], "GPay", "Cash"]
    assert len(auth.get(URL, params={"include_inactive": "true"}).json()) == 4


def test_patch(auth):
    pm = create(auth).json()
    r = auth.patch(f"{URL}/{pm['id']}", json={"name": "Regalia Gold", "network": "mastercard"}, headers=csrf_headers(auth))
    assert r.status_code == 200
    assert r.json()["name"] == "Regalia Gold" and r.json()["network"] == "mastercard"
    assert r.json()["bank"] == "HDFC"
    cleared = auth.patch(f"{URL}/{pm['id']}", json={"bank": None}, headers=csrf_headers(auth))
    assert cleared.json()["bank"] is None and cleared.json()["display_name"] == "Regalia Gold"


@pytest.mark.parametrize("body", [{"name": "  "}, {"network": None}, {"name": ""}, {"name": None}, {"is_active": None}, {"name": "x" * 61}])
def test_patch_validation(auth, body):
    pm = create(auth).json()
    assert auth.patch(f"{URL}/{pm['id']}", json=body, headers=csrf_headers(auth)).status_code == 422


def test_not_found(auth):
    missing = uuid.uuid4()
    h = csrf_headers(auth)
    for r in (
        auth.patch(f"{URL}/{missing}", json={"name": "x"}, headers=h),
        auth.put(f"{URL}/{missing}/image", files={"image": ("a", PNG, "image/png")}, headers=h),
        auth.get(f"{URL}/{missing}/image"),
    ):
        assert r.status_code == 404 and r.json() == {"detail": "Payment method not found"}
    assert auth.get(f"{URL}/not-a-uuid/image").status_code == 422


def test_color_create_list_patch_clear(auth):
    pm = create(auth, color="#1A2b3C").json()
    assert pm["color"] == "#1A2b3C"
    assert auth.get(URL).json()[0]["color"] == "#1A2b3C"
    assert create(auth, name="Other").json()["color"] is None
    h = csrf_headers(auth)
    r = auth.patch(f"{URL}/{pm['id']}", json={"color": "#000000"}, headers=h)
    assert r.json()["color"] == "#000000"
    assert auth.patch(f"{URL}/{pm['id']}", json={"color": "nope"}, headers=h).status_code == 422
    assert auth.patch(f"{URL}/{pm['id']}", json={"color": None}, headers=h).json()["color"] is None


def test_bank_and_name_are_stripped(auth):
    pm = create(auth, bank="  HDFC ", name="  Regalia  ").json()
    assert (pm["bank"], pm["name"]) == ("HDFC", "Regalia")
    h = csrf_headers(auth)
    r = auth.patch(f"{URL}/{pm['id']}", json={"bank": " SBI ", "name": " Elite "}, headers=h)
    assert (r.json()["bank"], r.json()["name"]) == ("SBI", "Elite")


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_bank_is_none(auth, blank):
    assert create(auth, bank=blank).json()["bank"] is None
    pm = create(auth, name="Two").json()
    r = auth.patch(f"{URL}/{pm['id']}", json={"bank": blank}, headers=csrf_headers(auth))
    assert r.json()["bank"] is None


def test_patch_network_on_upi_rejected(auth):
    pm = create(auth, type="upi", bank=None, name="GPay", network=None).json()
    r = auth.patch(f"{URL}/{pm['id']}", json={"network": "visa"}, headers=csrf_headers(auth))
    assert r.status_code == 422
