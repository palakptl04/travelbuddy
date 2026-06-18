"""Tests for the REST API v1 endpoints."""

import pytest
import json
from datetime import date, timedelta
from app.models import Trip, Expense, TripMember
from app.extensions import db as _db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(resp):
    return json.loads(resp.data)


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

class TestApiUnauthorized:
    def test_trips_401_if_not_logged_in(self, client):
        resp = client.get('/api/v1/trips')
        assert resp.status_code == 401
        body = _json(resp)
        assert body['status'] == 401

    def test_trip_detail_401_if_not_logged_in(self, client):
        resp = client.get('/api/v1/trips/1')
        assert resp.status_code == 401

    def test_expenses_401_if_not_logged_in(self, client):
        resp = client.get('/api/v1/expenses')
        assert resp.status_code == 401

    def test_settlements_401_if_not_logged_in(self, client):
        resp = client.get('/api/v1/settlements')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/trips
# ---------------------------------------------------------------------------

class TestApiTripsList:
    def test_returns_200_and_json(self, auth_client, sample_trip):
        client, _ = auth_client
        resp = client.get('/api/v1/trips')
        assert resp.status_code == 200
        assert resp.content_type == 'application/json'

    def test_returns_data_and_meta_keys(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/trips'))
        assert 'data' in body
        assert 'meta' in body

    def test_trip_appears_in_list(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/trips'))
        ids = [t['id'] for t in body['data']]
        assert sample_trip.id in ids

    def test_meta_contains_pagination_fields(self, auth_client, sample_trip):
        client, _ = auth_client
        meta = _json(client.get('/api/v1/trips'))['meta']
        assert 'page' in meta
        assert 'per_page' in meta
        assert 'total' in meta
        assert 'pages' in meta

    def test_per_page_query_param_respected(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/trips?per_page=1'))
        assert body['meta']['per_page'] == 1

    def test_empty_list_for_user_with_no_trips(self, app):
        from app.extensions import bcrypt
        from app.models import User

        with app.app_context():
            pw = bcrypt.generate_password_hash('pass').decode('utf-8')
            u = User(name='Lonely', email='lonely@test.com', password_hash=pw)
            _db.session.add(u)
            _db.session.commit()

        lonely_client = app.test_client()
        lonely_client.post('/auth/login', data={'email': 'lonely@test.com', 'password': 'pass'})
        body = _json(lonely_client.get('/api/v1/trips'))
        assert body['data'] == []
        assert body['meta']['total'] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/trips/<id>
# ---------------------------------------------------------------------------

class TestApiTripDetail:
    def test_returns_200_for_owner(self, auth_client, sample_trip):
        client, _ = auth_client
        resp = client.get(f'/api/v1/trips/{sample_trip.id}')
        assert resp.status_code == 200

    def test_trip_fields_present(self, auth_client, sample_trip):
        client, _ = auth_client
        data = _json(client.get(f'/api/v1/trips/{sample_trip.id}'))['data']
        for field in ('id', 'title', 'destination', 'start_date', 'end_date',
                      'status', 'budget_min', 'budget_max', 'members',
                      'expenses', 'settlements'):
            assert field in data, f"Missing field: {field}"

    def test_returns_404_for_nonexistent_trip(self, auth_client):
        client, _ = auth_client
        resp = client.get('/api/v1/trips/99999')
        assert resp.status_code == 404

    def test_returns_403_for_non_member(self, auth_client, app):
        """A trip the user neither owns nor joined should return 403."""
        from app.extensions import bcrypt
        from app.models import User

        with app.app_context():
            pw = bcrypt.generate_password_hash('pass').decode('utf-8')
            other = User(name='OtherGuy', email='otherguy@test.com', password_hash=pw)
            _db.session.add(other)
            _db.session.flush()

            tomorrow = date.today() + timedelta(days=1)
            other_trip = Trip(
                owner_id=other.id,
                title='Private Trip',
                destination='Vadodara',
                departure_city='Mumbai',
                start_date=tomorrow,
                end_date=tomorrow + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=2,
            )
            _db.session.add(other_trip)
            _db.session.commit()
            other_trip_id = other_trip.id

        client, _ = auth_client
        resp = client.get(f'/api/v1/trips/{other_trip_id}')
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/expenses
# ---------------------------------------------------------------------------

class TestApiExpenses:
    def test_returns_200(self, auth_client, sample_trip):
        client, _ = auth_client
        resp = client.get('/api/v1/expenses')
        assert resp.status_code == 200

    def test_expense_fields_present(self, auth_client, sample_trip, app):
        _, user = auth_client
        with app.app_context():
            exp = Expense(
                trip_id=sample_trip.id,
                paid_by_id=user.id,
                title='Lunch',
                amount=250.0,
                category='food',
                date=date.today(),
            )
            _db.session.add(exp)
            _db.session.commit()

        client, _ = auth_client
        body = _json(client.get('/api/v1/expenses'))
        assert body['meta']['total'] >= 1
        item = body['data'][0]
        for field in ('id', 'trip_id', 'title', 'amount', 'category', 'date', 'paid_by'):
            assert field in item, f"Missing field: {field}"

    def test_filter_by_trip_id(self, auth_client, sample_trip, app):
        client, user = auth_client
        with app.app_context():
            exp = Expense(
                trip_id=sample_trip.id,
                paid_by_id=user.id,
                title='Hotel',
                amount=1000.0,
                category='accommodation',
                date=date.today(),
            )
            _db.session.add(exp)
            _db.session.commit()

        body = _json(client.get(f'/api/v1/expenses?trip_id={sample_trip.id}'))
        for item in body['data']:
            assert item['trip_id'] == sample_trip.id


# ---------------------------------------------------------------------------
# GET /api/v1/settlements
# ---------------------------------------------------------------------------

class TestApiSettlements:
    def test_returns_200(self, auth_client, sample_trip):
        client, _ = auth_client
        resp = client.get('/api/v1/settlements')
        assert resp.status_code == 200

    def test_returns_data_list(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/settlements'))
        assert 'data' in body
        assert isinstance(body['data'], list)

    def test_settlement_structure(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/settlements'))
        assert len(body['data']) >= 1
        entry = body['data'][0]
        assert 'trip_id' in entry
        assert 'trip_title' in entry
        assert 'transfers' in entry
