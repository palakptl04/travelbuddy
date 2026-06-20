# TravelBuddy — Project Overview

> A Flask web application for finding travel companions, managing shared trips, and splitting expenses.

---

## Architecture

```
travelbuddy/
├── run.py                   # App entry point
├── config.py                # Config / TestingConfig classes
├── seed.py                  # Dev seed data
├── Dockerfile               # Multi-stage Docker build (builder + runtime)
├── docker-compose.yml       # Single-service compose (SQLite volume)
├── requirements.txt         # Python dependencies
├── pytest.ini               # Test config
├── migrations/              # Flask-Migrate / Alembic (1 revision)
│   └── versions/
│       └── 5afe88814f04_initial_schema_with_trip_lifecycle.py
├── tests/
│   ├── conftest.py          # Fixtures: app, auth_client, sample_trip, clean_db
│   ├── test_auth.py
│   ├── test_trips.py
│   ├── test_settlements.py
│   └── test_api.py
└── app/
    ├── __init__.py          # App factory (create_app)
    ├── extensions.py        # db, bcrypt, login_manager, csrf, migrate
    ├── models.py            # All ORM models
    ├── cities.py            # Gujarat + nearby city lists
    ├── templates/
    │   ├── base.html
    │   ├── main/home.html
    │   ├── auth/{login,register}.html
    │   ├── dashboard/index.html
    │   ├── profile/{view,edit}.html
    │   ├── trips/{index,create,edit,detail}.html
    │   └── expenses/my_expenses.html
    ├── main/                # Blueprint: landing page
    ├── auth/                # Blueprint: register, login, logout
    ├── dashboard/           # Blueprint: dashboard + quick request actions
    ├── profile/             # Blueprint: view and edit profile
    ├── trips/               # Blueprint: full trip CRUD + membership
    ├── expenses/            # Blueprint: expense CRUD + settlements
    └── api/                 # Blueprint: REST API v1 (read-only JSON)
```

### Stack

| Layer | Technology |
|---|---|
| Framework | Flask 3.x |
| ORM / Migrations | Flask-SQLAlchemy 3.x + Flask-Migrate (Alembic) |
| Auth | Flask-Login 0.6.x + Flask-Bcrypt |
| Forms / CSRF | Flask-WTF + WTForms |
| Database | SQLite (dev/prod default), in-memory SQLite (tests) |
| Production server | Gunicorn |
| Testing | pytest + pytest-flask |

---

## Database Models

### `User` — `users`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(100) | |
| `email` | String(150) | unique |
| `password_hash` | String(255) | bcrypt |
| `travel_style` | String(50) | flexible / adventurous / relaxed / budget |
| `bio` | Text | max 160 chars |
| `interests` | String(255) | comma-separated, max 3 values |
| `phone` | String(20) | optional |
| `created_at` | DateTime | UTC |

**Key methods:** `get_active_trips()`, `get_upcoming_trips()`, `get_pending_requests()`, `get_total_balance()`, `_all_trip_ids()`

---

### `Trip` — `trips`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `owner_id` | FK → users | |
| `title` | String(150) | |
| `destination` | String(150) | from city list |
| `departure_city` | String(100) | from city list |
| `start_date` / `end_date` | Date | start ≥ today + 2 days |
| `description` | Text | max 500 chars |
| `budget_min` / `budget_max` | Float | ₹ |
| `max_members` | Integer | 1–50, default 4 |
| `status` | String(20) | see lifecycle below |
| `confirmation_deadline` | DateTime | nullable |
| `confirmation_started_at` | DateTime | nullable |
| `cancelled_at` | DateTime | nullable |
| `is_public` | Boolean | default True |
| `created_at` | DateTime | UTC |

**Indexes:** `(owner_id, status)`, `(is_public, start_date)`

**Computed properties:** `computed_status` (upcoming/ongoing/completed), `joining_closed`, `main_confirmation_deadline` (start − 2 days), `confirmation_window_deadline` (confirmation_started_at + 24 h), `status_label`

