# TravelBuddy — Resume & Interview Improvement Guide

> **Context:** Full-stack Flask app with SQLAlchemy, Flask-Login, WTForms, Bcrypt, CSRF.
> Features: user auth, trip CRUD, buddy-request flow, equal-split expense tracking, Splitwise-style greedy settlement algorithm, per-trip settlement marking.

---

## 🏆 Priority Matrix

| Improvement | Effort | Interview Impact | TCS Prime Signal |
|---|---|---|---|
| Fix N+1 query bugs | Low | ⭐⭐⭐⭐⭐ | ✅ |
| Add a REST API layer (`/api/v1`) | Medium | ⭐⭐⭐⭐⭐ | ✅ |
| Write unit + integration tests | Medium | ⭐⭐⭐⭐⭐ | ✅ |
| Proper config hierarchy (Dev/Prod) | Low | ⭐⭐⭐⭐ | ✅ |
| Add `db.Index` & pagination | Low | ⭐⭐⭐⭐ | ✅ |
| Migrate to Flask-Migrate (Alembic) | Low | ⭐⭐⭐⭐ | ✅ |
| JWT-based API auth | Medium | ⭐⭐⭐⭐ | ✅ |
| Redis caching for dashboard | High | ⭐⭐⭐ | ✅ |
| GitHub Actions CI pipeline | Low | ⭐⭐⭐⭐ | ✅ |
| Dockerize the app | Low | ⭐⭐⭐⭐ | ✅ |
| Custom error pages (404, 500) | Low | ⭐⭐ | - |
| Expense split strategies | High | ⭐⭐⭐ | - |

---

## 🔴 Critical Fixes (Do These First)

### 1. Eliminate N+1 Query Bugs — _Most Common Interview Gotcha_

**Current problem:** `_count_unique_buddies` in `dashboard/routes.py` runs a `Trip.query.get()` inside a loop — that's a query for every trip the user has.

```python
# ❌ CURRENT — N+1 queries
owners = [Trip.query.get(tid).owner_id for tid in all_trip_ids
          if Trip.query.get(tid) and Trip.query.get(tid).owner_id != user.id]
```

```python
# ✅ FIX — single query with joinedload
from sqlalchemy.orm import joinedload

def _count_unique_buddies(user):
    all_trip_ids = user._all_trip_ids()
    if not all_trip_ids:
        return 0
    trips = Trip.query.filter(Trip.id.in_(all_trip_ids)).all()
    members = TripMember.query.filter(
        TripMember.trip_id.in_(all_trip_ids),
        TripMember.status == 'accepted',
        TripMember.user_id != user.id
    ).all()
    unique = set([m.user_id for m in members] + [t.owner_id for t in trips if t.owner_id != user.id])
    return len(unique)
```

**Also fix in `models.py`:** `get_active_trips()` does `TripMember.query` then a separate `Trip.query` — use a JOIN:

```python
# ✅ Better approach using join
def get_active_trips(self):
    from sqlalchemy import or_
    return (Trip.query
        .outerjoin(TripMember, (TripMember.trip_id == Trip.id) & (TripMember.user_id == self.id))
        .filter(
            or_(Trip.owner_id == self.id, TripMember.status == 'accepted'),
            Trip.status == 'active'
        ).distinct().all())
```

> **Why this matters for interviews:** N+1 is the #1 database performance question. Demonstrating you spotted and fixed it shows senior-level awareness.

---

### 2. Add Database Indexes

`models.py` has no indexes beyond primary keys. Add these to dramatically improve query performance at scale:

```python
# In models.py — add to each model's class body:

class Trip(db.Model):
    __table_args__ = (
        db.Index('ix_trips_owner_status', 'owner_id', 'status'),
        db.Index('ix_trips_destination', 'destination'),
        db.Index('ix_trips_public_date', 'is_public', 'start_date'),
    )

class TripMember(db.Model):
    __table_args__ = (
        db.Index('ix_trip_members_user_status', 'user_id', 'status'),
        db.UniqueConstraint('trip_id', 'user_id', name='uq_trip_member'),
    )

class Expense(db.Model):
    __table_args__ = (
        db.Index('ix_expenses_trip_date', 'trip_id', 'date'),
        db.Index('ix_expenses_paid_by', 'paid_by_id'),
    )

class Settlement(db.Model):
    __table_args__ = (
        db.Index('ix_settlements_trip_payer', 'trip_id', 'payer_id'),
        db.UniqueConstraint('trip_id', 'payer_id', 'payee_id', name='uq_settlement'),
    )
```

> The `UniqueConstraint` on `TripMember` also prevents a race-condition bug: currently two simultaneous requests could create duplicate membership rows.

---

### 3. Fix Config — Use Environment-Aware Classes

**Current `config.py` is 7 lines with a hardcoded fallback secret.** Replace with:

```python
# config.py
import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'change-me-in-production'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///travelbuddy.db')
    # Security headers
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = True  # Logs every SQL query — great for finding N+1s

class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True  # HTTPS only

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
```

Update `__init__.py` to use: `app.config.from_object(config[os.environ.get('FLASK_ENV', 'default')])`

