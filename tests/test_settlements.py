"""Tests for the Splitwise-style settlement algorithm in Trip.calculate_settlements()."""

import pytest
from datetime import date, timedelta
from app.models import Trip, User, Expense, TripMember
from app.extensions import db as _db, bcrypt


# ---------------------------------------------------------------------------
# Helpers — call within an app_context
# ---------------------------------------------------------------------------

def _make_user(name, email):
    pw = bcrypt.generate_password_hash('pass').decode('utf-8')
    u = User(name=name, email=email, password_hash=pw)
    _db.session.add(u)
    _db.session.flush()
    return u


def _make_trip(owner):
    tomorrow = date.today() + timedelta(days=1)
    t = Trip(
        owner_id=owner.id,
        title='Settlement Test Trip',
        destination='Mumbai',
        departure_city='Pune',
        start_date=tomorrow,
        end_date=tomorrow + timedelta(days=3),
        budget_min=1000,
        budget_max=5000,
        max_members=5,
    )
    _db.session.add(t)
    _db.session.flush()
    return t


def _add_member(trip, user):
    m = TripMember(trip_id=trip.id, user_id=user.id, status='accepted')
    _db.session.add(m)
    _db.session.flush()


def _add_expense(trip, user, amount):
    e = Expense(
        trip_id=trip.id,
        paid_by_id=user.id,
        title='Test Expense',
        amount=amount,
        category='general',
        date=date.today(),
    )
    _db.session.add(e)
    _db.session.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSettlementAlgorithm:

    def test_no_expenses_returns_empty(self, app):
        with app.app_context():
            owner = _make_user('Alpha', 'alpha@test.com')
            trip = _make_trip(owner)
            _db.session.commit()
            result = trip.calculate_settlements()
        assert result == []

    def test_single_member_no_transfers(self, app):
        with app.app_context():
            owner = _make_user('Beta', 'beta@test.com')
            trip = _make_trip(owner)
            _add_expense(trip, owner, 300.0)
            _db.session.commit()
            result = trip.calculate_settlements()
        assert result == []

    def test_equal_split_no_transfers(self, app):
        with app.app_context():
            a = _make_user('A', 'a@test.com')
            b = _make_user('B', 'b@test.com')
            trip = _make_trip(a)
            _add_member(trip, b)
            _add_expense(trip, a, 500.0)
            _add_expense(trip, b, 500.0)
            _db.session.commit()
            result = trip.calculate_settlements()
        assert result == []

    def test_one_person_paid_all(self, app):
        """3 members, A paid 900. Share=300. Expected: B→A 300, C→A 300."""
        with app.app_context():
            a = _make_user('Payer', 'payer@test.com')
            b = _make_user('Free1', 'free1@test.com')
            c = _make_user('Free2', 'free2@test.com')
            trip = _make_trip(a)
            _add_member(trip, b)
            _add_member(trip, c)
            _add_expense(trip, a, 900.0)
            _db.session.commit()
            result = trip.calculate_settlements()
            creditor_id = a.id

        assert len(result) == 2
        for s in result:
            assert s['creditor'].id == creditor_id
            assert round(s['amount'], 2) == 300.0

    def test_minimum_transfers_algorithm(self, app):
        """
        A paid 900, B paid 1200, C paid 0. Share=700.
        Minimum transfers: C→B 500, C→A 200 (2 not 3).
        """
        with app.app_context():
            a = _make_user('UserA', 'ua@test.com')
            b = _make_user('UserB', 'ub@test.com')
            c = _make_user('UserC', 'uc@test.com')
            trip = _make_trip(a)
            _add_member(trip, b)
            _add_member(trip, c)
            _add_expense(trip, a, 900.0)
            _add_expense(trip, b, 1200.0)
            _db.session.commit()
            result = trip.calculate_settlements()
            a_id, b_id, c_id = a.id, b.id, c.id

        assert len(result) == 2
        for s in result:
            assert s['debtor'].id == c_id
        total_transferred = sum(s['amount'] for s in result)
        assert round(total_transferred, 2) == 700.0
        creditor_amounts = {s['creditor'].id: s['amount'] for s in result}
        assert round(creditor_amounts[b_id], 2) == 500.0
        assert round(creditor_amounts[a_id], 2) == 200.0

    def test_settlement_amounts_are_non_negative(self, app):
        with app.app_context():
            a = _make_user('X', 'x@test.com')
            b = _make_user('Y', 'y@test.com')
            trip = _make_trip(a)
            _add_member(trip, b)
            _add_expense(trip, a, 750.0)
            _add_expense(trip, b, 250.0)
            _db.session.commit()
            result = trip.calculate_settlements()

        for s in result:
            assert s['amount'] > 0

    def test_settlement_summary_sums_correctly(self, app):
        with app.app_context():
            a = _make_user('M', 'm@test.com')
            b = _make_user('N', 'n@test.com')
            trip = _make_trip(a)
            _add_member(trip, b)
            _add_expense(trip, a, 600.0)
            _add_expense(trip, b, 200.0)
            _db.session.commit()
            summary = trip.settlement_summary()
            total_paid = sum(row['paid'] for row in summary)
            total_spent = trip.total_spent()

        assert round(total_paid, 2) == round(total_spent, 2)