---

### `TripMember` — `trip_members`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `trip_id` | FK → trips | cascade delete |
| `user_id` | FK → users | |
| `status` | String(20) | `pending` / `accepted` / `declined` |
| `is_confirmed` | Boolean | for AWAITING_CONFIRMATION phase |
| `confirmed_at` | DateTime | nullable |
| `joined_at` | DateTime | UTC |

**Constraints:** unique `(trip_id, user_id)`. Indexes on `(user_id, status)` and `(trip_id, status)`.

---

### `Expense` — `expenses`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `trip_id` | FK → trips | cascade delete |
| `paid_by_id` | FK → users | always the current logged-in user |
| `title` | String(150) | |
| `amount` | Float | ₹, > 0 |
| `category` | String(50) | food / transport / accommodation / activities / other |
| `date` | Date | defaults to today |
| `created_at` | DateTime | UTC |

**Indexes:** `(trip_id, paid_by_id)`, `(trip_id, date)`

---

### `Settlement` — `settlements`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `trip_id` | FK → trips | cascade delete |
| `payer_id` | FK → users | debtor |
| `payee_id` | FK → users | creditor |
| `amount` | Float | ₹ |
| `is_settled` | Boolean | default False |
| `settled_at` | DateTime | nullable |

**Indexes:** `(trip_id, payer_id)`, `(trip_id, payee_id)`

---

## Trip Lifecycle

```
OPEN ──(full OR 2 days before start)──► AWAITING_CONFIRMATION
                                              │
                          ┌───────────────────┴──────────────────┐
                          │ all members confirm within 24 h       │ 24 h window expires
                          ▼                                        ▼
                      CONFIRMED                    non-confirmed members → declined
                          │                        trip → CONFIRMED (confirmed only)
                          │
             (start_date reached via refresh_status)
                          │
                          ▼
                        ACTIVE
                          │
              (end_date passed via refresh_status)
                          │
                          ▼
                      COMPLETED

Any non-CANCELLED trip before start_date ──(owner action)──► CANCELLED
```

**Status rules enforced in code:**
- `OPEN`: Accepts new buddy requests; joining closes 1 day before start.
- `AWAITING_CONFIRMATION`: Accepted members have 24 h to confirm. Triggered automatically when trip is full or 2 days before start.
- `CONFIRMED`: All confirmed members locked in. Expenses can be added.
- `ACTIVE`: `start_date` reached. Expenses can be added.
- `COMPLETED`: `end_date` passed. Read-only.
- `CANCELLED`: Owner-initiated before start date.

`Trip.refresh_status()` is called on every detail page load and auto-advances OPEN/AWAITING_CONFIRMATION/CONFIRMED → ACTIVE → COMPLETED based on today's date.

---

## Blueprints & Routes

### `main` — `/`

| Method | Route | Description |
|---|---|---|
| GET | `/` | Landing / home page |

---

### `auth` — `/auth`

| Method | Route | Description |
|---|---|---|
| GET/POST | `/auth/register` | Register new user (name, email, password) |
| GET/POST | `/auth/login` | Login with email + bcrypt password check; `next` redirect support |
| GET | `/auth/logout` | Logout and redirect to home |

---

### `dashboard` — `/dashboard`

| Method | Route | Auth | Description |
|---|---|---|---|
| GET | `/dashboard` | ✓ | Shows active trips, upcoming trips, pending buddy requests, recent expenses (last 5), net balance, buddy count |
| POST | `/dashboard/request/<id>/accept` | ✓ | Quick-accept buddy request from dashboard |
| POST | `/dashboard/request/<id>/decline` | ✓ | Quick-decline buddy request from dashboard |

---

### `profile` — `/profile`

