"""Data storage: an in-memory store for tests, and PostgreSQL for real deployments.

The important rule in both: a booking must never take more places than are left.
The check and the update happen together, so two people booking the last ticket
at the same moment cannot both succeed.
"""

import copy
import secrets
import string
import threading
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row

from app.seed import SAMPLE_LISTINGS


class NotFound(Exception):
    pass


class NotEnoughAvailability(Exception):
    def __init__(self, available: int) -> None:
        super().__init__(f"only {available} left")
        self.available = available


def new_reference() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "BK-" + "".join(secrets.choice(alphabet) for _ in range(6))


def booking_total(listing: dict, quantity: int, nights: int) -> int:
    if listing["kind"] == "hotel":
        return listing["price"] * quantity * nights
    return listing["price"] * quantity


class MemoryStore:
    kind = "memory"

    def __init__(self, seed: bool = True) -> None:
        self._lock = threading.Lock()
        self._listings: list[dict] = []
        self._bookings: list[dict] = []
        if seed:
            for i, listing in enumerate(SAMPLE_LISTINGS, start=1):
                self._listings.append({"id": i, **copy.deepcopy(listing)})

    def init(self) -> None:
        pass

    def ping(self) -> None:
        pass

    def list_listings(self) -> list[dict]:
        return [dict(item) for item in self._listings]

    def get_listing(self, listing_id: int) -> dict | None:
        found = next((x for x in self._listings if x["id"] == listing_id), None)
        return dict(found) if found else None

    def create_listing(self, data: dict) -> dict:
        with self._lock:
            listing = {"id": max((x["id"] for x in self._listings), default=0) + 1, **data}
            self._listings.append(listing)
            return dict(listing)

    def update_listing(self, listing_id: int, changes: dict) -> dict | None:
        with self._lock:
            listing = next((x for x in self._listings if x["id"] == listing_id), None)
            if not listing:
                return None
            listing.update(changes)
            return dict(listing)

    def book(self, listing_id: int, name: str, email: str, quantity: int,
             nights: int, check_in: str | None) -> dict:
        with self._lock:
            listing = next((x for x in self._listings if x["id"] == listing_id), None)
            if not listing:
                raise NotFound()
            if listing["available"] < quantity:
                raise NotEnoughAvailability(listing["available"])
            listing["available"] -= quantity
            booking = {
                "ref": new_reference(),
                "listing_id": listing_id,
                "listing_title": listing["title"],
                "kind": listing["kind"],
                "name": name,
                "email": email,
                "quantity": quantity,
                "nights": nights,
                "check_in": check_in,
                "total": booking_total(listing, quantity, nights),
                "status": "confirmed",
                "created_at": datetime.now(UTC).isoformat(),
            }
            self._bookings.append(booking)
            return dict(booking)

    def bookings_for(self, email: str) -> list[dict]:
        return [dict(b) for b in reversed(self._bookings) if b["email"] == email]

    def cancel(self, ref: str) -> dict:
        with self._lock:
            booking = next((b for b in self._bookings if b["ref"] == ref), None)
            if not booking or booking["status"] != "confirmed":
                raise NotFound()
            booking["status"] = "cancelled"
            listing = next(x for x in self._listings if x["id"] == booking["listing_id"])
            listing["available"] += booking["quantity"]
            return dict(booking)


