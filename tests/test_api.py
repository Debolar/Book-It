"""Automated tests for the BookIt API. Run with: pytest"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import MemoryStore

HOTEL_ID = 1   # Lagoon View Suites: 85,000 per night, 6 rooms
EVENT_ID = 6   # Tech in Africa Summit: 25,000 per ticket, 5 tickets


def booking(listing_id=EVENT_ID, quantity=1, **extra):
    return {"listing_id": listing_id, "name": "Ada Obi", "email": "ada@example.com",
            "quantity": quantity, **extra}


@pytest.fixture
def client():
    with TestClient(create_app(store=MemoryStore())) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_reports_store(client):
    assert client.get("/ready").json()["store"] == "memory"


def test_ready_returns_503_when_store_is_down():
    store = MemoryStore()

    def broken():
        raise RuntimeError("database unreachable")

    store.ping = broken
    with TestClient(create_app(store=store)) as c:
        assert c.get("/ready").status_code == 503


def test_lists_all_sample_listings(client):
    assert len(client.get("/api/listings").json()) == 8


def test_filter_by_kind_and_city(client):
    events = client.get("/api/listings", params={"kind": "event"}).json()
    assert events and all(x["kind"] == "event" for x in events)
    abuja = client.get("/api/listings", params={"city": "abuja"}).json()
    assert abuja and all(x["city"] == "Abuja" for x in abuja)


def test_book_event_reduces_availability(client):
    res = client.post("/api/bookings", json=booking(quantity=2))
    assert res.status_code == 201
    body = res.json()
    assert body["ref"].startswith("BK-")
    assert body["total"] == 50000
    assert client.get(f"/api/listings/{EVENT_ID}").json()["available"] == 3


def test_hotel_total_uses_nights(client):
    res = client.post("/api/bookings", json=booking(HOTEL_ID, quantity=2, check_in="2026-12-20", nights=3))
    assert res.status_code == 201
    assert res.json()["total"] == 85000 * 2 * 3


def test_hotel_requires_check_in(client):
    assert client.post("/api/bookings", json=booking(HOTEL_ID)).status_code == 400


def test_cannot_overbook(client):
    res = client.post("/api/bookings", json=booking(quantity=6))
    assert res.status_code == 409
    assert "only 5 left" in res.json()["detail"]


def test_concurrent_bookings_never_overbook(client):
    # 20 people try to buy 1 ticket each at the same moment; only 5 exist.
    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(lambda _: client.post("/api/bookings", json=booking()).status_code, range(20)))
    assert codes.count(201) == 5
    assert codes.count(409) == 15
    assert client.get(f"/api/listings/{EVENT_ID}").json()["available"] == 0


def test_rejects_invalid_email(client):
    assert client.post("/api/bookings", json={**booking(), "email": "not-an-email"}).status_code == 422


def test_rejects_too_many_tickets(client):
    assert client.post("/api/bookings", json=booking(quantity=11)).status_code == 422


def test_missing_listing_returns_404(client):
    assert client.post("/api/bookings", json=booking(listing_id=999)).status_code == 404


def test_my_bookings_by_email(client):
    client.post("/api/bookings", json=booking())
    client.post("/api/bookings", json={**booking(), "email": "someone@example.com"})
    mine = client.get("/api/bookings", params={"email": "ADA@example.com"}).json()
    assert len(mine) == 1 and mine[0]["email"] == "ada@example.com"


def test_cancel_restores_availability(client):
    ref = client.post("/api/bookings", json=booking(quantity=3)).json()["ref"]
    res = client.post(f"/api/bookings/{ref}/cancel")
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    assert client.get(f"/api/listings/{EVENT_ID}").json()["available"] == 5


def test_cannot_cancel_twice(client):
    ref = client.post("/api/bookings", json=booking()).json()["ref"]
    client.post(f"/api/bookings/{ref}/cancel")
    assert client.post(f"/api/bookings/{ref}/cancel").status_code == 404