| Method | Route | Auth | Description |
|---|---|---|---|
| GET | `/profile` | ✓ | View own profile |
| GET/POST | `/profile/edit` | ✓ | Edit name, bio, travel style, phone, interests (max 3) |

---

### `trips` — `/trips`

| Method | Route | Auth | Description |
|---|---|---|---|
| GET | `/trips` | optional | Browse open public trips (paginated, 10/page); filter by destination & budget; show user's own trips |
| GET/POST | `/trips/create` | ✓ | Create a new trip |
| GET | `/trips/<id>` | ✓ | Trip detail: members, expenses, settlement summary, settlement actions; auto-advances trip status |
| GET/POST | `/trips/<id>/edit` | ✓ (owner) | Edit trip fields |
| POST | `/trips/<id>/cancel` | ✓ (owner) | Cancel trip (must be before start date) |
| POST | `/trips/<id>/request` | ✓ | Send buddy request to join trip |
| POST | `/trips/<id>/request/<mid>/accept` | ✓ (owner) | Accept a pending buddy request |
| POST | `/trips/<id>/request/<mid>/decline` | ✓ (owner) | Decline a pending buddy request |
| POST | `/trips/<id>/confirm` | ✓ (member) | Confirm participation during AWAITING_CONFIRMATION phase |
| POST | `/trips/<id>/leave` | ✓ (member) | Leave a trip (only while OPEN) |

---

### `expenses` — `/trips/<id>/expenses` & `/my-expenses`

| Method | Route | Auth | Description |
|---|---|---|---|
| POST | `/trips/<id>/expenses/add` | ✓ (member) | Add expense; only if trip is CONFIRMED or ACTIVE; always records current user as payer |
| POST | `/trips/<id>/expenses/<eid>/delete` | ✓ (payer or owner) | Delete an expense |
| POST | `/trips/<id>/settlements/mark-settled` | ✓ (debtor only) | Mark a specific payer→payee transfer as settled |
| GET | `/my-expenses` | ✓ | Cross-trip expense summary with per-trip balance and settlement status |

---

### `api` — `/api/v1` (REST, read-only JSON)

All endpoints use session cookie auth (same as web UI). No API keys.

| Method | Route | Description |
|---|---|---|
| GET | `/api/v1/trips` | Paginated list of user's trips (`page`, `per_page` ≤ 50) |
| GET | `/api/v1/trips/<id>` | Full trip detail: members, expenses, computed settlements |
| GET | `/api/v1/expenses` | All user expenses across all trips (`page`, `per_page` ≤ 100, `trip_id` filter) |
| GET | `/api/v1/settlements` | Computed settlement plan per trip (`trip_id` filter); includes `is_settled` flag |

**Error responses:** 401 / 403 / 404 returned as JSON `{ "error": "...", "status": N }`.

---

## Expense & Settlement Logic

### Equal Split
All expenses on a trip are split equally among all participants (owner + accepted members). There is no per-member or per-expense weighting.

```
share = total_spent / member_count
balance_for(user) = amount_paid_by_user - share
```

### Greedy Minimum-Transfers (Splitwise-style)
`Trip.calculate_settlements()` implements a greedy algorithm:
1. Compute net balance for each member (paid − share).
2. Separate into **creditors** (balance > 0) and **debtors** (balance < 0).
3. Sort creditors descending, debtors ascending.
4. Greedily match the largest debtor to the largest creditor, creating one transfer per iteration.
5. Result: minimum number of transactions to settle all debts.

### Settlement Tracking
- `Settlement` records are created/updated when a debtor clicks **"Mark as Settled"**.
- Only the debtor (payer) can mark their own debt settled.
- `my_expenses` page drives settlement status from `Settlement` DB records cross-referenced against computed transfers — not from raw balance alone (avoids false "settled" when balance happens to be zero but transfers remain unpaid).

---

## Authentication & Security

