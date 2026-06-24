"""
TravelBuddy REST API v1 — Full CRUD with JWT / API-Key / Session auth.

Base URL: /api/v1
Swagger UI: /api/docs/

Authentication (choose one header per request):
  - Authorization: Bearer <jwt_token>
  - X-API-Key: <api_key>
  - Session cookie (same as web UI — for browser clients)
"""

from datetime import date as _date

from flask import abort, jsonify, request
from marshmallow import EXCLUDE, Schema, ValidationError, fields, validate

from app.api import api_v1
from app.api.auth_utils import generate_token, require_api_auth
from app.extensions import bcrypt, db
from app.models import Expense, Trip, TripMember, User

# ===========================================================================
# Marshmallow schemas  (request validation)
# ===========================================================================

class TripCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    title           = fields.Str(required=True, validate=validate.Length(min=1, max=150))
    destination     = fields.Str(required=True, validate=validate.Length(min=1, max=150))
    departure_city  = fields.Str(load_default='', validate=validate.Length(max=100))
    start_date      = fields.Date(required=True)
    end_date        = fields.Date(required=True)
    description     = fields.Str(load_default='')
    budget_min      = fields.Float(load_default=0.0, validate=validate.Range(min=0))
    budget_max      = fields.Float(load_default=0.0, validate=validate.Range(min=0))
    max_members     = fields.Int(load_default=4, validate=validate.Range(min=2, max=50))
    is_public       = fields.Bool(load_default=True)
    open_roster     = fields.Bool(load_default=False)


class TripUpdateSchema(TripCreateSchema):
    # All fields optional for PATCH; TripCreateSchema fields stay required for PUT
    title           = fields.Str(validate=validate.Length(min=1, max=150))
    destination     = fields.Str(validate=validate.Length(min=1, max=150))
    start_date      = fields.Date()
    end_date        = fields.Date()


class ExpenseCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    trip_id   = fields.Int(required=True)
    title     = fields.Str(required=True, validate=validate.Length(min=1, max=150))
    amount    = fields.Float(required=True, validate=validate.Range(min=0.01))
    category  = fields.Str(load_default='general', validate=validate.Length(max=50))
    date      = fields.Date(load_default=None)


class ExpenseUpdateSchema(ExpenseCreateSchema):
    trip_id   = fields.Int()
    title     = fields.Str(validate=validate.Length(min=1, max=150))
    amount    = fields.Float(validate=validate.Range(min=0.01))


# ===========================================================================
# Serialisation helpers
# ===========================================================================

def _trip_to_dict(trip: Trip) -> dict:
    """Minimal trip representation."""
    return {
        'id':              trip.id,
        'title':           trip.title,
        'destination':     trip.destination,
        'departure_city':  trip.departure_city,
        'start_date':      trip.start_date.isoformat(),
        'end_date':        trip.end_date.isoformat(),
        'status':          trip.status,
        'computed_status': trip.computed_status,
        'joining_closed':  trip.joining_closed,
        'status_label':    trip.status_label,
        'is_public':       trip.is_public,
        'open_roster':     trip.open_roster,
        'budget_min':      trip.budget_min,
        'budget_max':      trip.budget_max,
        'max_members':     trip.max_members,
        'member_count':    trip.member_count(),
        'total_spent':     trip.total_spent(),
        'description':     trip.description,
        'created_at':      trip.created_at.isoformat(),
        'owner': {
            'id':   trip.owner.id,
            'name': trip.owner.name,
        },
    }


def _expense_to_dict(expense: Expense) -> dict:
    return {
        'id':         expense.id,
        'trip_id':    expense.trip_id,
        'title':      expense.title,
        'amount':     expense.amount,
        'category':   expense.category,
        'date':       expense.date.isoformat(),
        'paid_by': {
            'id':   expense.paid_by.id,
            'name': expense.paid_by.name,
        },
        'created_at': expense.created_at.isoformat(),
    }


def _validate_json(schema: Schema) -> dict:
    """Parse + validate JSON body; abort 400 on error."""
    body = request.get_json(silent=True)
    if body is None:
        abort(400, description='Request body must be valid JSON with Content-Type: application/json')
    try:
        return schema.load(body)
    except ValidationError as exc:
        abort(400, description=str(exc.messages))


