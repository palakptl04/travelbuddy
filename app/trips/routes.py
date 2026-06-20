from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import or_
from datetime import date, datetime, timezone

from app.trips import trips
from app.trips.forms import TripForm
from app.expenses.forms import ExpenseForm
from app.models import Trip, TripMember, Expense, User, Settlement  # noqa: F401 (Expense kept for potential future use)
from app.cities import GUJARAT_CITIES, NEARBY_CITIES
from app.extensions import db

BROWSE_PER_PAGE = 10


@trips.route('/trips')
def index():
    my_trips = []
    pending_ids = set()
    accepted_ids = set()

    if current_user.is_authenticated:
        # Trips the current user owns or has joined
        my_trip_ids = current_user._all_trip_ids()
        my_trips = Trip.query.filter(Trip.id.in_(my_trip_ids)).all() if my_trip_ids else []

        pending_ids = {m.trip_id for m in
                       TripMember.query.filter_by(user_id=current_user.id, status='pending').all()}
        accepted_ids = {m.trip_id for m in
                        TripMember.query.filter_by(user_id=current_user.id, status='accepted').all()}

        # Browse: open public trips not already owned/joined by the user
        my_trip_ids_set = set(my_trip_ids)
    else:
        my_trip_ids_set = set()

    # Browse: open public trips that are still accepting buddy requests.
    query = Trip.query.filter(
        Trip.is_public == True,   # noqa: E712
        Trip.status == 'OPEN'
    )
    if my_trip_ids_set:
        query = query.filter(~Trip.id.in_(my_trip_ids_set))

    destination = request.args.get('destination', '').strip()
    budget = request.args.get('budget', '').strip()
    page = request.args.get('page', 1, type=int)

    if destination:
        query = query.filter(Trip.destination == destination)
    if budget:
        try:
            b = float(budget)
            query = query.filter(Trip.budget_min <= b)
        except ValueError:
            pass

    pagination = query.order_by(Trip.start_date.asc()).paginate(
        page=page, per_page=BROWSE_PER_PAGE, error_out=False
    )
    browse_trips = pagination.items

    return render_template('trips/index.html',
        my_trips=my_trips,
        browse_trips=browse_trips,
        pagination=pagination,
        pending_ids=pending_ids,
        accepted_ids=accepted_ids,
        destination=destination,
        budget=budget,
        city_choices=GUJARAT_CITIES + NEARBY_CITIES,
        today=date.today()
    )


@trips.route('/trips/create', methods=['GET', 'POST'])
@login_required
def create():
    form = TripForm()
    if form.validate_on_submit():
        trip = Trip(
            owner_id=current_user.id,
            title=form.title.data.strip(),
            destination=form.destination.data.strip(),
            departure_city=form.departure_city.data.strip(),
            description=form.description.data.strip() if form.description.data else '',
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            budget_min=form.budget_min.data,
            budget_max=form.budget_max.data,
            max_members=form.max_members.data,
            status='OPEN',
            is_public=True
        )
        db.session.add(trip)
        db.session.commit()
        flash('Trip created successfully!', 'success')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    return render_template('trips/create.html', form=form)


@trips.route('/trips/<int:trip_id>')
def detail(trip_id):
    # Guests are redirected to login
    if not current_user.is_authenticated:
        flash('Login to view full trip details and send a buddy request.', 'error')
        return redirect(url_for('auth.login', next=request.url))

    trip = db.get_or_404(Trip, trip_id)

    status_changed = False
    if trip.maybe_start_confirmation_if_needed():
        status_changed = True
    if trip.is_awaiting_confirmation() and trip.confirmation_window_expired():
        trip.finalize_confirmed_members()
        status_changed = True
    if trip.refresh_status():
        status_changed = True
    if status_changed:
        db.session.commit()

    is_owner = trip.owner_id == current_user.id
    membership = TripMember.query.filter_by(trip_id=trip.id, user_id=current_user.id).first()
    is_member = is_owner or (membership is not None and membership.status == 'accepted')

    pending_requests = []
    if is_owner:
        pending_requests = TripMember.query.filter_by(trip_id=trip.id, status='pending').all()

    expense_form = None
    if is_member:
        expense_form = ExpenseForm()
        expense_form.paid_by_id.choices = [(current_user.id, current_user.name)]
        if not expense_form.expense_date.data:
            expense_form.expense_date.data = date.today()

    expenses_list = trip.expenses.order_by(Expense.date.desc(), Expense.created_at.desc()).all()

    # Build settlement lookup: {(payer_id, payee_id): Settlement}
    settlement_lookup = {}
    for s in trip.settlements.all():
        settlement_lookup[(s.payer_id, s.payee_id)] = s

    return render_template('trips/detail.html',
        trip=trip,
        is_owner=is_owner,
        is_member=is_member,
        membership=membership,
        pending_requests=pending_requests,
        expense_form=expense_form,
        expenses_list=expenses_list,
        settlement=trip.settlement_summary(),
        settlements=trip.calculate_settlements(),
        settlement_lookup=settlement_lookup,
        today=date.today()
    )