- **Registration:** name, email, password (min 6 chars); duplicate email rejected at form validation.
- **Password hashing:** Flask-Bcrypt.
- **Session management:** Flask-Login; `login_view = 'auth.login'`; `login_message_category = 'error'`.
- **CSRF protection:** Flask-WTF `CSRFProtect` applied globally; disabled in `TestingConfig`.
- **Authorization:** Route-level checks for ownership (`trip.owner_id == current_user.id`) and membership (`TripMember.status == 'accepted'`); API returns 403 for non-members.
- **No OAuth / social login** — email + password only.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-secret-change-in-production` | Flask session signing |
| `DATABASE_URL` | `sqlite:///travelbuddy.db` | SQLAlchemy DB URI |
| `FLASK_APP` | `run.py` | Flask CLI / Gunicorn entrypoint |

`TestingConfig` uses in-memory SQLite with `StaticPool` and disables CSRF.

---

## City Data

`app/cities.py` provides two static lists used as form `SelectField` choices:
- **GUJARAT_CITIES**: 27 Gujarat cities (Ahmedabad, Surat, Vadodara, …)
- **NEARBY_CITIES**: 7 nearby cities (Mumbai, Pune, Udaipur, Mount Abu, Indore, Diu, Daman)

Destination must differ from departure city (validated in `TripForm`).

---

## Tests

| File | Coverage area |
|---|---|
| `tests/test_auth.py` | Register, login, logout flows |
| `tests/test_trips.py` | Trip CRUD, buddy request flow, confirm/leave/cancel, status transitions |
| `tests/test_settlements.py` | Expense add/delete, mark-settled, balance calculations |
| `tests/test_api.py` | All four API v1 endpoints; auth enforcement; pagination |

**Test strategy:**
- Session-scoped `app` fixture with in-memory SQLite; schema created once.
- `_clean_db` autouse fixture truncates all tables after every test (no test bleed).
- `_push_request_context` overridden with a no-op to prevent Flask 3 + Flask-Login context leak where `g._login_user` would persist across requests from different test clients.
- Run: `pytest -v --tb=short`

---

## Containerization (Files Present)

The following Docker files **exist in the repo** but containerized deployment has not been fully validated:

| File | Contents |
|---|---|
| [`Dockerfile`](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/Dockerfile) | Multi-stage build (builder + runtime); non-root user; Gunicorn on port 5000; runs `flask db upgrade` on start |
| [`.dockerignore`](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/.dockerignore) | Excludes `.git`, `__pycache__`, `instance/`, `htmlcov/`, etc. |
| [`docker-compose.yml`](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/docker-compose.yml) | Single `web` service; SQLite volume at `./instance`; health check via `urllib.request` to `localhost:5000/`; `SECRET_KEY` and `DATABASE_URL` via env vars |

---

## CI/CD (File Present)

[`.github/workflows/ci.yml`](file:///c:/Users/palak/Downloads/travelbuddy_v6/travelbuddy/.github/workflows/ci.yml) **exists** and defines a GitHub Actions workflow, but it has **not been tested end-to-end** in CI (no runs confirmed):

- Triggers on push/PR to `main` or `develop`.
- Runner: `ubuntu-latest`, Python 3.12 with pip cache.
- Steps: checkout → install deps → `pytest -v --tb=short` → upload `.pytest_cache/` artifact (7-day retention).

---

## Remaining Implementations

The following items are **not yet fully implemented or validated**:

- **Docker / Containerization** — `Dockerfile` and `docker-compose.yml` are present but the containerized deployment has not been tested end-to-end. Known gaps: production database choice (SQLite in a volume is not suitable for multi-replica deployments), secret management, health-check reliability.

- **GitHub Actions / CI Testing** — `.github/workflows/ci.yml` is written but has never been run against the actual repository in GitHub. Needs: a live GitHub repo push to verify the workflow runs green, coverage reporting (currently only `.pytest_cache/` is uploaded, not an HTML/XML coverage report), and possibly a lint step (flake8/ruff).
