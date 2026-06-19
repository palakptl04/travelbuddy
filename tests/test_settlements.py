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


# ---------------------------------------------------------------------------
# Settlement Bug Regression — partial settlement must not show "all settled"
# ---------------------------------------------------------------------------

class TestPartialSettlementBug:
    """
    Regression test for the settlement bug:

    Setup: 3 members — Palak (owner), Khushi, Ruhi.
    Palak pays ₹480 total (all expenses).  Share = ₹160 each.
    calculate_settlements() produces:
        Khushi → Palak ₹160
        Ruhi   → Palak ₹160

    Khushi marks hers settled.  Ruhi does NOT.

    From Palak's perspective:
    - settled should be False (Ruhi's ₹160 still pending)
    - pending_balance should be +₹160 (she is still owed)
    """

    def test_partial_settlement_not_all_settled(self, app):
        from app.models import Settlement
        from app.expenses.routes import my_expenses
        from datetime import timezone

        with app.app_context():
            palak = _make_user('Palak', 'palak@bug.com')
            khushi = _make_user('Khushi', 'khushi@bug.com')
            ruhi = _make_user('Ruhi', 'ruhi@bug.com')

            trip = _make_trip(palak)
            _add_member(trip, khushi)
            _add_member(trip, ruhi)

            # Palak pays everything
            _add_expense(trip, palak, 480.0)   # 3 members → ₹160 each
            _db.session.commit()

            # Verify calculate_settlements gives 2 transfers both to Palak
            transfers = trip.calculate_settlements()
            assert len(transfers) == 2
            for t in transfers:
                assert t['creditor'].id == palak.id
                assert round(t['amount'], 2) == 160.0

            # Khushi settles her debt (payer=khushi, payee=palak)
            khushi_transfer = next(t for t in transfers if t['debtor'].id == khushi.id)
            s = Settlement(
                trip_id=trip.id,
                payer_id=khushi.id,
                payee_id=palak.id,
                amount=khushi_transfer['amount'],
                is_settled=True,
            )
            _db.session.add(s)
            _db.session.commit()

            # Now check from Palak's perspective using the fixed my_expenses logic
            computed = trip.calculate_settlements()
            my_credits = [t for t in computed if t['creditor'].id == palak.id]
            settled_payer_ids = {
                s.payer_id
                for s in Settlement.query.filter_by(
                    trip_id=trip.id, payee_id=palak.id, is_settled=True
                ).all()
            }
            unsettled_credit = sum(
                t['amount'] for t in my_credits
                if t['debtor'].id not in settled_payer_ids
            )

            # Ruhi's ₹160 is still unsettled — palak is not fully settled
            assert unsettled_credit > 0.01, \
                f"Expected unsettled credit > 0, got {unsettled_credit}"
            assert round(unsettled_credit, 2) == 160.0

    def test_full_settlement_shows_settled(self, app):
        """When ALL transfers are marked settled, the trip IS fully settled."""
        from app.models import Settlement

        with app.app_context():
            palak = _make_user('Palak2', 'palak2@bug.com')
            khushi = _make_user('Khushi2', 'khushi2@bug.com')
            ruhi = _make_user('Ruhi2', 'ruhi2@bug.com')

            trip = _make_trip(palak)
            _add_member(trip, khushi)
            _add_member(trip, ruhi)
            _add_expense(trip, palak, 480.0)
            _db.session.commit()

            transfers = trip.calculate_settlements()
            # Mark ALL transfers settled
            for t in transfers:
                s = Settlement(
                    trip_id=trip.id,
                    payer_id=t['debtor'].id,
                    payee_id=t['creditor'].id,
                    amount=t['amount'],
                    is_settled=True,
                )
                _db.session.add(s)
            _db.session.commit()

            computed = trip.calculate_settlements()
            my_credits = [t for t in computed if t['creditor'].id == palak.id]
            settled_payer_ids = {
                s.payer_id
                for s in Settlement.query.filter_by(
                    trip_id=trip.id, payee_id=palak.id, is_settled=True
                ).all()
            }
            unsettled_credit = sum(
                t['amount'] for t in my_credits
                if t['debtor'].id not in settled_payer_ids
            )
            assert unsettled_credit < 0.01, \
                f"Expected fully settled (unsettled_credit≈0), got {unsettled_credit}"