class PostgresStore:
    """Opens a short-lived connection per operation, so a database restart
    never leaves the app holding a broken connection."""

    kind = "postgres"

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=3)

    def init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS listings (
                  id SERIAL PRIMARY KEY,
                  kind VARCHAR(10) NOT NULL,
                  title VARCHAR(120) NOT NULL,
                  city VARCHAR(60) NOT NULL,
                  venue VARCHAR(120) NOT NULL,
                  date VARCHAR(10),
                  price INTEGER NOT NULL,
                  available INTEGER NOT NULL CHECK (available >= 0),
                  description TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                  ref VARCHAR(12) PRIMARY KEY,
                  listing_id INTEGER NOT NULL REFERENCES listings(id),
                  name VARCHAR(100) NOT NULL,
                  email VARCHAR(200) NOT NULL,
                  quantity INTEGER NOT NULL,
                  nights INTEGER NOT NULL,
                  check_in VARCHAR(10),
                  total INTEGER NOT NULL,
                  status VARCHAR(12) NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            if conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()["n"] == 0:
                for item in SAMPLE_LISTINGS:
                    conn.execute(
                        """INSERT INTO listings
                             (kind, title, city, venue, date, price, available, description)
                           VALUES (%(kind)s, %(title)s, %(city)s, %(venue)s, %(date)s, %(price)s,
                                   %(available)s, %(description)s)""",
                        item,
                    )

    def ping(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1")

    def list_listings(self) -> list[dict]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM listings ORDER BY id").fetchall()

    def get_listing(self, listing_id: int) -> dict | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM listings WHERE id = %s", (listing_id,)).fetchone()

    def create_listing(self, data: dict) -> dict:
        with self._connect() as conn:
            return conn.execute(
                """INSERT INTO listings
                             (kind, title, city, venue, date, price, available, description)
                   VALUES (%(kind)s, %(title)s, %(city)s, %(venue)s, %(date)s, %(price)s,
                           %(available)s, %(description)s)
                   RETURNING *""",
                data,
            ).fetchone()

    def update_listing(self, listing_id: int, changes: dict) -> dict | None:
        allowed = {"title", "price", "available", "description"}
        sets, values = [], []
        for key, value in changes.items():
            if key in allowed:
                sets.append(f"{key} = %s")
                values.append(value)
        if not sets:
            return self.get_listing(listing_id)
        values.append(listing_id)
        with self._connect() as conn:
            return conn.execute(
                f"UPDATE listings SET {', '.join(sets)} WHERE id = %s RETURNING *", values
            ).fetchone()

    def book(self, listing_id: int, name: str, email: str, quantity: int,
             nights: int, check_in: str | None) -> dict:
        with self._connect() as conn:
            # One statement both checks and takes the places, so it is safe
            # even when many people book at the same moment.
            listing = conn.execute(
                """UPDATE listings SET available = available - %s
                   WHERE id = %s AND available >= %s
                   RETURNING *""",
                (quantity, listing_id, quantity),
            ).fetchone()
            if not listing:
                current = conn.execute(
                    "SELECT available FROM listings WHERE id = %s", (listing_id,)
                ).fetchone()
                if not current:
                    raise NotFound()
                raise NotEnoughAvailability(current["available"])
            booking = conn.execute(
                """INSERT INTO bookings
                     (ref, listing_id, name, email, quantity, nights, check_in, total, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'confirmed') RETURNING *""",
                (new_reference(), listing_id, name, email, quantity, nights, check_in,
                 booking_total(listing, quantity, nights)),
            ).fetchone()
            return self._with_listing(booking, listing)

    def bookings_for(self, email: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT b.*, l.title AS listing_title, l.kind
                   FROM bookings b JOIN listings l ON l.id = b.listing_id
                   WHERE b.email = %s ORDER BY b.created_at DESC""",
                (email,),
            ).fetchall()
        return [self._clean(r) for r in rows]

    def cancel(self, ref: str) -> dict:
        with self._connect() as conn:
            booking = conn.execute(
                """UPDATE bookings SET status = 'cancelled'
                   WHERE ref = %s AND status = 'confirmed' RETURNING *""",
                (ref,),
            ).fetchone()
            if not booking:
                raise NotFound()
            listing = conn.execute(
                "UPDATE listings SET available = available + %s WHERE id = %s RETURNING *",
                (booking["quantity"], booking["listing_id"]),
            ).fetchone()
            return self._with_listing(booking, listing)

    @staticmethod
    def _clean(row: dict) -> dict:
        row = dict(row)
        if row.get("created_at") is not None:
            row["created_at"] = row["created_at"].isoformat()
        return row

    def _with_listing(self, booking: dict, listing: dict) -> dict:
        row = self._clean(booking)
        row["listing_title"] = listing["title"]
        row["kind"] = listing["kind"]
        return row


def create_store(database_url: str):
    return PostgresStore(database_url) if database_url else MemoryStore()
