# TravelBuddy 🌍

[![CI](https://github.com/<YOUR_GITHUB_USERNAME>/travelbuddy/actions/workflows/ci.yml/badge.svg)](https://github.com/<YOUR_GITHUB_USERNAME>/travelbuddy/actions/workflows/ci.yml)

A Flask-based travel planning and expense-splitting web app. Find trip buddies, split costs automatically with a Splitwise-style algorithm, and track settlements across all your trips.

---

## Features

- 🔐 **Auth** — Register, login, logout with bcrypt password hashing
- 🗺️ **Trip Management** — Create, edit, delete trips; send/accept/decline buddy requests
- 💰 **Expense Splitting** — Equal split among all trip members
- 📊 **Settlement Algorithm** — Greedy minimum-transfers (Splitwise-style)
- 🔍 **Browse & Filter** — Public trip discovery with destination/budget filters + pagination
- 📡 **REST API** — Read-only JSON API at `/api/v1`
- 🐳 **Docker** — Production-ready containerisation

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.10+
- pip

### Setup

```bash
# Clone and enter the project
cd travelbuddy

# Create a virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up the database
flask db upgrade          # runs all migrations
# OR, for a brand-new local DB:
# flask db stamp head     # if you already have an existing travelbuddy.db

# (Optional) Seed sample data
python seed.py

# Run the dev server
flask run
# App available at http://127.0.0.1:5000
```

---

## Migration Commands

Flask-Migrate (Alembic) manages the database schema.

```bash
# One-time: initialise migration repo (already done — do NOT re-run on existing projects)
flask db init

# Generate a new migration after changing models.py
flask db migrate -m "Describe your change"

# Apply pending migrations
flask db upgrade

# Roll back the last migration
flask db downgrade

# Stamp an existing DB as up-to-date (no data loss)
flask db stamp head

# Show migration history
flask db history
```

---

## Running Tests

```bash
# Install test dependencies (already in requirements.txt)
pip install pytest pytest-flask

# Run all tests with verbose output
pytest -v --tb=short

# Run a specific test file
pytest tests/test_auth.py -v

# Run a specific test class or function
pytest tests/test_settlements.py::TestSettlementAlgorithm::test_minimum_transfers_algorithm -v

# Run with coverage (install pytest-cov first)
pip install pytest-cov
pytest --cov=app --cov-report=html
```

### Test Modules

| File | Coverage |
|------|----------|
| `tests/test_auth.py` | Register, Login, Logout |
| `tests/test_trips.py` | Trip CRUD, Join Requests |
| `tests/test_settlements.py` | Settlement algorithm (7 cases) |
| `tests/test_api.py` | All 4 API endpoints |

---

## REST API Reference

Base URL: `/api/v1`

> All endpoints require an authenticated session (same browser cookie used by the web UI).

### `GET /api/v1/trips`

Paginated list of the current user's trips (owned + joined).

**Query params:** `page` (default 1), `per_page` (default 10, max 50)

```json
{
  "data": [
    {
      "id": 1,
      "title": "Goa Getaway",
      "destination": "Goa",
      "start_date": "2025-12-01",
      "end_date": "2025-12-07",
      "status": "upcoming",
      "total_spent": 4500.0,
      "member_count": 3,
      ...
    }
  ],
  "meta": { "page": 1, "per_page": 10, "total": 1, "pages": 1 }
}
```

### `GET /api/v1/trips/<id>`

Full trip detail including members, expenses, and computed settlements.

**Responses:** `200 OK` | `403 Forbidden` (not a member) | `404 Not Found`

### `GET /api/v1/expenses`

All expenses across all the user's trips.

**Query params:** `page`, `per_page`, `trip_id` (optional filter)

### `GET /api/v1/settlements`

Computed settlement plan (minimum transfers) per trip.

**Query params:** `trip_id` (optional filter)

```json
{
  "data": [
    {
      "trip_id": 1,
      "trip_title": "Goa Getaway",
      "transfers": [
        {
          "debtor":   { "id": 3, "name": "Charlie" },
          "creditor": { "id": 1, "name": "Alice" },
          "amount": 500.0,
          "is_settled": false
        }
      ]
    }
  ]
}
```

---

## Docker

### Run with Docker Compose (recommended)

```bash
# Build and start
docker compose up --build

# App available at http://localhost:5000

# Stop
docker compose down

# Stop and remove volumes
docker compose down -v
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `change-me-in-production` | Flask secret key — **change this** |
| `DATABASE_URL` | `sqlite:///travelbuddy.db` | Database URI |
| `FLASK_ENV` | `production` | Flask environment |

Create a `.env` file for local Docker runs:

```
SECRET_KEY=your-strong-secret-key-here
DATABASE_URL=sqlite:///travelbuddy.db
```

---

## Project Structure

```
travelbuddy/
├── app/
│   ├── __init__.py          # App factory
│   ├── extensions.py        # db, bcrypt, login_manager, migrate
│   ├── models.py            # User, Trip, TripMember, Expense, Settlement
│   ├── api/                 # REST API blueprint (/api/v1)
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── auth/                # Register / Login / Logout
│   ├── dashboard/           # User dashboard
│   ├── expenses/            # Expense CRUD & settlements
│   ├── main/                # Landing page
│   ├── profile/             # User profile
│   ├── trips/               # Trip CRUD & membership
│   └── templates/           # Jinja2 HTML templates
├── tests/
│   ├── conftest.py          # Pytest fixtures
│   ├── test_auth.py
│   ├── test_trips.py
│   ├── test_settlements.py
│   └── test_api.py
├── migrations/              # Alembic migration scripts (after flask db init)
├── config.py                # Config + TestingConfig
├── run.py                   # App entry point
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .github/
    └── workflows/
        └── ci.yml           # GitHub Actions CI
```

---

## CI / CD

GitHub Actions runs two jobs on every push and pull request to `main` and `develop`:

1. **Lint** (`ruff check .`) — fails fast on style or import errors.
2. **Test + Coverage** — runs pytest; fails if coverage drops below 74%.

Coverage XML and HTML artifacts are uploaded after every run (even on failure).

Replace `<YOUR_GITHUB_USERNAME>` in the badge below with your actual GitHub username:

```markdown
[![CI](https://github.com/<YOUR_GITHUB_USERNAME>/travelbuddy/actions/workflows/ci.yml/badge.svg)](https://github.com/<YOUR_GITHUB_USERNAME>/travelbuddy/actions/workflows/ci.yml)
```

---

## Performance Improvements

| Area | Change | Impact |
|---|---|---|
| `get_active_trips()` / `get_upcoming_trips()` | JOIN query instead of IDs→re-query pattern | −1 query per call |
| `get_total_balance()` | Batch trip load with `.filter(Trip.id.in_(...))` | −N queries (one per trip) |
| `_count_unique_buddies()` | Single set-union query, no per-trip lookups | −N queries |
| `load_user()` | `db.session.get()` instead of `Query.get()` | Uses identity map cache |
| `Trip.__table_args__` | Composite index on `(owner_id, status)` | Faster dashboard queries |
| `TripMember.__table_args__` | Composite index on `(user_id, status)` + `(trip_id, status)` | Faster membership checks |
| `Expense.__table_args__` | Composite index on `(trip_id, paid_by_id)` | Faster expense filtering |
| `Settlement.__table_args__` | Composite index on `(trip_id, payer_id)` | Faster settlement lookup |
| `TripMember` | Unique constraint on `(trip_id, user_id)` | Prevents duplicate memberships at DB level |

---

## License

MIT
