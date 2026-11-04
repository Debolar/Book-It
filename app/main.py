"""BookIt API: book hotel rooms and event tickets."""

import datetime as dt
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import settings
from app.store import NotEnoughAvailability, NotFound, create_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("bookit")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class BookingIn(BaseModel):
    listing_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=200)
    quantity: int = Field(ge=1, le=10, description="Rooms or tickets")
    # Hotels only: arrival date and number of nights.
    check_in: dt.date | None = None
    nights: int = Field(default=1, ge=1, le=30)


class ListingIn(BaseModel):
    kind: Literal["hotel", "event"]
    title: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=60)
    venue: str = Field(min_length=1, max_length=120)
    # Events need a date; hotels do not.
    date: dt.date | None = None
    price: int = Field(gt=0, le=100_000_000, description="Naira per night or per ticket")
    available: int = Field(ge=0, le=100_000, description="Rooms or tickets on sale")
    description: str = Field(default="", max_length=500)


class ListingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    price: int | None = Field(default=None, gt=0, le=100_000_000)
    available: int | None = Field(default=None, ge=0, le=100_000)
    description: str | None = Field(default=None, max_length=500)


def create_app(store=None, admin_key: str | None = None) -> FastAPI:
    store = store or create_store(settings.database_url)
    admin_key = settings.admin_api_key if admin_key is None else admin_key

    def require_admin(x_admin_key: str | None = Header(default=None)):
        """Allow the request only if it carries the correct admin key."""
        if not admin_key:
            raise HTTPException(status_code=503, detail="admin API is disabled: ADMIN_API_KEY is not set")
        if not x_admin_key or not secrets.compare_digest(x_admin_key, admin_key):
            raise HTTPException(status_code=401, detail="missing or wrong admin key")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Retry the database on startup: in Compose or Kubernetes it is often
        # not ready the moment the app starts.
        for attempt in range(1, 11):
            try:
                store.init()
                break
            except Exception as err:  # noqa: BLE001
                if attempt == 10:
                    log.error("Could not connect to the database: %s", err)
                    raise
                log.info("Database not ready (attempt %s/10), retrying in 3s", attempt)
                time.sleep(3)
        log.info("bookit v%s started (store: %s, env: %s)",
                 settings.app_version, store.kind, settings.environment)
        yield

    app = FastAPI(title="BookIt", version=settings.app_version, lifespan=lifespan)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        log.info("%s %s %s %.0fms", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000)
        return response

    # ---- Health checks ----

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            store.ping()
            return {"status": "ready", "store": store.kind}
        except Exception as err:  # noqa: BLE001
            return JSONResponse(status_code=503, content={"status": "not ready", "error": str(err)})

    # ---- API ----

    @app.get("/api/info")
    def info():
        return {"app": "bookit", "version": settings.app_version,
                "environment": settings.environment, "store": store.kind,
                "admin_enabled": bool(admin_key)}

    @app.get("/api/listings")
    def list_listings(
        kind: Literal["hotel", "event"] | None = None,
        city: str | None = Query(default=None, max_length=60),
    ):
        listings = store.list_listings()
        if kind:
            listings = [x for x in listings if x["kind"] == kind]
        if city:
            listings = [x for x in listings if x["city"].lower() == city.lower()]
        return listings

    @app.get("/api/listings/{listing_id}")
    def get_listing(listing_id: int):
        listing = store.get_listing(listing_id)
        if not listing:
            raise HTTPException(status_code=404, detail="listing not found")
        return listing

    @app.post("/api/bookings", status_code=201)
    def create_booking(body: BookingIn):
        listing = store.get_listing(body.listing_id)
        if not listing:
            raise HTTPException(status_code=404, detail="listing not found")

        if listing["kind"] == "hotel":
            if body.check_in is None:
                raise HTTPException(status_code=400, detail="check_in is required for hotel bookings")
            check_in, nights = body.check_in.isoformat(), body.nights
        else:
            check_in, nights = None, 1

        try:
            return store.book(body.listing_id, body.name.strip(), body.email.lower(),
                              body.quantity, nights, check_in)
        except NotEnoughAvailability as err:
            raise HTTPException(
                status_code=409, detail=f"not enough availability: only {err.available} left"
            ) from err

    @app.get("/api/bookings")
    def my_bookings(email: str = Query(pattern=EMAIL_PATTERN, max_length=200)):
        return store.bookings_for(email.lower())

    @app.post("/api/bookings/{ref}/cancel")
    def cancel_booking(ref: str):
        try:
            return store.cancel(ref)
        except NotFound:
            raise HTTPException(status_code=404, detail="no active booking with that reference") from None

    # ---- Admin API (needs the X-Admin-Key header) ----

    @app.get("/api/admin/check", dependencies=[Depends(require_admin)])
    def admin_check():
        return {"status": "ok"}

    @app.post("/api/admin/listings", status_code=201, dependencies=[Depends(require_admin)])
    def add_listing(body: ListingIn):
        if body.kind == "event" and body.date is None:
            raise HTTPException(status_code=400, detail="date is required for events")
        data = body.model_dump()
        data["date"] = body.date.isoformat() if body.kind == "event" else None
        listing = store.create_listing(data)
        log.info("admin added listing %s: %s", listing["id"], listing["title"])
        return listing

    @app.patch("/api/admin/listings/{listing_id}", dependencies=[Depends(require_admin)])
    def update_listing(listing_id: int, body: ListingUpdate):
        listing = store.update_listing(listing_id, body.model_dump(exclude_unset=True, exclude_none=True))
        if not listing:
            raise HTTPException(status_code=404, detail="listing not found")
        log.info("admin updated listing %s", listing_id)
        return listing

    # The website itself, served from the same container.
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


app = create_app()
