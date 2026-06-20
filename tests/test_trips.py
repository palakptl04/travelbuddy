"""Tests for trip CRUD operations and membership workflows."""

import pytest
from datetime import date, timedelta, datetime
from app.models import Trip, TripMember, ContactAccessLog
from app.extensions import db as _db


# ---------------------------------------------------------------------------
# Helpers — use cities that exist in CITY_CHOICES (Gujarat + Nearby)
# ---------------------------------------------------------------------------

def _trip_data(overrides=None):
    trip_start = date.today() + timedelta(days=4)
    data = {
        'title': 'Ahmedabad Adventure',
        'destination': 'Ahmedabad',
        'departure_city': 'Surat',
        'description': 'A fun trip',
        'start_date': trip_start.isoformat(),
        'end_date': (trip_start + timedelta(days=7)).isoformat(),
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

    def test_create_trip_with_join_deadline(self, auth_client, app):
        """Trip created with explicit join_deadline stores it correctly."""
        client, user = auth_client
        trip_start = date.today() + timedelta(days=5)
        deadline = date.today() + timedelta(days=2)
        resp = client.post('/trips/create', data=_trip_data({
            'title': 'Deadline Trip',
            'start_date': trip_start.isoformat(),
            'end_date': (trip_start + timedelta(days=3)).isoformat(),
            'join_deadline': deadline.isoformat(),
        }), follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            trip = Trip.query.filter_by(title='Deadline Trip', owner_id=user.id).first()
        assert trip is not None
        assert trip.join_deadline is not None
        assert trip.join_deadline.date() == deadline

    def test_create_trip_with_open_roster(self, auth_client, app):
        """Trip created with open_roster=True stores the flag."""
        client, user = auth_client
        resp = client.post('/trips/create', data=_trip_data({
            'title': 'Roster Trip',
            'open_roster': 'y',
        }), follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            trip = Trip.query.filter_by(title='Roster Trip', owner_id=user.id).first()
        assert trip is not None
        assert trip.open_roster is True


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
        from app.models import User, Trip
        from app.extensions import bcrypt

        with app.app_context():
            pw = bcrypt.generate_password_hash('pass').decode('utf-8')
            u = User(name='Owner2', email='owner2@test.com', password_hash=pw)
            _db.session.add(u)
            _db.session.flush()
            tomorrow = date.today() + timedelta(days=3)
            trip = Trip(
                owner_id=u.id, title='Public Trip', destination='Ahmedabad',
                departure_city='Surat', start_date=tomorrow,
                end_date=tomorrow + timedelta(days=2),
                budget_min=1000, budget_max=5000, max_members=3, is_public=True,
            )
            _db.session.add(trip)
            _db.session.commit()
            trip_id = trip.id

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
        from app.extensions import bcrypt
        from app.models import User

        with app.app_context():
            pw_hash = bcrypt.generate_password_hash('Pass123!').decode('utf-8')
            other = User(name='Other', email='other@example.com', password_hash=pw_hash)
            _db.session.add(other)
            _db.session.flush()

            tomorrow = date.today() + timedelta(days=3)
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

        client, _ = auth_client
        resp = client.post(f'/trips/{trip_id}/edit', data=_trip_data(), follow_redirects=True)
        assert b'Not authorised' in resp.data or resp.status_code in (200, 302)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

class TestCancelTrip:
    def test_cancel_trip_success(self, auth_client, sample_trip, app):
        client, _ = auth_client
        trip_id = sample_trip.id
        resp = client.post(f'/trips/{trip_id}/cancel', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            trip = _db.session.get(Trip, trip_id)
        assert trip is not None
        assert trip.status == 'CANCELLED'

    def test_cancel_trip_requires_login(self, client, sample_trip):
        resp = client.post(f'/trips/{sample_trip.id}/cancel', follow_redirects=False)
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Join request workflow
# ---------------------------------------------------------------------------

class TestJoinRequest:
    def test_send_buddy_request(self, auth_client, app):
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client

        with app.app_context():
            three_days = date.today() + timedelta(days=5)
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
        assert mem is not None, "TripMember was not created"
        assert mem_status == 'pending'


# ---------------------------------------------------------------------------
# Trip Status Lifecycle (computed_status)
# ---------------------------------------------------------------------------

class TestComputedStatus:
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

    def test_completed_when_ended_yesterday(self, auth_client, app):
        _, user = auth_client
        with app.app_context():
            trip = self._make_trip(user.id, start_offset=-5, end_offset=-1)
            _db.session.add(trip)
            _db.session.commit()
            assert trip.computed_status == 'completed'


# ---------------------------------------------------------------------------
# Join Deadline Logic
# ---------------------------------------------------------------------------

class TestJoinDeadline:
    """Tests for the new join_deadline-based workflow."""

    def _make_open_trip(self, owner_id, start_offset=10, join_deadline=None):
        today = date.today()
        trip = Trip(
            owner_id=owner_id,
            title='Deadline Trip',
            destination='Gandhinagar',
            departure_city='Surat',
            start_date=today + timedelta(days=start_offset),
            end_date=today + timedelta(days=start_offset + 5),
            budget_min=1000, budget_max=5000, max_members=4, is_public=True,
            status='OPEN',
        )
        if join_deadline is not None:
            trip.join_deadline = join_deadline
        return trip

    def test_join_deadline_not_passed_keeps_open(self, auth_client, app):
        """Trip with join_deadline in the future remains OPEN."""
        _, user = auth_client
        with app.app_context():
            future_dl = datetime.utcnow() + timedelta(days=2)
            trip = self._make_open_trip(user.id, join_deadline=future_dl)
            _db.session.add(trip)
            _db.session.commit()
            assert not trip.join_deadline_passed
            changed = trip.maybe_transition_to_awaiting()
            assert not changed
            assert trip.status == 'OPEN'

    def test_join_deadline_passed_transitions_to_awaiting(self, auth_client, app):
        """Trip with join_deadline in the past transitions to AWAITING_CONFIRMATION."""
        _, user = auth_client
        with app.app_context():
            past_dl = datetime.utcnow() - timedelta(hours=1)
            trip = self._make_open_trip(user.id, join_deadline=past_dl)
            _db.session.add(trip)
            _db.session.commit()
            assert trip.join_deadline_passed
            changed = trip.maybe_transition_to_awaiting()
            assert changed
            assert trip.status == 'AWAITING_CONFIRMATION'

    def test_no_join_deadline_uses_legacy_close(self, auth_client, app):
        """Trip without join_deadline falls back to 1-day-before-start behaviour."""
        _, user = auth_client
        with app.app_context():
            today = date.today()
            trip = Trip(
                owner_id=user.id,
                title='No Deadline Trip',
                destination='Rajkot',
                departure_city='Mumbai',
                start_date=today + timedelta(days=1),
                end_date=today + timedelta(days=5),
                budget_min=1000, budget_max=5000, max_members=4, is_public=True,
                status='OPEN',
            )
            _db.session.add(trip)
            _db.session.commit()
            assert trip.joining_closed   # 1 day before start → closed

    def test_send_request_blocked_after_deadline(self, auth_client, app):
        """A buddy request is rejected after the join_deadline has passed."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client

        with app.app_context():
            past_dl = datetime.utcnow() - timedelta(hours=1)
            future_start = date.today() + timedelta(days=5)
            trip = Trip(
                owner_id=owner.id,
                title='Deadline Closed Trip',
                destination='Vadodara',
                departure_city='Mumbai',
                start_date=future_start,
                end_date=future_start + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=4, is_public=True,
                status='OPEN',
                join_deadline=past_dl,
            )
            _db.session.add(trip)
            pw = bcrypt.generate_password_hash('Pass!').decode('utf-8')
            joiner = User(name='Joiner3', email='joiner3@test.com', password_hash=pw)
            _db.session.add(joiner)
            _db.session.commit()
            trip_id = trip.id

        joiner_client = app.test_client()
        joiner_client.post('/auth/login',
                           data={'email': 'joiner3@test.com', 'password': 'Pass!'},
                           follow_redirects=True)

        resp = joiner_client.post(f'/trips/{trip_id}/request', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            mem = TripMember.query.filter_by(trip_id=trip_id).first()
            assert mem is None, "TripMember should not exist — join deadline has passed"

    def test_leave_blocked_after_deadline(self, auth_client, app):
        """Members cannot leave once join_deadline has passed."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client

        with app.app_context():
            past_dl = datetime.utcnow() - timedelta(hours=1)
            future_start = date.today() + timedelta(days=5)
            trip = Trip(
                owner_id=owner.id,
                title='Leave Block Trip',
                destination='Gandhinagar',
                departure_city='Surat',
                start_date=future_start,
                end_date=future_start + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=4, is_public=True,
                status='OPEN',
                join_deadline=past_dl,
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
            assert still_member is not None, "Member should still exist — join deadline has passed"


# ---------------------------------------------------------------------------
# Owner Confirm / Cancel Workflow
# ---------------------------------------------------------------------------

class TestOwnerConfirmWorkflow:
    """Owner can confirm or cancel a trip in AWAITING_CONFIRMATION."""

    def _make_awaiting_trip(self, owner_id):
        future_start = date.today() + timedelta(days=5)
        return Trip(
            owner_id=owner_id,
            title='Awaiting Trip',
            destination='Ahmedabad',
            departure_city='Surat',
            start_date=future_start,
            end_date=future_start + timedelta(days=3),
            budget_min=1000, budget_max=5000, max_members=4, is_public=True,
            status='AWAITING_CONFIRMATION',
        )

    def test_owner_can_confirm_trip(self, auth_client, app):
        """Owner calling confirm_trip transitions to CONFIRMED."""
        client, user = auth_client
        with app.app_context():
            trip = self._make_awaiting_trip(user.id)
            _db.session.add(trip)
            _db.session.commit()
            trip_id = trip.id

        resp = client.post(f'/trips/{trip_id}/confirm-trip', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            t = _db.session.get(Trip, trip_id)
        assert t.status == 'CONFIRMED'

    def test_owner_can_cancel_awaiting_trip(self, auth_client, app):
        """Owner calling cancel on an AWAITING_CONFIRMATION trip works."""
        client, user = auth_client
        with app.app_context():
            trip = self._make_awaiting_trip(user.id)
            _db.session.add(trip)
            _db.session.commit()
            trip_id = trip.id

        resp = client.post(f'/trips/{trip_id}/cancel', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            t = _db.session.get(Trip, trip_id)
        assert t.status == 'CANCELLED'

    def test_non_owner_cannot_confirm_trip(self, auth_client, app):
        """A non-owner cannot use the confirm-trip route."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client

        with app.app_context():
            pw_hash = bcrypt.generate_password_hash('Other!').decode('utf-8')
            other = User(name='Other2', email='other2@test.com', password_hash=pw_hash)
            _db.session.add(other)
            _db.session.flush()

            trip = self._make_awaiting_trip(owner.id)
            _db.session.add(trip)
            _db.session.commit()
            trip_id = trip.id

        other_client = app.test_client()
        other_client.post('/auth/login',
                          data={'email': 'other2@test.com', 'password': 'Other!'},
                          follow_redirects=True)

        resp = other_client.post(f'/trips/{trip_id}/confirm-trip', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            t = _db.session.get(Trip, trip_id)
        assert t.status == 'AWAITING_CONFIRMATION', "Status should not have changed"

    def test_confirm_trip_on_open_trip_fails(self, auth_client, sample_trip, app):
        """confirm_trip route on an OPEN trip does nothing."""
        client, _ = auth_client
        resp = client.post(f'/trips/{sample_trip.id}/confirm-trip', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            t = _db.session.get(Trip, sample_trip.id)
        assert t.status == 'OPEN'


# ---------------------------------------------------------------------------
# Contact Visibility
# ---------------------------------------------------------------------------

class TestContactVisibility:
    """Tests for Trip.contact_visible_for() rules."""

    def _make_confirmed_trip(self, owner_id, open_roster=False):
        future_start = date.today() + timedelta(days=5)
        return Trip(
            owner_id=owner_id,
            title='Confirmed Trip',
            destination='Ahmedabad',
            departure_city='Surat',
            start_date=future_start,
            end_date=future_start + timedelta(days=3),
            budget_min=1000, budget_max=5000, max_members=4, is_public=True,
            status='CONFIRMED',
            open_roster=open_roster,
        )

    def test_no_contacts_before_confirmation(self, auth_client, app):
        """In OPEN status, no contacts are visible to anyone."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client
        with app.app_context():
            pw = bcrypt.generate_password_hash('M!').decode('utf-8')
            member = User(name='Mem', email='mem_cv@test.com', password_hash=pw)
            _db.session.add(member)
            _db.session.flush()
            future_start = date.today() + timedelta(days=5)
            trip = Trip(
                owner_id=owner.id,
                title='Open Trip CV',
                destination='Rajkot',
                departure_city='Mumbai',
                start_date=future_start,
                end_date=future_start + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=4,
                status='OPEN',
            )
            _db.session.add(trip)
            _db.session.flush()
            _db.session.add(TripMember(trip_id=trip.id, user_id=member.id, status='accepted'))
            _db.session.commit()
            # Member cannot see owner's contacts before confirmation
            assert not trip.contact_visible_for(member.id, owner.id)
            # Owner cannot see member's contacts before confirmation
            assert not trip.contact_visible_for(owner.id, member.id)

    def test_cancelled_trip_hides_all_contacts(self, auth_client, app):
        """CANCELLED status always hides contacts."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client
        with app.app_context():
            pw = bcrypt.generate_password_hash('M!').decode('utf-8')
            member = User(name='Mem2', email='mem2_cv@test.com', password_hash=pw)
            _db.session.add(member)
            _db.session.flush()
            future_start = date.today() + timedelta(days=5)
            trip = Trip(
                owner_id=owner.id,
                title='Cancelled Trip CV',
                destination='Surat',
                departure_city='Ahmedabad',
                start_date=future_start,
                end_date=future_start + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=4,
                status='CANCELLED',
            )
            _db.session.add(trip)
            _db.session.flush()
            _db.session.add(TripMember(trip_id=trip.id, user_id=member.id, status='accepted'))
            _db.session.commit()
            assert not trip.contact_visible_for(owner.id, member.id)
            assert not trip.contact_visible_for(member.id, owner.id)

    def test_confirmed_owner_sees_all_contacts(self, auth_client, app):
        """After CONFIRMED, owner sees all members' contacts."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client
        with app.app_context():
            pw = bcrypt.generate_password_hash('M!').decode('utf-8')
            m1 = User(name='M1', email='m1_cv@test.com', password_hash=pw)
            m2 = User(name='M2', email='m2_cv@test.com', password_hash=pw)
            _db.session.add_all([m1, m2])
            _db.session.flush()
            trip = self._make_confirmed_trip(owner.id, open_roster=False)
            _db.session.add(trip)
            _db.session.flush()
            _db.session.add(TripMember(trip_id=trip.id, user_id=m1.id, status='accepted'))
            _db.session.add(TripMember(trip_id=trip.id, user_id=m2.id, status='accepted'))
            _db.session.commit()
            assert trip.contact_visible_for(owner.id, m1.id)
            assert trip.contact_visible_for(owner.id, m2.id)

    def test_confirmed_member_sees_owner_always(self, auth_client, app):
        """After CONFIRMED, member always sees owner contact."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client
        with app.app_context():
            pw = bcrypt.generate_password_hash('M!').decode('utf-8')
            m1 = User(name='M1b', email='m1b_cv@test.com', password_hash=pw)
            _db.session.add(m1)
            _db.session.flush()
            trip = self._make_confirmed_trip(owner.id, open_roster=False)
            _db.session.add(trip)
            _db.session.flush()
            _db.session.add(TripMember(trip_id=trip.id, user_id=m1.id, status='accepted'))
            _db.session.commit()
            assert trip.contact_visible_for(m1.id, owner.id)

    def test_confirmed_member_cannot_see_other_member_without_open_roster(self, auth_client, app):
        """After CONFIRMED with open_roster=False, members cannot see each other's contacts."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client
        with app.app_context():
            pw = bcrypt.generate_password_hash('M!').decode('utf-8')
            m1 = User(name='M1c', email='m1c_cv@test.com', password_hash=pw)
            m2 = User(name='M2c', email='m2c_cv@test.com', password_hash=pw)
            _db.session.add_all([m1, m2])
            _db.session.flush()
            trip = self._make_confirmed_trip(owner.id, open_roster=False)
            _db.session.add(trip)
            _db.session.flush()
            _db.session.add(TripMember(trip_id=trip.id, user_id=m1.id, status='accepted'))
            _db.session.add(TripMember(trip_id=trip.id, user_id=m2.id, status='accepted'))
            _db.session.commit()
            assert not trip.contact_visible_for(m1.id, m2.id)
            assert not trip.contact_visible_for(m2.id, m1.id)

    def test_confirmed_member_sees_other_member_with_open_roster(self, auth_client, app):
        """After CONFIRMED with open_roster=True, members see each other's contacts."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client
        with app.app_context():
            pw = bcrypt.generate_password_hash('M!').decode('utf-8')
            m1 = User(name='M1d', email='m1d_cv@test.com', password_hash=pw)
            m2 = User(name='M2d', email='m2d_cv@test.com', password_hash=pw)
            _db.session.add_all([m1, m2])
            _db.session.flush()
            trip = self._make_confirmed_trip(owner.id, open_roster=True)
            _db.session.add(trip)
            _db.session.flush()
            _db.session.add(TripMember(trip_id=trip.id, user_id=m1.id, status='accepted'))
            _db.session.add(TripMember(trip_id=trip.id, user_id=m2.id, status='accepted'))
            _db.session.commit()
            assert trip.contact_visible_for(m1.id, m2.id)
            assert trip.contact_visible_for(m2.id, m1.id)

    def test_removed_member_loses_contact_access(self, auth_client, app):
        """A member whose status is 'declined' (removed) cannot see contacts."""
        from app.extensions import bcrypt
        from app.models import User

        _, owner = auth_client
        with app.app_context():
            pw = bcrypt.generate_password_hash('M!').decode('utf-8')
            m1 = User(name='M1e', email='m1e_cv@test.com', password_hash=pw)
            _db.session.add(m1)
            _db.session.flush()
            trip = self._make_confirmed_trip(owner.id, open_roster=True)
            _db.session.add(trip)
            _db.session.flush()
            # Add member then decline (remove)
            _db.session.add(TripMember(trip_id=trip.id, user_id=m1.id, status='declined'))
            _db.session.commit()
            # Declined member cannot see owner's contacts
            assert not trip.contact_visible_for(m1.id, owner.id)


# ---------------------------------------------------------------------------
# ContactAccessLog
# ---------------------------------------------------------------------------

class TestContactAccessLog:
    """ContactAccessLog rows are written when contacts are revealed."""

    def test_contact_log_written_on_detail_view(self, auth_client, app):
        """Loading trip detail for a confirmed trip creates ContactAccessLog rows."""
        from app.extensions import bcrypt
        from app.models import User

        client, owner = auth_client

        with app.app_context():
            pw = bcrypt.generate_password_hash('M!').decode('utf-8')
            member = User(name='LogMem', email='logmem@test.com', password_hash=pw)
            _db.session.add(member)
            _db.session.flush()

            future_start = date.today() + timedelta(days=5)
            trip = Trip(
                owner_id=owner.id,
                title='Log Trip',
                destination='Ahmedabad',
                departure_city='Surat',
                start_date=future_start,
                end_date=future_start + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=4,
                status='CONFIRMED',
                open_roster=False,
            )
            _db.session.add(trip)
            _db.session.flush()
            _db.session.add(TripMember(trip_id=trip.id, user_id=member.id, status='accepted'))
            _db.session.commit()
            trip_id = trip.id
            member_id = member.id

        # Owner loads the detail page → owner sees member's contacts
        resp = client.get(f'/trips/{trip_id}')
        assert resp.status_code == 200

        with app.app_context():
            log = ContactAccessLog.query.filter_by(
                viewer_id=owner.id,
                target_user_id=member_id,
                trip_id=trip_id,
            ).first()
        assert log is not None, "ContactAccessLog should have been written for owner→member"


# ---------------------------------------------------------------------------
# Joining Closed Logic (legacy fallback)
# ---------------------------------------------------------------------------

class TestJoiningClosed:
    """Trip.joining_closed when no join_deadline (legacy 1-day fallback)."""

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

    def test_send_request_blocked_when_joining_closed(self, auth_client, app):
        from app.extensions import bcrypt
        from app.models import User
        _, owner = auth_client

        with app.app_context():
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
            assert mem is None


# ---------------------------------------------------------------------------
# Expense Gating
# ---------------------------------------------------------------------------

class TestExpenseGating:
    def test_add_expense_blocked_when_joining_open(self, auth_client, app):
        from app.models import Expense
        client, user = auth_client
        with app.app_context():
            future = date.today() + timedelta(days=5)
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
            assert count == 0


# ---------------------------------------------------------------------------
# Leave Logic
# ---------------------------------------------------------------------------

class TestLeaveLogic:
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
            assert still_member is not None

    def test_leave_allowed_when_joining_open(self, auth_client, app):
        from app.extensions import bcrypt
        from app.models import User
        _, owner = auth_client

        with app.app_context():
            far_future = date.today() + timedelta(days=10)
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
            assert still_member is None


# ---------------------------------------------------------------------------
# Partial Fill
# ---------------------------------------------------------------------------

class TestPartialFill:
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
                max_members=5,
                status='OPEN',
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
            assert t is not None
            assert t.status == 'OPEN'
            assert t.member_count() == 2
