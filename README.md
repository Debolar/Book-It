# BookIt

A web app for booking hotel rooms and event tickets. People browse listings, filter by type and city, book rooms or tickets, get a booking reference, and view or cancel their bookings by email. Staff use a protected **admin page** to add new hotels and events, and to update prices and availability.

The app code is done. Your job is the DevOps work, this time **mostly on your own**, using Fuel Finder as your reference.

```
Browser ──▶ BookIt (Python, FastAPI) ──▶ PostgreSQL
            serves the website AND the API
```

**Demo data:** the 8 hotels and events are fictional, with made-up prices and dates. No payment is taken.

## What makes this app different

- **Two tables** (`listings` and `bookings`) instead of one
- **It must never overbook.** If 20 people try to buy the last 5 tickets at the same moment, exactly 5 must succeed. The check and the update happen in one database statement, so this holds even with many copies of the app running. There's a test for it (`test_concurrent_bookings_never_overbook`)
- That makes it a good app to **scale** with an autoscaler, and to load-test

## Project structure

```
bookit/
├── app/
│   ├── main.py      Routes, validation, admin API, health checks, startup retries
│   ├── config.py    Settings from environment variables
│   ├── store.py     Data layer: in-memory (tests) or PostgreSQL (real)
│   └── seed.py      The sample hotels and events loaded on first start
├── static/          The website, plus admin.html (the admin page)
├── tests/           26 automated tests (pytest): booking + admin
├── requirements.txt / requirements-dev.txt / pyproject.toml
└── .env.example
```

## Run it locally

```bash
python -m venv .venv
source .venv/Scripts/activate      # Git Bash on Windows
pip install -r requirements-dev.txt
pytest                              # 26 tests should pass
ruff check .                        # "All checks passed!"
ADMIN_API_KEY=pick-a-local-key uvicorn app.main:app --port 8000
```

Open http://localhost:8000. Admin page: http://localhost:8000/admin.html (unlock it with the key you chose). API docs: http://localhost:8000/docs

Without `ADMIN_API_KEY`, the site works normally and the admin page is switched off.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | *(empty)* | PostgreSQL connection. Empty = in-memory |
| `APP_VERSION` | `dev` | Shown in the footer |
| `APP_ENV` | `local` | Environment name shown in the footer |
| `ADMIN_API_KEY` | *(empty)* | **Secret.** Unlocks the admin API and admin page. Empty = admin switched off. Never put the real value in Git |

The app creates its tables and sample listings on first start.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness: is the database reachable? `200` or `503` |
| GET | `/api/info` | Version, environment, store |
| GET | `/api/listings` | List hotels and events. Optional: `kind` (`hotel`/`event`), `city` |
| GET | `/api/listings/{id}` | One listing, including places left |
| POST | `/api/bookings` | Book: `listing_id`, `name`, `email`, `quantity`; hotels also need `check_in` and `nights` |
| GET | `/api/bookings?email=` | A person's bookings |
| POST | `/api/bookings/{ref}/cancel` | Cancel a booking; the places go back on sale |

**Admin API** (every request needs the header `X-Admin-Key: <your key>`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/check` | Check a key is valid |
| POST | `/api/admin/listings` | Add a hotel or event (`kind`, `title`, `city`, `venue`, `date` for events, `price`, `available`, `description`) |
| PATCH | `/api/admin/listings/{id}` | Update `title`, `price`, `available` or `description` |

Example:

```bash
curl -X POST http://localhost:8000/api/admin/listings \
  -H "Content-Type: application/json" -H "X-Admin-Key: $ADMIN_API_KEY" \
  -d '{"kind":"event","title":"New Year Countdown","city":"Lagos","venue":"Beachfront","date":"2026-12-31","price":20000,"available":200}'
```

Status codes to know: `201` booked, `409` not enough places left, `422` invalid input, `404` not found, `401` missing or wrong admin key, `503` admin switched off.

---

# Your DevOps tasks

Write each file yourself first, using Fuel Finder's as a guide, then ask for a review.

### 1. Repository
- [ ] GitHub repo `bookit`, branch `main`, `.gitattributes`, protected with a ruleset (no bypass)

### 2. Docker
- [ ] `Dockerfile` (same five questions as Fuel Finder; port 8000)
- [ ] `.dockerignore`
- [ ] `docker-compose.yml` with PostgreSQL and a named volume; check a booking survives `down` and `up`
- [ ] Pass `ADMIN_API_KEY` to the app from a `.env` file (which `.gitignore` already keeps out of Git), not written into the Compose file

### 3. CI
- [ ] Workflow: lint and test on PRs; build, Trivy scan and push on merge; `test` as a required check

### 4. Kubernetes
- [ ] Namespace `bookit`, Secret, database StatefulSet, app Deployment with probes, Service
- [ ] Put `ADMIN_API_KEY` in a Kubernetes Secret (created with `kubectl`, never in a YAML file in Git), and pass it to the app with `secretKeyRef`
- [ ] Rotate the key: change the Secret, restart the app, check the old key stops working
- [ ] Ingress through Traefik at `bookit.localhost`

### 5. GitOps
- [ ] Make the image public; point the Deployment at the pipeline image
- [ ] Argo CD Application watching `k8s/`

### 6. Stretch: scaling under demand
- [ ] Add CPU requests, install metrics-server, add a HorizontalPodAutoscaler (2 to 8 replicas)
- [ ] Load-test the booking endpoint and watch Pods being added
- [ ] Confirm it still never overbooks with several replicas running