def _assert_trip_ownership(trip: Trip, user: User):
    """Abort 403 if the user is not the trip owner."""
    if trip.owner_id != user.id:
        abort(403)


def _assert_trip_access(trip: Trip, user: User):
    """Abort 403 if the user is neither owner nor accepted member."""
    is_owner = trip.owner_id == user.id
    membership = TripMember.query.filter_by(trip_id=trip.id, user_id=user.id).first()
    is_member = is_owner or (membership is not None and membership.status == 'accepted')
    if not is_member:
        abort(403)


def _assert_active_trip_membership(trip: Trip, user: User):
    """Abort 403 if the user is not currently an active member (owner or
    accepted member) of the trip.  Used for expense write operations to
    prevent ex-members (status='left'/'declined') from mutating expenses
    they originally paid."""
    is_owner = trip.owner_id == user.id
    if is_owner:
        return  # owners always retain full access
    membership = TripMember.query.filter_by(trip_id=trip.id, user_id=user.id).first()
    if membership is None or membership.status != 'accepted':
        abort(403)


# ===========================================================================
# Auth — token endpoint
# ===========================================================================

@api_v1.route('/auth/token', methods=['POST'])
def get_token():
    """
    Obtain a JWT bearer token.
    ---
    tags:
      - Authentication
    consumes:
      - application/json
    parameters:
      - in: body
        name: credentials
        required: true
        schema:
          type: object
          required: [email, password]
          properties:
            email:
              type: string
              example: user@example.com
            password:
              type: string
              example: MyPassword123
    responses:
      200:
        description: JWT token issued
        schema:
          type: object
          properties:
            token:
              type: string
            expires_in:
              type: integer
            token_type:
              type: string
      401:
        description: Invalid credentials
    """
    body = request.get_json(silent=True) or {}
    email = (body.get('email') or '').lower().strip()
    password = body.get('password') or ''

    user = User.query.filter_by(email=email).first()
    if not user or not bcrypt.check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password', 'status': 401}), 401

    from flask import current_app
    expiry = current_app.config.get('JWT_EXPIRY_SECONDS', 3600)
    token = generate_token(user.id)
    return jsonify({
        'token':      token,
        'token_type': 'Bearer',
        'expires_in': expiry,
        'user': {'id': user.id, 'name': user.name, 'email': user.email},
    }), 200


# ===========================================================================
# API-key management
# ===========================================================================

@api_v1.route('/me/api-key', methods=['GET'])
def get_api_key():
    """
    View the current user's API key (masked if set).
    ---
    tags:
      - API Key
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    responses:
      200:
        description: API key info
        schema:
          type: object
          properties:
            has_key:
              type: boolean
            key_prefix:
              type: string
              description: First 8 chars of the key (rest masked)
      401:
        description: Authentication required
    """
    user = require_api_auth()
    if user.api_key:
        masked = user.api_key[:8] + '…' + '*' * 24
    else:
        masked = None
    return jsonify({
        'has_key':    user.api_key is not None,
        'key_prefix': masked,
    }), 200


@api_v1.route('/me/api-key', methods=['POST'])
def rotate_api_key():
    """
    Generate or rotate the current user's API key.
    ---
    tags:
      - API Key
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    responses:
      200:
        description: New API key (shown in full — store it safely)
        schema:
          type: object
          properties:
            api_key:
              type: string
            message:
              type: string
      401:
        description: Authentication required
    """
    user = require_api_auth()
    new_key = user.generate_api_key()
    db.session.commit()
    return jsonify({
        'api_key': new_key,
        'message': 'API key generated. Store it safely — it will not be shown again in full.',
    }), 200


# ===========================================================================
# Trips — list & create
# ===========================================================================