---

## 🟡 High-Impact Additions (Resume Differentiators)

### 4. Add a REST API Layer (`/api/v1/`)

This is the **single biggest signal** for TCS Prime/product interviews. Shows you understand:
- REST conventions
- Separation of concerns (HTML routes vs. JSON API)
- Token-based auth

**Create `app/api/` blueprint:**

```python
# app/api/trips.py
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.models import Trip, TripMember
from app.extensions import db

api_trips = Blueprint('api_trips', __name__, url_prefix='/api/v1/trips')

@api_trips.route('/', methods=['GET'])
@login_required
def list_trips():
    """GET /api/v1/trips?page=1&per_page=10&status=active"""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 50)
    status = request.args.get('status')

    query = Trip.query.filter_by(is_public=True)
    if status:
        query = query.filter_by(status=status)

    paginated = query.order_by(Trip.start_date.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'trips': [trip_to_dict(t) for t in paginated.items],
        'total': paginated.total,
        'pages': paginated.pages,
        'page': paginated.page
    })

@api_trips.route('/<int:trip_id>', methods=['GET'])
@login_required
def get_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    return jsonify(trip_to_dict(trip))

def trip_to_dict(trip):
    return {
        'id': trip.id,
        'title': trip.title,
        'destination': trip.destination,
        'start_date': trip.start_date.isoformat(),
        'end_date': trip.end_date.isoformat(),
        'budget_min': trip.budget_min,
        'budget_max': trip.budget_max,
        'member_count': trip.member_count(),
        'max_members': trip.max_members,
        'status': trip.status,
        'owner': {'id': trip.owner.id, 'name': trip.owner.name}
    }
```

Also add `/api/v1/expenses/`, `/api/v1/settlements/` similarly.

> **Interview talking point:** "I added a RESTful JSON API layer so the same backend can serve a mobile app or third-party integrations without changes to the HTML views."

---

### 5. Add Flask-Migrate (Alembic) — Critical for Production Readiness

Currently `db.create_all()` is called in `__init__.py`. This **cannot update existing tables** — you'd lose data on every schema change.

```bash
pip install Flask-Migrate
```

```python
# app/extensions.py
from flask_migrate import Migrate
migrate = Migrate()

# app/__init__.py
from app.extensions import migrate
migrate.init_app(app, db)
# Remove: db.create_all()
```

```bash
# One-time setup
flask db init
flask db migrate -m "initial schema"
flask db upgrade
```

> **Why this matters:** Every production Flask app uses Alembic migrations. Not having it is a red flag. Interviewers will specifically ask about this.

---

### 6. Write Tests (pytest)

Zero tests = immediate shortlisting concern. Add `tests/` with at minimum:

```python
# tests/conftest.py
import pytest
from app import create_app
from app.extensions import db as _db

@pytest.fixture(scope='session')
def app():
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def auth_client(client, app):
    """A client logged in as a test user."""
    with app.app_context():
        from app.models import User
        from app.extensions import bcrypt, db
        user = User(name='Test', email='test@test.com',
                    password_hash=bcrypt.generate_password_hash('password').decode())
        db.session.add(user)
        db.session.commit()
    client.post('/auth/login', data={'email': 'test@test.com', 'password': 'password'})
    return client
```

```python
# tests/test_auth.py
def test_register_success(client):
    resp = client.post('/auth/register', data={
        'name': 'Alice', 'email': 'alice@example.com',
        'password': 'SecurePass1!', 'confirm_password': 'SecurePass1!'
    }, follow_redirects=True)
    assert resp.status_code == 200

def test_login_invalid_password(client):
    resp = client.post('/auth/login', data={
        'email': 'nobody@example.com', 'password': 'wrong'
    })
    assert b'Invalid email or password' in resp.data

# tests/test_settlement_algorithm.py
def test_greedy_settlement_minimises_transactions(app):
    """The Splitwise greedy algorithm should produce minimum transfers."""
    with app.app_context():
        # ... create users, trip, expenses, assert settlements
        pass
```

```python
# tests/test_models.py
def test_settlement_algorithm_zero_expenses(app):
    """No expenses → no settlements."""
    with app.app_context():
        from app.models import Trip, User
        # ... verify calculate_settlements() returns []
        pass
```

> **Minimum viable test suite for resume:** auth tests, settlement algorithm unit test, trip CRUD, and one API endpoint test. That's 10-15 tests and a massive differentiator.

---

### 7. Add Pagination to Browse Trips

The current `/trips` route fetches **all** public trips with no limit. At scale this would crash:

```python
# trips/routes.py
browse_trips = query.order_by(Trip.start_date.asc()).paginate(
    page=request.args.get('page', 1, type=int),
    per_page=12,
    error_out=False
)
# Pass browse_trips.items to template, browse_trips for pagination controls
```

---

### 8. Add a `Dockerfile` + `docker-compose.yml`

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV FLASK_ENV=production
EXPOSE 8000
CMD ["gunicorn", "-w", "4", "-b", "0:8000", "run:app"]
```

```yaml
# docker-compose.yml
version: '3.9'
services:
  web:
    build: .
    ports: ["8000:8000"]
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - DATABASE_URL=sqlite:///travelbuddy.db
    volumes:
      - ./instance:/app/instance
