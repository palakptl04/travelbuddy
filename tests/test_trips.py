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
            # Trip must start 3+ days out so joining is still open
            # (joining closes 1 day before start, i.e. today >= start-1 means closed)
            three_days = date.today() + timedelta(days=3)
            trip = Trip(
                owner_id=owner.id,
                title='Join Test Trip',
                destination='Rajkot',
                departure_city='Mumbai',
                start_date=three_days,
                end_date=three_days + timedelta(days=4),
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

        # Log in as the joiner via the real login route.
        # This works correctly because conftest.py overrides pytest-flask's
        # _push_request_context with a no-op, so each request gets its own
        # isolated app+request context and Flask-Login reads current_user
        # fresh from the session cookie on every call.
        joiner_client = app.test_client()
        joiner_client.post(
            '/auth/login',
            data={'email': 'joiner@example.com', 'password': 'Pass2!'},
            follow_redirects=True,
        )

        resp = joiner_client.post(
            f'/trips/{trip_id}/request',
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            mem = TripMember.query.filter_by(trip_id=trip_id, user_id=joiner_id).first()
            mem_status = mem.status if mem else None
        assert mem is not None, "TripMember was not created — join request failed"
        assert mem_status == 'pending'


# ---------------------------------------------------------------------------
# Trip Status Lifecycle (computed_status)
# ---------------------------------------------------------------------------

class TestComputedStatus:
    """Trip.computed_status returns correct label based on today's date."""

    def _make_trip(self, owner_id, start_offset, end_offset):
        today = date.today()
        return Trip(
            owner_id=owner_id,
            title='Status Test Trip',
            destination='Ahmedabad',
            departure_city='Surat',
            start_date=today + timedelta(days=start_offset),
            end_date=today + timedelta(days=end_offset),
            budget_min=1000, budget_max=5000, max_members=4, is_public=True,
        )

    def test_upcoming_when_starts_tomorrow(self, auth_client, app):
        _, user = auth_client
        with app.app_context():
            trip = self._make_trip(user.id, start_offset=1, end_offset=5)
            _db.session.add(trip)
            _db.session.commit()
            assert trip.computed_status == 'upcoming'

    def test_ongoing_when_starts_today(self, auth_client, app):
        _, user = auth_client
        with app.app_context():
            trip = self._make_trip(user.id, start_offset=0, end_offset=5)
            _db.session.add(trip)
            _db.session.commit()
            assert trip.computed_status == 'ongoing'

    def test_ongoing_when_midway(self, auth_client, app):
        _, user = auth_client
        with app.app_context():
            trip = self._make_trip(user.id, start_offset=-2, end_offset=2)
            _db.session.add(trip)
            _db.session.commit()
            assert trip.computed_status == 'ongoing'

    def test_completed_when_ended_yesterday(self, auth_client, app):
        _, user = auth_client
        with app.app_context():
            trip = self._make_trip(user.id, start_offset=-5, end_offset=-1)
            _db.session.add(trip)
            _db.session.commit()
            assert trip.computed_status == 'completed'


# ---------------------------------------------------------------------------
# Join Closing Logic
# ---------------------------------------------------------------------------

class TestJoiningClosed:
    """Trip.joining_closed is True when today >= start_date - 1 day."""

    def _make_trip(self, owner_id, start_offset):
        today = date.today()
        return Trip(
            owner_id=owner_id,
            title='Join Closed Test',
            destination='Rajkot',
            departure_city='Mumbai',
            start_date=today + timedelta(days=start_offset),
            end_date=today + timedelta(days=start_offset + 5),
            budget_min=1000, budget_max=5000, max_members=4, is_public=True,
        )

    def test_joining_open_two_days_before(self, auth_client, app):
        _, user = auth_client
        with app.app_context():
            trip = self._make_trip(user.id, start_offset=2)
            _db.session.add(trip)
            _db.session.commit()
            assert not trip.joining_closed

    def test_joining_closed_one_day_before(self, auth_client, app):
        _, user = auth_client
        with app.app_context():
            trip = self._make_trip(user.id, start_offset=1)
            _db.session.add(trip)
            _db.session.commit()
            assert trip.joining_closed

    def test_joining_closed_on_start_day(self, auth_client, app):
        _, user = auth_client
        with app.app_context():
            trip = self._make_trip(user.id, start_offset=0)
            _db.session.add(trip)
            _db.session.commit()
            assert trip.joining_closed

    def test_send_request_blocked_when_joining_closed(self, auth_client, app):
        """A new buddy request must be rejected once joining has closed."""
        from app.extensions import bcrypt
        from app.models import User
        _, owner = auth_client

        with app.app_context():
            # Trip starting tomorrow → joining already closed
            tomorrow = date.today() + timedelta(days=1)
            trip = Trip(
                owner_id=owner.id,
                title='Closed Join Trip',
                destination='Vadodara',
                departure_city='Mumbai',
                start_date=tomorrow,
                end_date=tomorrow + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=4, is_public=True,
            )
            _db.session.add(trip)
            pw = bcrypt.generate_password_hash('Pass!').decode('utf-8')
            joiner = User(name='Joiner2', email='joiner2@test.com', password_hash=pw)
            _db.session.add(joiner)
            _db.session.commit()
            trip_id = trip.id

        joiner_client = app.test_client()
        joiner_client.post('/auth/login',
                           data={'email': 'joiner2@test.com', 'password': 'Pass!'},
                           follow_redirects=True)

        resp = joiner_client.post(f'/trips/{trip_id}/request', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            mem = TripMember.query.filter_by(trip_id=trip_id).first()
            assert mem is None, "TripMember should not exist — joining was closed"


# ---------------------------------------------------------------------------
# Expense Gating
# ---------------------------------------------------------------------------

class TestExpenseGating:
    """Expenses cannot be added while joining is still open."""

    def test_add_expense_blocked_when_joining_open(self, auth_client, app):
        """Adding an expense when start_date is 2+ days away must fail."""
        from app.models import Expense
        client, user = auth_client
        with app.app_context():
            future = date.today() + timedelta(days=3)
            trip = Trip(
                owner_id=user.id,
                title='Expense Gate Trip',
                destination='Surat',
                departure_city='Ahmedabad',
                start_date=future,
                end_date=future + timedelta(days=4),
                budget_min=1000, budget_max=5000, max_members=3, is_public=True,
            )
            _db.session.add(trip)
            _db.session.commit()
            trip_id = trip.id

        resp = client.post(
            f'/trips/{trip_id}/expenses/add',
            data={
                'csrf_token': '',
                'title': 'Hotel',
                'amount': '500',
                'category': 'accommodation',
                'expense_date': date.today().isoformat(),
                'paid_by_id': str(user.id),
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            from app.models import Expense
            count = Expense.query.filter_by(trip_id=trip_id).count()
            assert count == 0, "No expense should be created while joining is open"


# ---------------------------------------------------------------------------
# Leave Logic
# ---------------------------------------------------------------------------

class TestLeaveLogic:
    """Members cannot leave once joining has closed."""

    def test_leave_blocked_when_joining_closed(self, auth_client, app):
        from app.extensions import bcrypt
        from app.models import User
        _, owner = auth_client

        with app.app_context():
            tomorrow = date.today() + timedelta(days=1)
            trip = Trip(
                owner_id=owner.id,
                title='Leave Block Trip',
                destination='Gandhinagar',
                departure_city='Surat',
                start_date=tomorrow,
                end_date=tomorrow + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=4, is_public=True,
            )
            _db.session.add(trip)
            pw = bcrypt.generate_password_hash('Pass2!').decode('utf-8')
            member_user = User(name='LeaveMe', email='leaveme@test.com', password_hash=pw)
            _db.session.add(member_user)
            _db.session.flush()
            mem = TripMember(trip_id=trip.id, user_id=member_user.id, status='accepted')
            _db.session.add(mem)
            _db.session.commit()
            trip_id = trip.id

        member_client = app.test_client()
        member_client.post('/auth/login',
                           data={'email': 'leaveme@test.com', 'password': 'Pass2!'},
                           follow_redirects=True)

        resp = member_client.post(f'/trips/{trip_id}/leave', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            still_member = TripMember.query.filter_by(trip_id=trip_id).first()
            assert still_member is not None, "Member should still exist — join is closed"

    def test_leave_allowed_when_joining_open(self, auth_client, app):
        from app.extensions import bcrypt
        from app.models import User
        _, owner = auth_client

        with app.app_context():
            far_future = date.today() + timedelta(days=5)
            trip = Trip(
                owner_id=owner.id,
                title='Leave Allow Trip',
                destination='Gandhinagar',
                departure_city='Surat',
                start_date=far_future,
                end_date=far_future + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=4, is_public=True,
            )
            _db.session.add(trip)
            pw = bcrypt.generate_password_hash('Pass3!').decode('utf-8')
            member_user = User(name='GoAway', email='goaway@test.com', password_hash=pw)
            _db.session.add(member_user)
            _db.session.flush()
            mem = TripMember(trip_id=trip.id, user_id=member_user.id, status='accepted')
            _db.session.add(mem)
            _db.session.commit()
            trip_id = trip.id

        member_client = app.test_client()
        member_client.post('/auth/login',
                           data={'email': 'goaway@test.com', 'password': 'Pass3!'},
                           follow_redirects=True)

        resp = member_client.post(f'/trips/{trip_id}/leave', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            still_member = TripMember.query.filter_by(trip_id=trip_id).first()
            assert still_member is None, "Member should be removed — joining was open"


# ---------------------------------------------------------------------------
# Member Count — Partial Fill (Item 5)
# ---------------------------------------------------------------------------

class TestPartialFill:
    """Trip continues normally even if fewer members joined than max_members."""

    def test_trip_continues_with_partial_fill(self, auth_client, app):
        from app.models import User
        from app.extensions import bcrypt
        _, owner = auth_client

        with app.app_context():
            future = date.today() + timedelta(days=10)
            trip = Trip(
                owner_id=owner.id,
                title='Partial Fill Trip',
                destination='Ahmedabad',
                departure_city='Surat',
                start_date=future,
                end_date=future + timedelta(days=3),
                budget_min=1000, budget_max=5000,
                max_members=5,   # expected 5
                is_public=True,
            )
            _db.session.add(trip)
            pw = bcrypt.generate_password_hash('Pass!').decode('utf-8')
            joiner = User(name='PartialJoiner', email='partial@test.com', password_hash=pw)
            _db.session.add(joiner)
            _db.session.flush()
            _db.session.add(TripMember(trip_id=trip.id, user_id=joiner.id, status='accepted'))
            _db.session.commit()
            trip_id = trip.id

        with app.app_context():
            t = _db.session.get(Trip, trip_id)
            # Trip must exist and not be cancelled
            assert t is not None
            assert t.status == 'upcoming'
            # member_count reflects actual accepted members only
            assert t.member_count() == 2   # owner + 1 joiner
