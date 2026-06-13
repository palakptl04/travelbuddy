from flask import redirect, url_for, flash
from flask_login import login_required, current_user

from app.expenses import expenses
from app.expenses.forms import ExpenseForm
from app.models import Trip, TripMember, Expense
from app.extensions import db


@expenses.route('/trips/<int:trip_id>/expenses/add', methods=['POST'])
@login_required
def add(trip_id):
    trip = Trip.query.get_or_404(trip_id)

    is_owner = trip.owner_id == current_user.id
    membership = TripMember.query.filter_by(trip_id=trip.id, user_id=current_user.id).first()
    is_member = is_owner or (membership is not None and membership.status == 'accepted')

    if not is_member:
        flash('Only trip members can add expenses.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    form = ExpenseForm()
    form.paid_by_id.choices = [(u.id, u.name) for u in trip.all_member_users()]

    if form.validate_on_submit():
        expense = Expense(
            trip_id=trip.id,
            paid_by_id=form.paid_by_id.data,
            title=form.title.data.strip(),
            amount=form.amount.data,
            category=form.category.data
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
    trip = Trip.query.get_or_404(trip_id)
    expense = Expense.query.get_or_404(expense_id)

    if expense.trip_id != trip.id:
        flash('Invalid request.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    if expense.paid_by_id != current_user.id and trip.owner_id != current_user.id:
        flash('Not authorised to delete this expense.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    db.session.delete(expense)
    db.session.commit()
    flash('Expense removed.', 'success')
    return redirect(url_for('trips.detail', trip_id=trip.id))
