from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import date as date_today, datetime, timezone

from app.expenses import expenses
from app.expenses.forms import ExpenseForm
from app.models import Trip, TripMember, Expense, Settlement
from app.extensions import db


def _get_membership(trip):
    """Return (is_owner, is_member) for current_user on the given trip."""
    is_owner = trip.owner_id == current_user.id
    membership = TripMember.query.filter_by(
        trip_id=trip.id, user_id=current_user.id
    ).first()
    is_member = is_owner or (membership is not None and membership.status == 'accepted')
    return is_owner, is_member


@expenses.route('/trips/<int:trip_id>/expenses/add', methods=['POST'])
@login_required
def add(trip_id):
    trip = db.get_or_404(Trip, trip_id)
    is_owner, is_member = _get_membership(trip)

    if not is_member:
        flash('Only trip members can add expenses.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    # Expenses are only allowed after joining closes (1 day before trip starts).
    # This prevents members who join later from distorting existing splits.
    if not trip.joining_closed:
        flash(
            'Expenses can only be added after joining closes '
            '(1 day before the trip starts).',
            'error'
        )
        return redirect(url_for('trips.detail', trip_id=trip.id))

    form = ExpenseForm()
    # Paid By is always the current logged-in user — force choices to just self
    form.paid_by_id.choices = [(current_user.id, current_user.name)]

    if form.validate_on_submit():
        expense_date = form.expense_date.data or date_today.today()
        expense = Expense(
            trip_id=trip.id,
            paid_by_id=current_user.id,   # always self — ignore submitted value
            title=form.title.data.strip(),
            amount=form.amount.data,
            category=form.category.data,
            date=expense_date
        )
        db.session.add(expense)
        db.session.commit()
        flash('Expense added and split equally among all members.', 'success')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                flash(err, 'error')

    return redirect(url_for('trips.detail', trip_id=trip.id))


@expenses.route('/trips/<int:trip_id>/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete(trip_id, expense_id):
    trip = db.get_or_404(Trip, trip_id)
    expense = db.get_or_404(Expense, expense_id)

    if expense.trip_id != trip.id:
        flash('Invalid request.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    is_owner, is_member = _get_membership(trip)
    if expense.paid_by_id != current_user.id and not is_owner:
        flash('Only the payer or trip owner can delete this expense.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    db.session.delete(expense)
    db.session.commit()
    flash('Expense removed.', 'success')
    return redirect(url_for('trips.detail', trip_id=trip.id))


@expenses.route('/trips/<int:trip_id>/settlements/mark-settled', methods=['POST'])
@login_required
def mark_settled(trip_id):
    """Mark a specific payer→payee settlement row as settled."""
    trip = db.get_or_404(Trip, trip_id)
    is_owner, is_member = _get_membership(trip)

    if not is_member:
        flash('Only trip members can mark settlements.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    try:
        payer_id = int(request.form.get('payer_id'))
        payee_id = int(request.form.get('payee_id'))
        amount   = float(request.form.get('amount'))
    except (TypeError, ValueError):
        flash('Invalid settlement data.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    # Only the debtor (payer) can mark their own debt settled
    if payer_id != current_user.id:
        flash('You can only mark your own debts as settled.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    # Find or create the settlement record
    s = Settlement.query.filter_by(
        trip_id=trip_id, payer_id=payer_id, payee_id=payee_id
    ).first()

    if s is None:
        s = Settlement(
            trip_id=trip_id,
            payer_id=payer_id,
            payee_id=payee_id,
            amount=amount,
            is_settled=True,
            settled_at=datetime.now(timezone.utc)
        )
        db.session.add(s)
    else:
        s.is_settled = True
        s.amount = amount
        s.settled_at = datetime.now(timezone.utc)

    db.session.commit()
    flash('Payment marked as settled! ✓', 'success')
    return redirect(url_for('trips.detail', trip_id=trip.id) + '#settlement-summary')


@expenses.route('/my-expenses')
@login_required
def my_expenses():
    """Show all trips the user belongs to with per-trip expense summary."""
    trip_ids = current_user._all_trip_ids()
    trips_list = Trip.query.filter(Trip.id.in_(trip_ids)).order_by(Trip.start_date.desc()).all() \
        if trip_ids else []

    rows = []
    pending_balance = 0.0
    for trip in trips_list:
        raw_balance = trip.balance_for(current_user.id)
        per_person  = trip.your_share(current_user.id)

        # -----------------------------------------------------------------
        # Correct settlement status: drive purely from Settlement records
        # against the computed transfer list, NOT from raw_balance alone.
        #
        # Bug that was fixed: Palak pays Khushi ₹390 (settled) and owes
        # Ruhi ₹90 (not settled).  Palak's raw balance could be 0 because
        # she happened to pay exactly her economic share, but she still has
        # an unsettled transfer to Ruhi.  The old code short-circuited on
        # raw_balance==0 and wrongly called the trip fully settled.
        # -----------------------------------------------------------------
        computed_transfers = trip.calculate_settlements()

        # Rows where current user is the debtor (must pay someone)
        my_debts = [t for t in computed_transfers if t['debtor'].id == current_user.id]
        # Rows where current user is the creditor (expects payment)
        my_credits = [t for t in computed_transfers if t['creditor'].id == current_user.id]

        if not my_debts and not my_credits:
            # User has no transfer obligation in this trip
            settled = True
            unsettled_amount = 0.0
        else:
            # Fetch all settled Settlement records involving this user in this trip
            settled_payer_ids = {
                s.payer_id
                for s in Settlement.query.filter_by(
                    trip_id=trip.id, payee_id=current_user.id, is_settled=True
                ).all()
            }
            settled_payee_ids = {
                s.payee_id
                for s in Settlement.query.filter_by(
                    trip_id=trip.id, payer_id=current_user.id, is_settled=True
                ).all()
            }

            # An individual transfer is settled only if the Settlement record exists
            # and is_settled=True for that exact (payer, payee) pair.
            unsettled_debt_amount = sum(
                t['amount'] for t in my_debts
                if t['creditor'].id not in settled_payee_ids
            )
            unsettled_credit_amount = sum(
                t['amount'] for t in my_credits
                if t['debtor'].id not in settled_payer_ids
            )

            # From the user's perspective: pending balance is what they still owe.
            # If they're a creditor with outstanding amounts, that's positive (owed to them).
            unsettled_amount = unsettled_credit_amount - unsettled_debt_amount
            settled = (unsettled_debt_amount < 0.01 and unsettled_credit_amount < 0.01)

        if not settled:
            pending_balance += unsettled_amount

        rows.append({
            'trip':       trip,
            'per_person': round(per_person, 2),
            'balance':    round(raw_balance, 2),
            'settled':    settled,
        })

    return render_template('expenses/my_expenses.html',
        rows=rows,
        pending_balance=round(pending_balance, 2)
    )
