"""
REST API v1 — Read-only JSON endpoints.

All endpoints require an authenticated session (same cookie auth as the web UI).
Base URL: /api/v1

Endpoints
---------
GET /api/v1/trips              — paginated list of the current user's trips
GET /api/v1/trips/<id>         — trip detail with members, expenses, settlements
GET /api/v1/expenses           — all expenses across all the user's trips
GET /api/v1/settlements        — computed settlement plan per trip
"""

from flask import jsonify, request, abort
from flask_login import current_user, login_required

from app.api import api_v1
from app.models import Trip, TripMember, Expense, Settlement
from app.extensions import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trip_to_dict(trip):
    """Minimal trip representation."""
    return {
        'id':              trip.id,
        'title':           trip.title,
        'destination':     trip.destination,
        'departure_city':  trip.departure_city,
        'start_date':      trip.start_date.isoformat(),
        'end_date':        trip.end_date.isoformat(),
        'status':          trip.status,
        'computed_status': trip.computed_status,   # date-based: upcoming/ongoing/completed
        'joining_closed':  trip.joining_closed,
        'status_label':    trip.status_label,
        'is_public':       trip.is_public,
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


def _expense_to_dict(expense):
    return {
        'id':       expense.id,
        'trip_id':  expense.trip_id,
        'title':    expense.title,
        'amount':   expense.amount,
        'category': expense.category,
        'date':     expense.date.isoformat(),
        'paid_by': {
            'id':   expense.paid_by.id,
            'name': expense.paid_by.name,
        },
        'created_at': expense.created_at.isoformat(),
    }


def _require_auth():
    """Abort with 401 if user is not authenticated."""
    if not current_user.is_authenticated:
        abort(401)


# ---------------------------------------------------------------------------
# GET /api/v1/trips
# ---------------------------------------------------------------------------

@api_v1.route('/trips', methods=['GET'])
def list_trips():
    """
    Return a paginated list of the current user's trips (owned + joined).

    Query parameters:
      page     (int, default 1)
      per_page (int, default 10, max 50)
    """
    _require_auth()

    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 50)

    trip_ids = current_user._all_trip_ids()
    if not trip_ids:
        return jsonify({
            'data': [],
            'meta': {'page': page, 'per_page': per_page, 'total': 0, 'pages': 0}
        }), 200

    pagination = (
        Trip.query
        .filter(Trip.id.in_(trip_ids))
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
        }
    }), 200


# ---------------------------------------------------------------------------
# GET /api/v1/trips/<id>
# ---------------------------------------------------------------------------

@api_v1.route('/trips/<int:trip_id>', methods=['GET'])
def get_trip(trip_id):
    """
    Return full details for a single trip.
    Only accessible to the trip owner or accepted members.
    """
    _require_auth()

    trip = db.get_or_404(Trip, trip_id)

    is_owner = trip.owner_id == current_user.id
    membership = TripMember.query.filter_by(
        trip_id=trip.id, user_id=current_user.id
    ).first()
    is_member = is_owner or (membership is not None and membership.status == 'accepted')

    if not is_member:
        abort(403)

    members = [
        {'id': trip.owner.id, 'name': trip.owner.name, 'role': 'owner'}
    ] + [
        {'id': m.user.id, 'name': m.user.name, 'role': 'member'}
        for m in trip.accepted_members()
    ]

    expenses = [_expense_to_dict(e)
                for e in trip.expenses.order_by(Expense.date.desc()).all()]

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


# ---------------------------------------------------------------------------
# GET /api/v1/expenses
# ---------------------------------------------------------------------------

@api_v1.route('/expenses', methods=['GET'])
def list_expenses():
    """
    Return all expenses across all trips the current user belongs to.

    Query parameters:
      page     (int, default 1)
      per_page (int, default 20, max 100)
      trip_id  (int, optional) — filter by trip
    """
    _require_auth()

    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    trip_id  = request.args.get('trip_id', type=int)

    trip_ids = current_user._all_trip_ids()
    if not trip_ids:
        return jsonify({
            'data': [],
            'meta': {'page': page, 'per_page': per_page, 'total': 0, 'pages': 0}
        }), 200

    query = Expense.query.filter(Expense.trip_id.in_(trip_ids))
    if trip_id is not None:
        if trip_id not in trip_ids:
            abort(403)
        query = query.filter(Expense.trip_id == trip_id)

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
        }
    }), 200


# ---------------------------------------------------------------------------
# GET /api/v1/settlements
# ---------------------------------------------------------------------------

@api_v1.route('/settlements', methods=['GET'])
def list_settlements():
    """
    Return the computed settlement plan for all of the current user's trips.

    Query parameters:
      trip_id (int, optional) — filter to a single trip
    """
    _require_auth()

    trip_ids = current_user._all_trip_ids()
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
                    'debtor':    {'id': s['debtor'].id,   'name': s['debtor'].name},
                    'creditor':  {'id': s['creditor'].id, 'name': s['creditor'].name},
                    'amount':    s['amount'],
                    'is_settled': db_settled.get(
                        (s['debtor'].id, s['creditor'].id), False
                    ),
                }
                for s in computed
            ],
        })

    return jsonify({'data': result}), 200


# ---------------------------------------------------------------------------
# Error handlers (scoped to this blueprint)
# ---------------------------------------------------------------------------

@api_v1.errorhandler(401)
def api_unauthorized(e):
    return jsonify({'error': 'Authentication required', 'status': 401}), 401


@api_v1.errorhandler(403)
def api_forbidden(e):
    return jsonify({'error': 'Access forbidden', 'status': 403}), 403


@api_v1.errorhandler(404)
def api_not_found(e):
    return jsonify({'error': 'Resource not found', 'status': 404}), 404
