"""
Tests for the REST API v1 endpoints.

Covers:
 - Unauthenticated access (401)
 - JWT token endpoint (POST /api/v1/auth/token)
 - API-key auth (X-API-Key header)
 - CRUD for trips (GET list, GET detail, POST, PUT, PATCH, DELETE)
 - CRUD for expenses (GET list, GET detail, POST, PUT, PATCH, DELETE)
 - Settlements (GET)
 - bfcache Cache-Control headers on web routes
"""

import json
from datetime import date, timedelta

from app.extensions import db as _db
from app.models import Expense, Trip, User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(resp):
    return json.loads(resp.data)


def _trip_payload(offset_days=5):
    start = date.today() + timedelta(days=offset_days)
    return {
        'title':          'API Test Trip',
        'destination':    'Manali',
        'departure_city': 'Delhi',
        'start_date':     start.isoformat(),
        'end_date':       (start + timedelta(days=3)).isoformat(),
        'budget_min':     3000,
        'budget_max':     8000,
        'max_members':    4,
        'is_public':      True,
    }


# ---------------------------------------------------------------------------
# JWT token endpoint
# ---------------------------------------------------------------------------

class TestTokenEndpoint:
    def test_valid_credentials_return_token(self, auth_client):
        client, _ = auth_client
        resp = client.post(
            '/api/v1/auth/token',
            json={'email': 'test@example.com', 'password': 'TestPass123!'},
            content_type='application/json',
        )
        assert resp.status_code == 200
        body = _json(resp)
        assert 'token' in body
        assert body['token_type'] == 'Bearer'
        assert 'expires_in' in body

    def test_invalid_password_returns_401(self, client):
        resp = client.post(
            '/api/v1/auth/token',
            json={'email': 'nobody@example.com', 'password': 'wrong'},
            content_type='application/json',
        )
        assert resp.status_code == 401

    def test_missing_body_returns_401(self, client):
        resp = client.post('/api/v1/auth/token', json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# JWT bearer auth
# ---------------------------------------------------------------------------

class TestJWTBearerAuth:
    def _get_token(self, client):
        resp = client.post(
            '/api/v1/auth/token',
            json={'email': 'test@example.com', 'password': 'TestPass123!'},
            content_type='application/json',
        )
        return _json(resp)['token']

    def test_bearer_token_allows_access(self, auth_client, sample_trip):
        client, _ = auth_client
        token = self._get_token(client)
        resp = client.get(
            '/api/v1/trips',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert resp.status_code == 200

    def test_invalid_token_returns_401(self, client):
        resp = client.get(
            '/api/v1/trips',
            headers={'Authorization': 'Bearer totally.invalid.token'},
        )
        assert resp.status_code == 401

    def test_malformed_header_returns_401(self, client):
        resp = client.get(
            '/api/v1/trips',
            headers={'Authorization': 'Token notjwt'},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# API-key auth
# ---------------------------------------------------------------------------

class TestApiKeyAuth:
    def test_rotate_api_key_returns_key(self, auth_client):
        client, _ = auth_client
        resp = client.post('/api/v1/me/api-key', content_type='application/json')
        assert resp.status_code == 200
        body = _json(resp)
        assert 'api_key' in body
        assert len(body['api_key']) == 64

    def test_api_key_header_allows_access(self, auth_client, sample_trip):
        client, user = auth_client
        # Generate a key first
        resp = client.post('/api/v1/me/api-key')
        api_key = _json(resp)['api_key']

        # New unauthenticated client uses the key
        fresh = client.application.test_client()
        resp2 = fresh.get(
            '/api/v1/trips',
            headers={'X-API-Key': api_key},
        )
        assert resp2.status_code == 200

    def test_invalid_api_key_returns_401(self, client):
        resp = client.get(
            '/api/v1/trips',
            headers={'X-API-Key': 'aaaa' * 16},
        )
        assert resp.status_code == 401

    def test_get_api_key_shows_masked(self, auth_client):
        client, _ = auth_client
        # No key yet
        resp = client.get('/api/v1/me/api-key')
        body = _json(resp)
        assert body['has_key'] is False

        # After generating
        client.post('/api/v1/me/api-key')
        resp2 = client.get('/api/v1/me/api-key')
        body2 = _json(resp2)
        assert body2['has_key'] is True
        assert '…' in body2['key_prefix']


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
        assert client.get('/api/v1/trips/1').status_code == 401

    def test_expenses_401_if_not_logged_in(self, client):
        assert client.get('/api/v1/expenses').status_code == 401

    def test_settlements_401_if_not_logged_in(self, client):
        assert client.get('/api/v1/settlements').status_code == 401

    def test_create_trip_401_if_not_logged_in(self, client):
        resp = client.post('/api/v1/trips', json=_trip_payload())
        assert resp.status_code == 401

    def test_create_expense_401_if_not_logged_in(self, client):
        resp = client.post('/api/v1/expenses', json={'trip_id': 1, 'title': 'x', 'amount': 100})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/trips  (list)
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
        assert 'data' in body and 'meta' in body

    def test_trip_appears_in_list(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/trips'))
        ids = [t['id'] for t in body['data']]
        assert sample_trip.id in ids

    def test_meta_pagination_fields(self, auth_client, sample_trip):
        client, _ = auth_client
        meta = _json(client.get('/api/v1/trips'))['meta']
        for key in ('page', 'per_page', 'total', 'pages'):
            assert key in meta

    def test_per_page_respected(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/trips?per_page=1'))
        assert body['meta']['per_page'] == 1

    def test_status_filter(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/trips?status=OPEN'))
        assert all(t['status'] == 'OPEN' for t in body['data'])

    def test_empty_for_user_with_no_trips(self, app):
        with app.app_context():
            from app.extensions import bcrypt as _bcrypt
            pw = _bcrypt.generate_password_hash('pass').decode('utf-8')
            u = User(name='Lonely', email='lonely@test.com', password_hash=pw)
            _db.session.add(u)
            _db.session.commit()

        lonely = app.test_client()
        lonely.post('/auth/login', data={'email': 'lonely@test.com', 'password': 'pass'})
        body = _json(lonely.get('/api/v1/trips'))
        assert body['data'] == [] and body['meta']['total'] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/trips  (create)
# ---------------------------------------------------------------------------

class TestApiTripsCreate:
    def test_create_returns_201(self, auth_client):
        client, _ = auth_client
        resp = client.post('/api/v1/trips', json=_trip_payload(),
                           content_type='application/json')
        assert resp.status_code == 201
        assert _json(resp)['data']['title'] == 'API Test Trip'

    def test_create_missing_fields_returns_400(self, auth_client):
        client, _ = auth_client
        resp = client.post('/api/v1/trips', json={'title': 'Only Title'},
                           content_type='application/json')
        assert resp.status_code == 400

    def test_create_bad_dates_returns_400(self, auth_client):
        client, _ = auth_client
        payload = _trip_payload()
        payload['end_date'] = (date.today() - timedelta(days=10)).isoformat()
        payload['start_date'] = date.today().isoformat()
        resp = client.post('/api/v1/trips', json=payload, content_type='application/json')
        assert resp.status_code == 400

    def test_create_not_json_returns_400(self, auth_client):
        client, _ = auth_client
        resp = client.post('/api/v1/trips', data='not json',
                           content_type='text/plain')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/v1/trips/<id>  (detail)
# ---------------------------------------------------------------------------

class TestApiTripDetail:
    def test_returns_200_for_owner(self, auth_client, sample_trip):
        client, _ = auth_client
        assert client.get(f'/api/v1/trips/{sample_trip.id}').status_code == 200

    def test_all_fields_present(self, auth_client, sample_trip):
        client, _ = auth_client
        data = _json(client.get(f'/api/v1/trips/{sample_trip.id}'))['data']
        for field in ('id', 'title', 'destination', 'start_date', 'end_date',
                      'status', 'budget_min', 'budget_max', 'members',
                      'expenses', 'settlements'):
            assert field in data, f'Missing field: {field}'

    def test_returns_404_for_nonexistent(self, auth_client):
        client, _ = auth_client
        assert client.get('/api/v1/trips/99999').status_code == 404

    def test_returns_403_for_non_member(self, auth_client, app):
        with app.app_context():
            from app.extensions import bcrypt as _bcrypt
            pw = _bcrypt.generate_password_hash('pass').decode('utf-8')
            other = User(name='OtherGuy', email='other2@test.com', password_hash=pw)
            _db.session.add(other)
            _db.session.flush()
            start = date.today() + timedelta(days=1)
            trip = Trip(
                owner_id=other.id, title='Private', destination='Vapi',
                departure_city='Surat', start_date=start,
                end_date=start + timedelta(days=3),
                budget_min=1000, budget_max=5000, max_members=2,
            )
            _db.session.add(trip)
            _db.session.commit()
            tid = trip.id

        client, _ = auth_client
        assert client.get(f'/api/v1/trips/{tid}').status_code == 403


# ---------------------------------------------------------------------------
# PUT /api/v1/trips/<id>  (full update)
# ---------------------------------------------------------------------------

class TestApiTripsUpdate:
    def test_put_updates_trip(self, auth_client, sample_trip):
        client, _ = auth_client
        payload = _trip_payload(offset_days=10)
        payload['title'] = 'Updated Title'
        resp = client.put(f'/api/v1/trips/{sample_trip.id}', json=payload,
                          content_type='application/json')
        assert resp.status_code == 200
        assert _json(resp)['data']['title'] == 'Updated Title'

    def test_put_by_non_owner_returns_403(self, auth_client, app):
        with app.app_context():
            from app.extensions import bcrypt as _bcrypt
            pw = _bcrypt.generate_password_hash('pass').decode('utf-8')
            other = User(name='Attacker', email='attacker@test.com', password_hash=pw)
            _db.session.add(other)
            _db.session.flush()
            start = date.today() + timedelta(days=1)
            trip = Trip(
                owner_id=other.id, title='Their Trip', destination='Pune',
                departure_city='Mumbai', start_date=start,
                end_date=start + timedelta(days=2),
                budget_min=0, budget_max=0, max_members=2,
            )
            _db.session.add(trip)
            _db.session.commit()
            tid = trip.id

        client, _ = auth_client
        payload = _trip_payload()
        resp = client.put(f'/api/v1/trips/{tid}', json=payload,
                          content_type='application/json')
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /api/v1/trips/<id>  (partial update)
# ---------------------------------------------------------------------------

class TestApiTripsPatch:
    def test_patch_updates_single_field(self, auth_client, sample_trip):
        client, _ = auth_client
        resp = client.patch(
            f'/api/v1/trips/{sample_trip.id}',
            json={'description': 'A fun patch test'},
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert _json(resp)['data']['description'] == 'A fun patch test'

    def test_patch_returns_400_on_bad_dates(self, auth_client, sample_trip):
        client, _ = auth_client
        resp = client.patch(
            f'/api/v1/trips/{sample_trip.id}',
            json={'end_date': '2000-01-01'},
            content_type='application/json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/v1/trips/<id>
# ---------------------------------------------------------------------------

class TestApiTripsDelete:
    def test_delete_returns_204(self, auth_client, sample_trip):
        client, _ = auth_client
        resp = client.delete(f'/api/v1/trips/{sample_trip.id}')
        assert resp.status_code == 204
        assert resp.data == b''

    def test_delete_removes_trip(self, auth_client, sample_trip, app):
        client, _ = auth_client
        client.delete(f'/api/v1/trips/{sample_trip.id}')
        assert client.get(f'/api/v1/trips/{sample_trip.id}').status_code == 404

    def test_delete_by_non_owner_returns_403(self, auth_client, app):
        with app.app_context():
            from app.extensions import bcrypt as _bcrypt
            pw = _bcrypt.generate_password_hash('pass').decode('utf-8')
            other = User(name='Intruder', email='intruder@test.com', password_hash=pw)
            _db.session.add(other)
            _db.session.flush()
            start = date.today() + timedelta(days=1)
            trip = Trip(
                owner_id=other.id, title='Theirs', destination='Lonavala',
                departure_city='Pune', start_date=start,
                end_date=start + timedelta(days=2),
                budget_min=0, budget_max=0, max_members=2,
            )
            _db.session.add(trip)
            _db.session.commit()
            tid = trip.id

        client, _ = auth_client
        assert client.delete(f'/api/v1/trips/{tid}').status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/expenses  (list)
# ---------------------------------------------------------------------------

class TestApiExpensesList:
    def test_returns_200(self, auth_client, sample_trip):
        client, _ = auth_client
        assert client.get('/api/v1/expenses').status_code == 200

    def test_expense_fields_present(self, auth_client, sample_trip, app):
        _, user = auth_client
        with app.app_context():
            exp = Expense(
                trip_id=sample_trip.id, paid_by_id=user.id,
                title='Lunch', amount=250.0, category='food', date=date.today(),
            )
            _db.session.add(exp)
            _db.session.commit()

        client, _ = auth_client
        body = _json(client.get('/api/v1/expenses'))
        assert body['meta']['total'] >= 1
        item = body['data'][0]
        for field in ('id', 'trip_id', 'title', 'amount', 'category', 'date', 'paid_by'):
            assert field in item, f'Missing field: {field}'

    def test_filter_by_trip_id(self, auth_client, sample_trip, app):
        client, user = auth_client
        with app.app_context():
            exp = Expense(
                trip_id=sample_trip.id, paid_by_id=user.id,
                title='Hotel', amount=1000.0, category='accommodation', date=date.today(),
            )
            _db.session.add(exp)
            _db.session.commit()

        body = _json(client.get(f'/api/v1/expenses?trip_id={sample_trip.id}'))
        assert all(e['trip_id'] == sample_trip.id for e in body['data'])

    def test_filter_by_category(self, auth_client, sample_trip, app):
        client, user = auth_client
        with app.app_context():
            _db.session.add(Expense(
                trip_id=sample_trip.id, paid_by_id=user.id,
                title='Taxi', amount=150.0, category='transport', date=date.today(),
            ))
            _db.session.commit()

        body = _json(client.get('/api/v1/expenses?category=transport'))
        assert all(e['category'] == 'transport' for e in body['data'])


# ---------------------------------------------------------------------------
# POST /api/v1/expenses  (create)
# ---------------------------------------------------------------------------

class TestApiExpensesCreate:
    def _make_active_trip(self, app, user_id):
        """Create an ACTIVE trip so expenses can be added."""
        with app.app_context():
            today = date.today()
            trip = Trip(
                owner_id=user_id, title='Active Trip', destination='Shimla',
                departure_city='Chandigarh', start_date=today - timedelta(days=1),
                end_date=today + timedelta(days=2),
                budget_min=0, budget_max=0, max_members=4, status='ACTIVE',
            )
            _db.session.add(trip)
            _db.session.commit()
            return trip.id

    def test_create_expense_returns_201(self, auth_client, app):
        client, user = auth_client
        tid = self._make_active_trip(app, user.id)
        resp = client.post(
            '/api/v1/expenses',
            json={'trip_id': tid, 'title': 'Dinner', 'amount': 500.0, 'category': 'food'},
            content_type='application/json',
        )
        assert resp.status_code == 201
        data = _json(resp)['data']
        assert data['title'] == 'Dinner'
        assert data['amount'] == 500.0

    def test_create_expense_on_open_trip_returns_400(self, auth_client, sample_trip):
        """OPEN trips don't allow expenses."""
        client, _ = auth_client
        resp = client.post(
            '/api/v1/expenses',
            json={'trip_id': sample_trip.id, 'title': 'x', 'amount': 100},
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_create_expense_missing_fields_returns_400(self, auth_client, app):
        client, user = auth_client
        tid = self._make_active_trip(app, user.id)
        resp = client.post(
            '/api/v1/expenses',
            json={'trip_id': tid},
            content_type='application/json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/v1/expenses/<id>  (detail)
# ---------------------------------------------------------------------------

class TestApiExpenseDetail:
    def _create_active_expense(self, app, user_id):
        with app.app_context():
            today = date.today()
            trip = Trip(
                owner_id=user_id, title='Trip', destination='X',
                departure_city='Y', start_date=today - timedelta(days=1),
                end_date=today + timedelta(days=1),
                budget_min=0, budget_max=0, max_members=4, status='ACTIVE',
            )
            _db.session.add(trip)
            _db.session.flush()
            exp = Expense(
                trip_id=trip.id, paid_by_id=user_id,
                title='Bus', amount=200.0, category='transport', date=today,
            )
            _db.session.add(exp)
            _db.session.commit()
            return exp.id

    def test_get_expense_detail(self, auth_client, app):
        client, user = auth_client
        eid = self._create_active_expense(app, user.id)
        resp = client.get(f'/api/v1/expenses/{eid}')
        assert resp.status_code == 200
        assert _json(resp)['data']['id'] == eid

    def test_get_nonexistent_expense_404(self, auth_client):
        client, _ = auth_client
        assert client.get('/api/v1/expenses/99999').status_code == 404


# ---------------------------------------------------------------------------
# PUT / PATCH / DELETE expenses
# ---------------------------------------------------------------------------

class TestApiExpensesMutate:
    def _setup(self, app, user_id):
        with app.app_context():
            today = date.today()
            trip = Trip(
                owner_id=user_id, title='Mutate Trip', destination='Z',
                departure_city='W', start_date=today - timedelta(days=1),
                end_date=today + timedelta(days=2),
                budget_min=0, budget_max=0, max_members=4, status='ACTIVE',
            )
            _db.session.add(trip)
            _db.session.flush()
            exp = Expense(
                trip_id=trip.id, paid_by_id=user_id,
                title='Original', amount=100.0, category='general', date=today,
            )
            _db.session.add(exp)
            _db.session.commit()
            return trip.id, exp.id

    def test_put_expense_updates(self, auth_client, app):
        client, user = auth_client
        tid, eid = self._setup(app, user.id)
        resp = client.put(
            f'/api/v1/expenses/{eid}',
            json={'trip_id': tid, 'title': 'Updated', 'amount': 999.0},
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert _json(resp)['data']['amount'] == 999.0

    def test_patch_expense_updates_single_field(self, auth_client, app):
        client, user = auth_client
        _, eid = self._setup(app, user.id)
        resp = client.patch(
            f'/api/v1/expenses/{eid}',
            json={'amount': 777.0},
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert _json(resp)['data']['amount'] == 777.0

    def test_delete_expense(self, auth_client, app):
        client, user = auth_client
        _, eid = self._setup(app, user.id)
        assert client.delete(f'/api/v1/expenses/{eid}').status_code == 204
        assert client.get(f'/api/v1/expenses/{eid}').status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/settlements
# ---------------------------------------------------------------------------

class TestApiSettlements:
    def test_returns_200(self, auth_client, sample_trip):
        client, _ = auth_client
        assert client.get('/api/v1/settlements').status_code == 200

    def test_returns_data_list(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/settlements'))
        assert 'data' in body and isinstance(body['data'], list)

    def test_settlement_structure(self, auth_client, sample_trip):
        client, _ = auth_client
        body = _json(client.get('/api/v1/settlements'))
        assert len(body['data']) >= 1
        entry = body['data'][0]
        for key in ('trip_id', 'trip_title', 'transfers'):
            assert key in entry


# ---------------------------------------------------------------------------
# bfcache — Cache-Control headers on web routes
# ---------------------------------------------------------------------------

class TestBfcacheCacheControl:
    def test_dashboard_has_no_store(self, auth_client):
        client, _ = auth_client
        resp = client.get('/dashboard')
        cc = resp.headers.get('Cache-Control', '')
        assert 'no-store' in cc

    def test_login_page_has_no_store(self, client):
        resp = client.get('/auth/login')
        cc = resp.headers.get('Cache-Control', '')
        assert 'no-store' in cc

    def test_logout_redirect_has_no_store(self, auth_client):
        client, _ = auth_client
        resp = client.get('/auth/logout')
        cc = resp.headers.get('Cache-Control', '')
        assert 'no-store' in cc

    def test_api_routes_not_affected(self, auth_client, sample_trip):
        """API responses should NOT have Cache-Control: no-store injected by web hook."""
        client, _ = auth_client
        resp = client.get('/api/v1/trips')
        # API responses may have their own cache headers but NOT the web no-store
        # (the after_request hook skips /api/ paths)
        assert resp.status_code == 200
        assert 'no-store' not in resp.headers.get('Cache-Control', '')
