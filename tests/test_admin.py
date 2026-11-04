"""Tests for the admin API. Run with: pytest"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import MemoryStore

KEY = "test-admin-key"
NEW_EVENT = {"kind": "event", "title": "New Year Countdown", "city": "Lagos",
             "venue": "Beachfront Grounds", "date": "2026-12-31", "price": 20000,
             "available": 200, "description": "Music and fireworks."}


@pytest.fixture
def client():
    with TestClient(create_app(store=MemoryStore(), admin_key=KEY)) as c:
        yield c


def admin(key=KEY):
    return {"X-Admin-Key": key}


def test_admin_api_is_off_without_a_configured_key():
    with TestClient(create_app(store=MemoryStore(), admin_key="")) as c:
        assert c.post("/api/admin/listings", json=NEW_EVENT, headers=admin()).status_code == 503
        assert c.get("/api/info").json()["admin_enabled"] is False


def test_rejects_missing_key(client):
    assert client.post("/api/admin/listings", json=NEW_EVENT).status_code == 401


def test_rejects_wrong_key(client):
    assert client.post("/api/admin/listings", json=NEW_EVENT, headers=admin("guess")).status_code == 401


def test_check_accepts_correct_key(client):
    assert client.get("/api/admin/check", headers=admin()).status_code == 200


def test_add_event_appears_in_listings(client):
    res = client.post("/api/admin/listings", json=NEW_EVENT, headers=admin())
    assert res.status_code == 201
    new_id = res.json()["id"]
    assert new_id == 9
    titles = [x["title"] for x in client.get("/api/listings", params={"kind": "event"}).json()]
    assert "New Year Countdown" in titles
    # and it can be booked straight away
    booking = {"listing_id": new_id, "name": "Ada", "email": "ada@example.com", "quantity": 2}
    assert client.post("/api/bookings", json=booking).status_code == 201


def test_event_needs_a_date(client):
    res = client.post("/api/admin/listings", json={**NEW_EVENT, "date": None}, headers=admin())
    assert res.status_code == 400


def test_hotel_date_is_ignored(client):
    hotel = {**NEW_EVENT, "kind": "hotel", "title": "Seaside Rooms", "date": "2026-12-31"}
    res = client.post("/api/admin/listings", json=hotel, headers=admin())
    assert res.status_code == 201 and res.json()["date"] is None


def test_rejects_invalid_listing(client):
    bad = {**NEW_EVENT, "price": 0}
    assert client.post("/api/admin/listings", json=bad, headers=admin()).status_code == 422


def test_update_price_and_availability(client):
    res = client.patch("/api/admin/listings/1", json={"price": 90000, "available": 2}, headers=admin())
    assert res.status_code == 200
    assert res.json()["price"] == 90000 and res.json()["available"] == 2


def test_update_missing_listing_returns_404(client):
    assert client.patch("/api/admin/listings/999", json={"price": 1}, headers=admin()).status_code == 404
