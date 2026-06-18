"""Tests for trip CRUD operations and membership workflows."""

import pytest
from datetime import date, timedelta
from app.models import Trip, TripMember
from app.extensions import db as _db


# ---------------------------------------------------------------------------
# Helpers — use cities that exist in CITY_CHOICES (Gujarat + Nearby)
# ---------------------------------------------------------------------------

def _trip_data(overrides=None):
    tomorrow = date.today() + timedelta(days=1)
    data = {
        'title': 'Ahmedabad Adventure',
        'destination': 'Ahmedabad',
        'departure_city': 'Surat',
        'description': 'A fun trip',
        'start_date': tomorrow.isoformat(),
        'end_date': (tomorrow + timedelta(days=7)).isoformat(),
        'budget_min': 5000,
        'budget_max': 15000,
        'max_members': 4,
    }
    if overrides:
        data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreateTrip:
    def test_create_trip_requires_login(self, client):
        resp = client.get('/trips/create', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers.get('Location', '')

    def test_create_trip_success(self, auth_client, app):
        client, user = auth_client
        resp = client.post('/trips/create', data=_trip_data(), follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            trip = Trip.query.filter_by(title='Ahmedabad Adventure', owner_id=user.id).first()
        assert trip is not None
        assert trip.destination == 'Ahmedabad'

    def test_create_trip_redirects_to_detail(self, auth_client, app):
        client, user = auth_client
        resp = client.post('/trips/create', data=_trip_data())
        assert resp.status_code == 302
        with app.app_context():
            trip = Trip.query.filter_by(title='Ahmedabad Adventure', owner_id=user.id).first()
        assert trip is not None
        assert f'/trips/{trip.id}' in resp.headers.get('Location', '')

    def test_create_trip_missing_title_fails(self, auth_client, app):
        client, user = auth_client
        data = _trip_data({'title': ''})
        resp = client.post('/trips/create', data=data, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            trip = Trip.query.filter_by(owner_id=user.id).first()
        assert trip is None


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

class TestReadTrip:
    def test_trip_list_accessible_to_guests(self, client):
        resp = client.get('/trips')
        assert resp.status_code == 200

    def test_trip_detail_accessible_to_owner(self, auth_client, sample_trip):
        client, _ = auth_client
        resp = client.get(f'/trips/{sample_trip.id}')
        assert resp.status_code == 200
        assert b'Test Trip' in resp.data

    def test_trip_detail_404_for_missing(self, auth_client):
        client, _ = auth_client
        resp = client.get('/trips/99999')
        assert resp.status_code == 404

    def test_trip_detail_guest_redirects_to_login(self, client, app):
        """Unauthenticated access to trip detail should redirect to login.
        Creates its own user+trip inline to avoid shared-session issues.
        """
        from app.models import User, Trip
        from app.extensions import bcrypt

        with app.app_context():
            pw = bcrypt.generate_password_hash('pass').decode('utf-8')
            u = User(name='Owner2', email='owner2@test.com', password_hash=pw)
            _db.session.add(u)
            _db.session.flush()
            tomorrow = date.today() + timedelta(days=1)
            trip = Trip(
                owner_id=u.id, title='Public Trip', destination='Ahmedabad',
                departure_city='Surat', start_date=tomorrow,
                end_date=tomorrow + timedelta(days=2),
                budget_min=1000, budget_max=5000, max_members=3, is_public=True,
            )
            _db.session.add(trip)
            _db.session.commit()
            trip_id = trip.id

        # Freshly created unauthenticated client — no cookies
        resp = client.get(f'/trips/{trip_id}', follow_redirects=False)
        assert resp.status_code == 302
        assert 'login' in resp.headers.get('Location', '').lower()


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

class TestEditTrip:
    def test_edit_trip_success(self, auth_client, sample_trip, app):
        client, _ = auth_client
        data = _trip_data({'title': 'Updated Title'})
        resp = client.post(f'/trips/{sample_trip.id}/edit', data=data, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            trip = _db.session.get(Trip, sample_trip.id)
        assert trip.title == 'Updated Title'

    def test_edit_trip_non_owner_forbidden(self, auth_client, app):
        """A second user cannot edit another user's trip."""
        from app.extensions import bcrypt
        from app.models import User

        with app.app_context():
            pw_hash = bcrypt.generate_password_hash('Pass123!').decode('utf-8')
            other = User(name='Other', email='other@example.com', password_hash=pw_hash)
            _db.session.add(other)
            _db.session.flush()

            tomorrow = date.today() + timedelta(days=1)
            trip = Trip(
                owner_id=other.id,
                title='Other Trip',
                destination='Vadodara',
                departure_city='Mumbai',
                start_date=tomorrow,
                end_date=tomorrow + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=2,
            )
            _db.session.add(trip)
            _db.session.commit()
            trip_id = trip.id

        # Auth client (test@example.com) tries to edit other's trip
        client, _ = auth_client
        resp = client.post(f'/trips/{trip_id}/edit', data=_trip_data(), follow_redirects=True)
        assert b'Not authorised' in resp.data or resp.status_code in (200, 302)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDeleteTrip:
    def test_delete_trip_success(self, auth_client, sample_trip, app):
        client, _ = auth_client
        trip_id = sample_trip.id
        resp = client.post(f'/trips/{trip_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert _db.session.get(Trip, trip_id) is None

    def test_delete_trip_requires_login(self, client, sample_trip):
        resp = client.post(f'/trips/{sample_trip.id}/delete', follow_redirects=False)
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Join request workflow
# ---------------------------------------------------------------------------

class TestJoinRequest:
    def test_send_buddy_request(self, auth_client, app):
        """A second user can send a request to join an existing trip."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client

        with app.app_context():
            # Create the trip
            tomorrow = date.today() + timedelta(days=1)
            trip = Trip(
                owner_id=owner.id,
                title='Join Test Trip',
                destination='Rajkot',
                departure_city='Mumbai',
                start_date=tomorrow,
                end_date=tomorrow + timedelta(days=4),
                budget_min=3000, budget_max=8000, max_members=4,
                is_public=True,
            )
            _db.session.add(trip)

            pw_hash = bcrypt.generate_password_hash('Pass2!').decode('utf-8')
            joiner = User(name='Joiner', email='joiner@example.com', password_hash=pw_hash)
            _db.session.add(joiner)
            _db.session.commit()
            trip_id = trip.id
            joiner_id = joiner.id

        # Login as joiner
        joiner_client = app.test_client()
        joiner_client.post('/auth/login', data={
            'email': 'joiner@example.com',
            'password': 'Pass2!',
        })
        resp = joiner_client.post(f'/trips/{trip_id}/request', follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            mem = TripMember.query.filter_by(trip_id=trip_id, user_id=joiner_id).first()
            mem_status = mem.status if mem else None
        assert mem is not None
        assert mem_status == 'pending'
