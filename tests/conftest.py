"""
Shared pytest fixtures for TravelBuddy.

Strategy:
- Session-scoped `app` fixture creates the Flask app + schema.
- Function-scoped `_clean_db` (autouse) truncates all tables between tests.
- Each test gets a fresh `app.test_client()` so cookie jars don't bleed.
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
    """Flask app configured for testing with in-memory SQLite."""
    application = create_app(TestingConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


# ---------------------------------------------------------------------------
# Function-scoped: truncate all rows after each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_db(app):
    """Truncate every table after each test to isolate state."""
    with app.app_context():
        yield
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
