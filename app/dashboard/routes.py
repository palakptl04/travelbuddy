from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.dashboard import dashboard
from app.models import Trip, TripMember, Expense, User
from app.extensions import db
from datetime import date


@dashboard.route('/dashboard')
@login_required
def index():
    active_trips   = current_user.get_active_trips()
    upcoming_trips = current_user.get_upcoming_trips()
    pending_reqs   = current_user.get_pending_requests()
    net_balance    = current_user.get_total_balance()

    # Recent expenses across all user's trips
    all_trip_ids = current_user._all_trip_ids()
    recent_expenses = (Expense.query
                       .filter(Expense.trip_id.in_(all_trip_ids))
                       .order_by(Expense.created_at.desc())
                       .limit(5)
                       .all()) if all_trip_ids else []

    # Stats
    total_trips    = len(active_trips) + len(upcoming_trips)
    total_buddies  = _count_unique_buddies(current_user)
    trips_for_card = (active_trips + upcoming_trips)[:6]

    return render_template('dashboard/index.html',
        active_trips=active_trips,
        upcoming_trips=upcoming_trips,
        pending_reqs=pending_reqs,
        recent_expenses=recent_expenses,
        net_balance=net_balance,
        total_trips=total_trips,
        total_buddies=total_buddies,
        trips_for_card=trips_for_card,
        today=date.today()
    )


@dashboard.route('/dashboard/request/<int:member_id>/accept', methods=['POST'])
@login_required
def accept_request(member_id):
    member = TripMember.query.get_or_404(member_id)
    if member.trip.owner_id != current_user.id:
        flash('Not authorised.', 'error')
        return redirect(url_for('dashboard.index'))
    member.status = 'accepted'
    db.session.commit()
    flash(f'{member.user.name} has been added to {member.trip.title}.', 'success')
    return redirect(url_for('dashboard.index'))


@dashboard.route('/dashboard/request/<int:member_id>/decline', methods=['POST'])
@login_required
def decline_request(member_id):
    member = TripMember.query.get_or_404(member_id)
    if member.trip.owner_id != current_user.id:
        flash('Not authorised.', 'error')
        return redirect(url_for('dashboard.index'))
    member.status = 'declined'
    db.session.commit()
    flash(f'Request from {member.user.name} declined.', 'success')
    return redirect(url_for('dashboard.index'))


def _count_unique_buddies(user):
    all_trip_ids = user._all_trip_ids()
    if not all_trip_ids:
        return 0
    members = TripMember.query.filter(
        TripMember.trip_id.in_(all_trip_ids),
        TripMember.status == 'accepted',
        TripMember.user_id != user.id
    ).all()
    owners = [Trip.query.get(tid).owner_id for tid in all_trip_ids
              if Trip.query.get(tid) and Trip.query.get(tid).owner_id != user.id]
    unique = set([m.user_id for m in members] + owners)
    return len(unique)
