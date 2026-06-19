"""
Shared pytest fixtures for TravelBuddy.

Strategy:
- Session-scoped `app` fixture creates the Flask app + schema.
- Function-scoped `_clean_db` (autouse) truncates all tables between tests.
- Each test gets a fresh `app.test_client()` so cookie jars don't bleed.

IMPORTANT — pytest-flask context-leak fix
-----------------------------------------
pytest-flask 1.3.0 provides an autouse fixture `_push_request_context` that
pushes a test request context (and therefore an app context) for the *entire*
duration of every test function.  In Flask 3 + Flask-Login 0.6.3, the logged-in
user is cached in `g._login_user` (app-context scoped).  Because that context
stays open across all HTTP requests made inside the test, the first
`login_user()` call (e.g. the owner login in `auth_client`) permanently sets
`g._login_user` for every subsequent request in the same test — including
requests made by a *different* test client (e.g. joiner_client).  This causes:
  * joiner_client.post('/auth/login') → login() sees current_user.is_authenticated
    == True (owner) → redirects to dashboard without calling login_user(joiner)
    → joiner session stays empty.
  * joiner_client.post('/trips/…/request') → current_user is still owner (id=1)
    → "can't send request to own trip" → TripMember never created.

Fix: shadow _push_request_context with a no-op so each test_client request gets
its own isolated app+request context and Flask-Login reloads current_user from
the session cookie on every request.
"""

import pytest
from datetime import date, timedelta

from app import create_app
from app.extensions import db as _db
from config import TestingConfig


# ---------------------------------------------------------------------------
# Session-scoped: app + schema creation
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def app():
    """Flask app configured for testing with in-memory SQLite.

    IMPORTANT: We yield *outside* any app_context so that no context remains
    pushed on the stack during test execution.  A persistent app_context would
    keep a live SQLAlchemy session alive for the whole test session; Flask-Login
    would then resolve current_user against that stale, cached session instead
    of issuing a fresh DB lookup for every request, causing the wrong user to
    be returned (e.g. owner instead of joiner in send_buddy_request).
    """
    application = create_app(TestingConfig)

    # Short-lived context: only needed to create the schema.
    with application.app_context():
        _db.create_all()

    yield application

    # Short-lived context: only needed to drop the schema.
    with application.app_context():
        _db.drop_all()


# ---------------------------------------------------------------------------
# Override pytest-flask's autouse _push_request_context with a no-op.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _push_request_context(request):
    """No-op override of pytest-flask's _push_request_context.

    pytest-flask pushes a request context for the entire test duration.  In
    Flask 3, this also keeps an app context alive, so g._login_user persists
    across all requests in the test and Flask-Login cannot reload current_user
    from the session cookie.  By overriding with a no-op, every test_client
    request gets its own isolated context pair.
    """
    yield  # intentionally empty — no context pushed


# ---------------------------------------------------------------------------
# Function-scoped: truncate all rows after each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_db(app):
    yield

    with app.app_context():
        _db.session.remove()
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()

# ---------------------------------------------------------------------------
# HTTP client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(app):
    """Unauthenticated test client (fresh cookie jar per test)."""
    return app.test_client()


@pytest.fixture
def auth_client(app):
    """
    Returns (test_client, user).
    The user is created in DB and logged in. Fresh cookie jar.
    """
    from app.extensions import bcrypt
    from app.models import User

    with app.app_context():
        pw_hash = bcrypt.generate_password_hash('TestPass123!').decode('utf-8')
        user = User(
            name='Test User',
            email='test@example.com',
            password_hash=pw_hash,
        )
        _db.session.add(user)
        _db.session.commit()
        user_id = user.id

    http_client = app.test_client()
    resp = http_client.post('/auth/login', data={
        'email': 'test@example.com',
        'password': 'TestPass123!',
    }, follow_redirects=True)
    assert resp.status_code == 200, f"Login failed: {resp.status_code}"

    with app.app_context():
        user = _db.session.get(User, user_id)

    return http_client, user


@pytest.fixture
def sample_trip(auth_client, app):
    """Create a Trip owned by the authenticated test user."""
    from app.models import Trip
    _, user = auth_client
    tomorrow = date.today() + timedelta(days=1)

    with app.app_context():
        trip = Trip(
            owner_id=user.id,
            title='Test Trip',
            destination='Ahmedabad',
            departure_city='Surat',
            start_date=tomorrow,
            end_date=tomorrow + timedelta(days=5),
            budget_min=5000,
            budget_max=10000,
            max_members=4,
            status='upcoming',
            is_public=True,
        )
        _db.session.add(trip)
        _db.session.commit()
        trip_id = trip.id

    # Return a detached proxy — tests can use .id
    class TripProxy:
        def __init__(self, tid):
            self.id = tid

    return TripProxy(trip_id)