@trips.route('/trips/<int:trip_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(trip_id):
    trip = db.get_or_404(Trip, trip_id)
    if trip.owner_id != current_user.id:
        flash('Not authorised to edit this trip.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    form = TripForm(obj=trip)
    if form.validate_on_submit():
        trip.title = form.title.data.strip()
        trip.destination = form.destination.data.strip()
        trip.departure_city = form.departure_city.data.strip()
        trip.description = form.description.data.strip() if form.description.data else ''
        trip.start_date = form.start_date.data
        trip.end_date = form.end_date.data
        trip.budget_min = form.budget_min.data
        trip.budget_max = form.budget_max.data
        trip.max_members = form.max_members.data
        db.session.commit()
        flash('Trip updated successfully.', 'success')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    return render_template('trips/edit.html', form=form, trip=trip)


@trips.route('/trips/<int:trip_id>/cancel', methods=['POST'])
@login_required
def cancel(trip_id):
    trip = db.get_or_404(Trip, trip_id)
    if trip.owner_id != current_user.id:
        flash('Not authorised to cancel this trip.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    if not trip.can_cancel():
        flash('This trip cannot be cancelled at this time.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    trip.cancel()
    db.session.commit()
    flash('Trip cancelled.', 'success')
    return redirect(url_for('trips.index'))


@trips.route('/trips/<int:trip_id>/request', methods=['POST'])
@login_required
def send_request(trip_id):
    trip = db.get_or_404(Trip, trip_id)
    if trip.owner_id == current_user.id:
        flash("You can't send a buddy request to your own trip.", 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    if not trip.can_join():
        flash('Joining is closed for this trip.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    if trip.is_full():
        flash('This trip is already full.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    existing = TripMember.query.filter_by(trip_id=trip.id, user_id=current_user.id).first()
    if existing:
        flash('You have already sent a request for this trip.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    member = TripMember(trip_id=trip.id, user_id=current_user.id, status='pending')
    db.session.add(member)
    db.session.commit()
    flash('Buddy request sent! The trip creator will review it.', 'success')
    return redirect(url_for('trips.detail', trip_id=trip.id))


@trips.route('/trips/<int:trip_id>/request/<int:member_id>/accept', methods=['POST'])
@login_required
def accept_request(trip_id, member_id):
    trip = db.get_or_404(Trip, trip_id)
    member = db.get_or_404(TripMember, member_id)

    if trip.owner_id != current_user.id or member.trip_id != trip.id:
        flash('Not authorised.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    if not trip.can_join():
        flash('Joining is closed for this trip. No new members can be accepted.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    if trip.is_full():
        flash('Trip is already full. Cannot accept more members.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    member.status = 'accepted'
    if trip.maybe_start_confirmation_if_needed():
        db.session.add(trip)
    db.session.commit()
    flash(f'{member.user.name} has been added to {trip.title}.', 'success')
    return redirect(url_for('trips.detail', trip_id=trip_id))


@trips.route('/trips/<int:trip_id>/request/<int:member_id>/decline', methods=['POST'])
@login_required
def decline_request(trip_id, member_id):
    trip = db.get_or_404(Trip, trip_id)
    member = db.get_or_404(TripMember, member_id)

    if trip.owner_id != current_user.id or member.trip_id != trip.id:
        flash('Not authorised.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    member.status = 'declined'
    db.session.commit()
    flash(f'Request from {member.user.name} declined.', 'success')
    return redirect(url_for('trips.detail', trip_id=trip_id))


@trips.route('/trips/<int:trip_id>/confirm', methods=['POST'])
@login_required
def confirm_participation(trip_id):
    trip = db.get_or_404(Trip, trip_id)
    membership = TripMember.query.filter_by(
        trip_id=trip.id, user_id=current_user.id, status='accepted'
    ).first()

    if not membership:
        flash('Only accepted trip members can confirm participation.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    if not trip.is_awaiting_confirmation():
        flash('This trip is not awaiting confirmation.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    if membership.is_confirmed:
        flash('You have already confirmed your participation.', 'info')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    trip.confirm_member(membership)
    db.session.commit()
    flash('Your participation is confirmed.', 'success')
    return redirect(url_for('trips.detail', trip_id=trip.id))


@trips.route('/trips/<int:trip_id>/leave', methods=['POST'])
@login_required
def leave(trip_id):
    trip = db.get_or_404(Trip, trip_id)

    if trip.owner_id == current_user.id:
        flash('Trip owner cannot leave. Cancel the trip instead.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    membership = TripMember.query.filter_by(
        trip_id=trip_id, user_id=current_user.id, status='accepted'
    ).first()
    if not membership:
        flash('You are not an accepted member of this trip.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    if not trip.can_leave():
        flash(
            'You cannot leave this trip once joining has closed.',
            'error'
        )
        return redirect(url_for('trips.detail', trip_id=trip_id))

    db.session.delete(membership)
    db.session.commit()
    flash(f'You have left "{trip.title}".', 'success')
    return redirect(url_for('trips.index'))