```

> **Signal:** Shows awareness of deployment and 12-factor app principles.

---

### 9. Add GitHub Actions CI

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt pytest
      - run: pytest tests/ -v
```

---

## 🟢 Code Quality Improvements (Interview Discussion Points)

### 10. Add Custom Error Handlers

```python
# In app/__init__.py, after registering blueprints:
@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403

@app.errorhandler(500)
def server_error(e):
    db.session.rollback()  # Critical: rollback failed transactions
    return render_template('errors/500.html'), 500
```

---

### 11. Use `abort()` Instead of Redirect on Authorization Failures

```python
# ❌ Current
flash('Not authorised to edit this trip.', 'error')
return redirect(url_for('trips.detail', trip_id=trip.id))

# ✅ Correct HTTP semantics
from flask import abort
if trip.owner_id != current_user.id:
    abort(403)
```

> **Why:** Returning a 302 redirect for unauthorized access is incorrect HTTP — servers should return 403. Interviewers notice this.

---

### 12. Replace Deprecated `Query.get()` with `db.session.get()`

SQLAlchemy 2.0 deprecates `Model.query.get()`:

```python
# ❌ Deprecated (shows up as warnings)
trip = Trip.query.get_or_404(trip_id)
member = TripMember.query.get(int(user_id))

# ✅ Modern SQLAlchemy 2.x style
trip = db.get_or_404(Trip, trip_id)
member = db.session.get(TripMember, int(user_id))
```

---

### 13. Add `note` Field to Expense & `description` to Settlement

Minimal schema improvements that unlock real-world use cases:

```python
class Expense(db.Model):
    note = db.Column(db.Text, default='')          # "Receipt #1234", "Split 3 ways"
    receipt_url = db.Column(db.String(255), default='')  # optional image URL

class Settlement(db.Model):
    note = db.Column(db.String(255), default='')   # "Paid via UPI", "Cash"
```

---

### 14. Add `__all__` Exports & Type Hints

```python
# models.py — add type hints to methods
from typing import List

def all_member_users(self) -> List['User']:
    ...

def calculate_settlements(self) -> List[dict]:
    ...
```

---

## 💬 Key Interview Talking Points

Use these when explaining the project:

### Architecture
> "I used the Application Factory pattern with Blueprints to keep the codebase modular — auth, trips, expenses, dashboard are all independent modules that can be tested in isolation."

### The Settlement Algorithm
> "For expense settlement I implemented a Greedy Minimum-Transfers algorithm — the same approach Splitwise uses. It works by separating members into net creditors and debtors, then greedily matching the largest debt to the largest credit, minimising the total number of transactions. For N members it runs in O(N log N) due to the sort."

### Security
> "CSRF protection is applied globally via Flask-WTF. Passwords are hashed with bcrypt (adaptive cost factor). The `paid_by_id` field is forced server-side to `current_user.id` to prevent form tampering — client-submitted values are ignored."

### Database Design
> "The Settlement model acts as an audit log — it persists *who marked what as settled and when*, which is separate from the computed settlement recommendations from `calculate_settlements()`. This lets us handle partial payments and unmark settled debts if needed."

---

## 📋 Suggested `README.md` Sections

A missing or thin README is an instant shortlisting negative. Include:

```markdown
## Features
- Trip creation & buddy-request workflow
- Equal-split expense tracking across all trip members
- Greedy minimum-transfers settlement algorithm (Splitwise-style, O(N log N))
- Per-trip settlement tracking with audit timestamps
- CSRF-protected forms, bcrypt password hashing

## Tech Stack
Flask 3.x · SQLAlchemy · Flask-Login · WTForms · SQLite/PostgreSQL · Bcrypt

## Setup
```bash
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
flask db upgrade        # or: python run.py (auto-creates tables)
python seed.py          # load sample data
flask run
```

## Running Tests
```bash
pytest tests/ -v
```

## API Endpoints (v1)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/v1/trips | List public trips (paginated) |
| GET | /api/v1/trips/:id | Get trip detail |
| POST | /api/v1/trips | Create trip |
```

---

## ✅ Quick-Win Checklist

- [ ] Fix `_count_unique_buddies` N+1 query
- [ ] Replace `Query.get()` with `db.session.get()` throughout
- [ ] Replace redirect-on-403 with `abort(403)`  
- [ ] Add `__table_args__` indexes + `UniqueConstraint` on `TripMember`
- [ ] Add `DevelopmentConfig` / `ProductionConfig` / `TestingConfig`
- [ ] Add `Flask-Migrate` and generate initial migration
- [ ] Write 10–15 pytest tests (auth + settlement algorithm + trip CRUD)
- [ ] Add `/api/v1/trips` JSON endpoint with pagination
- [ ] Add custom `404.html` and `500.html` with `db.session.rollback()`
- [ ] Add `Dockerfile` + `docker-compose.yml`
- [ ] Add `.github/workflows/ci.yml` GitHub Actions
- [ ] Write a proper `README.md` with setup, features, and API docs