@api_v1.route('/trips', methods=['GET'])
def list_trips():
    """
    List the current user's trips (owned + joined), paginated.
    ---
    tags:
      - Trips
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    parameters:
      - in: query
        name: page
        type: integer
        default: 1
      - in: query
        name: per_page
        type: integer
        default: 10
        maximum: 50
      - in: query
        name: status
        type: string
        description: Filter by trip status (OPEN, CONFIRMED, ACTIVE, COMPLETED, CANCELLED)
    responses:
      200:
        description: Paginated list of trips
      401:
        description: Authentication required
    """
    user = require_api_auth()

    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 50)
    status   = request.args.get('status', '').upper() or None

    trip_ids = user._all_trip_ids()
    if not trip_ids:
        return jsonify({
            'data': [],
            'meta': {'page': page, 'per_page': per_page, 'total': 0, 'pages': 0},
        }), 200

    query = Trip.query.filter(Trip.id.in_(trip_ids))
    if status:
        query = query.filter(Trip.status == status)

    pagination = (
        query
        .order_by(Trip.start_date.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return jsonify({
        'data': [_trip_to_dict(t) for t in pagination.items],
        'meta': {
            'page':     pagination.page,
            'per_page': pagination.per_page,
            'total':    pagination.total,
            'pages':    pagination.pages,
        },
    }), 200


@api_v1.route('/trips', methods=['POST'])
def create_trip():
    """
    Create a new trip owned by the current user.
    ---
    tags:
      - Trips
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    consumes:
      - application/json
    parameters:
      - in: body
        name: trip
        required: true
        schema:
          type: object
          required: [title, destination, start_date, end_date]
          properties:
            title:
              type: string
              example: Goa Weekend Getaway
            destination:
              type: string
              example: Goa
            departure_city:
              type: string
              example: Mumbai
            start_date:
              type: string
              format: date
              example: "2026-12-20"
            end_date:
              type: string
              format: date
              example: "2026-12-24"
            description:
              type: string
            budget_min:
              type: number
              example: 5000
            budget_max:
              type: number
              example: 15000
            max_members:
              type: integer
              example: 4
            is_public:
              type: boolean
              example: true
            open_roster:
              type: boolean
              example: false
    responses:
      201:
        description: Trip created
      400:
        description: Validation error
      401:
        description: Authentication required
    """
    user = require_api_auth()
    data = _validate_json(TripCreateSchema())

    if data['end_date'] < data['start_date']:
        abort(400, description='end_date must be on or after start_date')

    trip = Trip(
        owner_id       = user.id,
        title          = data['title'],
        destination    = data['destination'],
        departure_city = data.get('departure_city', ''),
        start_date     = data['start_date'],
        end_date       = data['end_date'],
        description    = data.get('description', ''),
        budget_min     = data.get('budget_min', 0.0),
        budget_max     = data.get('budget_max', 0.0),
        max_members    = data.get('max_members', 4),
        is_public      = data.get('is_public', True),
        open_roster    = data.get('open_roster', False),
        status         = 'OPEN',
    )
    db.session.add(trip)
    db.session.commit()

    return jsonify({'data': _trip_to_dict(trip)}), 201


# ===========================================================================
# Trips — single resource (GET / PUT / PATCH / DELETE)
# ===========================================================================

@api_v1.route('/trips/<int:trip_id>', methods=['GET'])
def get_trip(trip_id: int):
    """
    Get full details for a single trip (owner or accepted member only).
    ---
    tags:
      - Trips
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    parameters:
      - in: path
        name: trip_id
        type: integer
        required: true
    responses:
      200:
        description: Trip detail with members, expenses, settlements
      401:
        description: Authentication required
      403:
        description: Not a member of this trip
      404:
        description: Trip not found
    """
    user = require_api_auth()
    # HIGH-3: Return 404 for both non-existent and inaccessible trips so
    # that attackers cannot enumerate private trip IDs via 403 vs 404.
    trip = db.session.get(Trip, trip_id)
    if trip is None:
        abort(404)
    is_owner = trip.owner_id == user.id
    membership = TripMember.query.filter_by(trip_id=trip.id, user_id=user.id).first()
    if not (is_owner or (membership is not None and membership.status == 'accepted')):
        abort(404)  # intentional 404 — do not reveal trip existence

    members = (
        [{'id': trip.owner.id, 'name': trip.owner.name, 'role': 'owner'}]
        + [{'id': m.user.id, 'name': m.user.name, 'role': 'member'}
           for m in trip.accepted_members()]
    )

    expenses = [
        _expense_to_dict(e)
        for e in trip.expenses.order_by(Expense.date.desc()).all()
    ]

    settlements = [
        {
            'debtor':   {'id': s['debtor'].id,   'name': s['debtor'].name},
            'creditor': {'id': s['creditor'].id, 'name': s['creditor'].name},
            'amount':   s['amount'],
        }
        for s in trip.calculate_settlements()
    ]

    data = _trip_to_dict(trip)
    data['members']     = members
    data['expenses']    = expenses
    data['settlements'] = settlements

    return jsonify({'data': data}), 200


@api_v1.route('/trips/<int:trip_id>', methods=['PUT'])
def update_trip(trip_id: int):
    """
    Fully replace a trip's mutable fields (owner only).
    ---
    tags:
      - Trips
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: trip_id
        type: integer
        required: true
      - in: body
        name: trip
        required: true
        schema:
          type: object
          required: [title, destination, start_date, end_date]
          properties:
            title:
              type: string
            destination:
              type: string
            departure_city:
              type: string
            start_date:
              type: string
              format: date
            end_date:
              type: string
              format: date
            description:
              type: string
            budget_min:
              type: number
            budget_max:
              type: number
            max_members:
              type: integer
            is_public:
              type: boolean
            open_roster:
              type: boolean
    responses:
      200:
        description: Updated trip
      400:
        description: Validation error
      401:
        description: Authentication required
      403:
        description: Not the trip owner
      404:
        description: Trip not found
    """
    user = require_api_auth()
    trip = db.get_or_404(Trip, trip_id)
    _assert_trip_ownership(trip, user)
    data = _validate_json(TripCreateSchema())

    if data['end_date'] < data['start_date']:
        abort(400, description='end_date must be on or after start_date')

    # ── Trip lock: reject changes to core fields once a member has joined ──
    LOCKED_FIELDS = {
        'title', 'destination', 'departure_city',
        'start_date', 'end_date', 'budget_min', 'budget_max',
    }
    if trip.has_accepted_members:
        # Check if caller is attempting to change any locked field
        attempted = [
            f for f in LOCKED_FIELDS
            if f in data and getattr(trip, f) != data[f]
        ]
        if attempted:
            abort(423, description=(
                'This trip is locked because at least one member has joined. '
                f'Cannot change: {attempted}. '
                'Only max_members (upward) can be modified.'
            ))
        # Also block max_members reduction
        if 'max_members' in data and data['max_members'] < trip.max_members:
            abort(400, description=(
                'Cannot reduce max_members once a member has joined.'
            ))

    trip.title          = data['title']
    trip.destination    = data['destination']
    trip.departure_city = data.get('departure_city', '')
    trip.start_date     = data['start_date']
    trip.end_date       = data['end_date']
    trip.description    = data.get('description', '')
    trip.budget_min     = data.get('budget_min', 0.0)
    trip.budget_max     = data.get('budget_max', 0.0)
    trip.max_members    = data.get('max_members', 4)
    trip.is_public      = data.get('is_public', True)
    trip.open_roster    = data.get('open_roster', False)

    db.session.commit()
    return jsonify({'data': _trip_to_dict(trip)}), 200


@api_v1.route('/trips/<int:trip_id>', methods=['PATCH'])
def patch_trip(trip_id: int):
    """
    Partially update a trip (owner only). Only supplied fields are changed.
    ---
    tags:
      - Trips
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: trip_id
        type: integer
        required: true
      - in: body
        name: trip
        required: true
        schema:
          type: object
          properties:
            title:
              type: string
            destination:
              type: string
            departure_city:
              type: string
            start_date:
              type: string
              format: date
            end_date:
              type: string
              format: date
            description:
              type: string
            budget_min:
              type: number
            budget_max:
              type: number
            max_members:
              type: integer
            is_public:
              type: boolean
            open_roster:
              type: boolean
    responses:
      200:
        description: Patched trip
      400:
        description: Validation error
      401:
        description: Authentication required
      403:
        description: Not the trip owner
      404:
        description: Trip not found
    """
    user = require_api_auth()
    trip = db.get_or_404(Trip, trip_id)
    _assert_trip_ownership(trip, user)

    body = request.get_json(silent=True)
    if body is None:
        abort(400, description='Request body must be valid JSON')

    try:
        data = TripUpdateSchema(partial=True).load(body)
    except ValidationError as exc:
        abort(400, description=str(exc.messages))

    # ── Trip lock: block changes to core fields once a member has joined ───
    LOCKED_FIELDS = {
        'title', 'destination', 'departure_city',
        'start_date', 'end_date', 'budget_min', 'budget_max',
    }
    if trip.has_accepted_members:
        attempted = [
            f for f in LOCKED_FIELDS
            if f in data and getattr(trip, f) != data[f]
        ]
        if attempted:
            abort(423, description=(
                'This trip is locked because at least one member has joined. '
                f'Cannot change: {attempted}. '
                'Only max_members (upward) can be modified.'
            ))
        if 'max_members' in data and data['max_members'] < trip.max_members:
            abort(400, description=(
                'Cannot reduce max_members once a member has joined.'
            ))

    if 'title'          in data: trip.title          = data['title']
    if 'destination'    in data: trip.destination    = data['destination']
    if 'departure_city' in data: trip.departure_city = data['departure_city']
    if 'start_date'     in data: trip.start_date     = data['start_date']
    if 'end_date'       in data: trip.end_date       = data['end_date']
    if 'description'    in data: trip.description    = data['description']
    if 'budget_min'     in data: trip.budget_min     = data['budget_min']
    if 'budget_max'     in data: trip.budget_max     = data['budget_max']
    if 'max_members'    in data: trip.max_members    = data['max_members']
    if 'is_public'      in data: trip.is_public      = data['is_public']
    if 'open_roster'    in data: trip.open_roster    = data['open_roster']

    # Re-validate date coherence if either was changed
    if trip.end_date < trip.start_date:
        abort(400, description='end_date must be on or after start_date')

    db.session.commit()
    return jsonify({'data': _trip_to_dict(trip)}), 200


@api_v1.route('/trips/<int:trip_id>', methods=['DELETE'])
def delete_trip(trip_id: int):
    """
    Delete a trip and all its expenses/members (owner only).
    ---
    tags:
      - Trips
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    parameters:
      - in: path
        name: trip_id
        type: integer
        required: true
    responses:
      204:
        description: Trip deleted
      401:
        description: Authentication required
      403:
        description: Not the trip owner
      404:
        description: Trip not found
    """
    user = require_api_auth()
    trip = db.get_or_404(Trip, trip_id)
    _assert_trip_ownership(trip, user)

    db.session.delete(trip)
    db.session.commit()
    return '', 204


# ===========================================================================
# Expenses — list & create
# ===========================================================================

@api_v1.route('/expenses', methods=['GET'])
def list_expenses():
    """
    List expenses across all of the user's trips, paginated.
    ---
    tags:
      - Expenses
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    parameters:
      - in: query
        name: page
        type: integer
        default: 1
      - in: query
        name: per_page
        type: integer
        default: 20
        maximum: 100
      - in: query
        name: trip_id
        type: integer
        description: Filter to a single trip
      - in: query
        name: category
        type: string
        description: Filter by category
    responses:
      200:
        description: Paginated list of expenses
      401:
        description: Authentication required
    """
    user = require_api_auth()

    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    trip_id  = request.args.get('trip_id', type=int)
    category = request.args.get('category', '').strip() or None

    trip_ids = user._all_trip_ids()
    if not trip_ids:
        return jsonify({
            'data': [],
            'meta': {'page': page, 'per_page': per_page, 'total': 0, 'pages': 0},
        }), 200

    query = Expense.query.filter(Expense.trip_id.in_(trip_ids))

    if trip_id is not None:
        if trip_id not in trip_ids:
            abort(403)
        query = query.filter(Expense.trip_id == trip_id)

    if category:
        query = query.filter(Expense.category == category)

    pagination = (
        query
        .order_by(Expense.date.desc(), Expense.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return jsonify({
        'data': [_expense_to_dict(e) for e in pagination.items],
        'meta': {
            'page':     pagination.page,
            'per_page': pagination.per_page,
            'total':    pagination.total,
            'pages':    pagination.pages,
        },
    }), 200


@api_v1.route('/expenses', methods=['POST'])
def create_expense():
    """
    Add an expense to a trip. The caller becomes the payer.
    ---
    tags:
      - Expenses
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    consumes:
      - application/json
    parameters:
      - in: body
        name: expense
        required: true
        schema:
          type: object
          required: [trip_id, title, amount]
          properties:
            trip_id:
              type: integer
              example: 1
            title:
              type: string
              example: Hotel booking
            amount:
              type: number
              example: 3500.00
            category:
              type: string
              example: accommodation
            date:
              type: string
              format: date
              example: "2026-12-21"
    responses:
      201:
        description: Expense created
      400:
        description: Validation error
      401:
        description: Authentication required
      403:
        description: Not a member of this trip / trip does not allow expenses
    """
    user = require_api_auth()
    data = _validate_json(ExpenseCreateSchema())

    trip = db.get_or_404(Trip, data['trip_id'])
    _assert_trip_access(trip, user)

    if not trip.can_add_expense():
        abort(400, description=(
            f'Expenses can only be added to CONFIRMED or ACTIVE trips. '
            f'Current status: {trip.status}'
        ))

    expense = Expense(
        trip_id    = trip.id,
        paid_by_id = user.id,
        title      = data['title'],
        amount     = data['amount'],
        category   = data.get('category', 'general'),
        date       = data['date'] if data.get('date') else _date.today(),
    )
    db.session.add(expense)
    db.session.commit()

    return jsonify({'data': _expense_to_dict(expense)}), 201


# ===========================================================================
# Expenses — single resource (GET / PUT / PATCH / DELETE)
# ===========================================================================

@api_v1.route('/expenses/<int:expense_id>', methods=['GET'])
def get_expense(expense_id: int):
    """
    Get a single expense (trip member only).
    ---
    tags:
      - Expenses
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    parameters:
      - in: path
        name: expense_id
        type: integer
        required: true
    responses:
      200:
        description: Expense detail
      401:
        description: Authentication required
      403:
        description: Not a member of this trip
      404:
        description: Expense not found
    """
    user = require_api_auth()
    expense = db.get_or_404(Expense, expense_id)
    _assert_trip_access(expense.trip, user)
    return jsonify({'data': _expense_to_dict(expense)}), 200


@api_v1.route('/expenses/<int:expense_id>', methods=['PUT'])
def update_expense(expense_id: int):
    """
    Fully replace an expense's fields (original payer or trip owner only).
    ---
    tags:
      - Expenses
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: expense_id
        type: integer
        required: true
      - in: body
        name: expense
        required: true
        schema:
          type: object
          required: [trip_id, title, amount]
          properties:
            trip_id:
              type: integer
            title:
              type: string
            amount:
              type: number
            category:
              type: string
            date:
              type: string
              format: date
    responses:
      200:
        description: Updated expense
      400:
        description: Validation error
      401:
        description: Authentication required
      403:
        description: Not the payer or trip owner
      404:
        description: Expense not found
    """
    user = require_api_auth()
    expense = db.get_or_404(Expense, expense_id)

    # CRIT-1 / HIGH-1: Verify the caller is still an active member of the
    # trip this expense belongs to.  An ex-member who left or was declined
    # must not be able to mutate expenses they originally paid.
    _assert_active_trip_membership(expense.trip, user)

    # Only the payer or the trip owner may update
    if expense.paid_by_id != user.id and expense.trip.owner_id != user.id:
        abort(403)

    data = _validate_json(ExpenseCreateSchema())

    expense.title    = data['title']
    expense.amount   = data['amount']
    expense.category = data.get('category', 'general')
    expense.date     = data['date'] if data.get('date') else expense.date

    db.session.commit()
    return jsonify({'data': _expense_to_dict(expense)}), 200


@api_v1.route('/expenses/<int:expense_id>', methods=['PATCH'])
def patch_expense(expense_id: int):
    """
    Partially update an expense (original payer or trip owner only).
    ---
    tags:
      - Expenses
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    consumes:
      - application/json
    parameters:
      - in: path
        name: expense_id
        type: integer
        required: true
      - in: body
        name: expense
        required: true
        schema:
          type: object
          properties:
            title:
              type: string
            amount:
              type: number
            category:
              type: string
            date:
              type: string
              format: date
    responses:
      200:
        description: Patched expense
      400:
        description: Validation error
      401:
        description: Authentication required
      403:
        description: Not the payer or trip owner
      404:
        description: Expense not found
    """
    user = require_api_auth()
    expense = db.get_or_404(Expense, expense_id)

    # HIGH-1: Verify active trip membership before allowing PATCH.
    _assert_active_trip_membership(expense.trip, user)

    if expense.paid_by_id != user.id and expense.trip.owner_id != user.id:
        abort(403)

    body = request.get_json(silent=True)
    if body is None:
        abort(400, description='Request body must be valid JSON')

    try:
        data = ExpenseUpdateSchema(partial=True).load(body)
    except ValidationError as exc:
        abort(400, description=str(exc.messages))

    if 'title'    in data: expense.title    = data['title']
    if 'amount'   in data: expense.amount   = data['amount']
    if 'category' in data: expense.category = data['category']
    if 'date'     in data: expense.date     = data['date']

    db.session.commit()
    return jsonify({'data': _expense_to_dict(expense)}), 200


@api_v1.route('/expenses/<int:expense_id>', methods=['DELETE'])
def delete_expense(expense_id: int):
    """
    Delete an expense (original payer or trip owner only).
    ---
    tags:
      - Expenses
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    parameters:
      - in: path
        name: expense_id
        type: integer
        required: true
    responses:
      204:
        description: Expense deleted
      401:
        description: Authentication required
      403:
        description: Not the payer or trip owner
      404:
        description: Expense not found
    """
    user = require_api_auth()
    expense = db.get_or_404(Expense, expense_id)

    # HIGH-1: Verify active trip membership before allowing DELETE.
    _assert_active_trip_membership(expense.trip, user)

    if expense.paid_by_id != user.id and expense.trip.owner_id != user.id:
        abort(403)

    db.session.delete(expense)
    db.session.commit()
    return '', 204


# ===========================================================================
# Settlements — read-only
# ===========================================================================

@api_v1.route('/settlements', methods=['GET'])
def list_settlements():
    """
    Return the computed settlement plan for all of the user's trips.
    ---
    tags:
      - Settlements
    security:
      - BearerAuth: []
      - ApiKeyAuth: []
    parameters:
      - in: query
        name: trip_id
        type: integer
        description: Filter to a single trip
    responses:
      200:
        description: Settlement plan per trip
      401:
        description: Authentication required
    """
    user = require_api_auth()

    trip_ids = user._all_trip_ids()
    if not trip_ids:
        return jsonify({'data': []}), 200

    trip_id_filter = request.args.get('trip_id', type=int)
    if trip_id_filter is not None:
        if trip_id_filter not in trip_ids:
            abort(403)
        trips_to_show = Trip.query.filter(Trip.id == trip_id_filter).all()
    else:
        trips_to_show = Trip.query.filter(Trip.id.in_(trip_ids)).all()

    result = []
    for trip in trips_to_show:
        computed = trip.calculate_settlements()
        db_settled = {
            (s.payer_id, s.payee_id): s.is_settled
            for s in trip.settlements.all()
        }
        result.append({
            'trip_id':    trip.id,
            'trip_title': trip.title,
            'transfers': [
                {
                    'debtor':     {'id': s['debtor'].id,   'name': s['debtor'].name},
                    'creditor':   {'id': s['creditor'].id, 'name': s['creditor'].name},
                    'amount':     s['amount'],
                    'is_settled': db_settled.get((s['debtor'].id, s['creditor'].id), False),
                }
                for s in computed
            ],
        })

    return jsonify({'data': result}), 200


# ===========================================================================
# Blueprint-scoped error handlers
# ===========================================================================

@api_v1.errorhandler(400)
def api_bad_request(e):
    desc = getattr(e, 'description', str(e))
    return jsonify({'error': desc, 'status': 400}), 400


@api_v1.errorhandler(401)
def api_unauthorized(e):
    return jsonify({
        'error': 'Authentication required. Provide Authorization: Bearer <token>, X-API-Key: <key>, or a valid session cookie.',
        'status': 401,
    }), 401


@api_v1.errorhandler(403)
def api_forbidden(e):
    return jsonify({'error': 'Access forbidden', 'status': 403}), 403


@api_v1.errorhandler(404)
def api_not_found(e):
    return jsonify({'error': 'Resource not found', 'status': 404}), 404


@api_v1.errorhandler(405)
def api_method_not_allowed(e):
    return jsonify({'error': 'Method not allowed', 'status': 405}), 405


@api_v1.errorhandler(423)
def api_locked(e):
    desc = getattr(e, 'description', str(e))
    return jsonify({'error': desc, 'status': 423}), 423
