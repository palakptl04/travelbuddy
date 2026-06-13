from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import or_
from datetime import date

from app.trips import trips
from app.trips.forms import TripForm
from app.expenses.forms import ExpenseForm
from app.models import Trip, TripMember, Expense, User
from app.cities import GUJARAT_CITIES, NEARBY_CITIES
from app.extensions import db


@trips.route('/trips')
@login_required
def index():
    # Trips the current user owns or has joined
    my_trip_ids = current_user._all_trip_ids()
    my_trips = Trip.query.filter(Trip.id.in_(my_trip_ids)).all() if my_trip_ids else []

    # Browse: open public trips not already owned/joined by the user
    query = Trip.query.filter(Trip.is_public == True)  # noqa: E712
    if my_trip_ids:
        query = query.filter(~Trip.id.in_(my_trip_ids))

    destination = request.args.get('destination', '').strip()
    budget = request.args.get('budget', '').strip()
    open_only = request.args.get('open_only', '').strip()

    if destination:
        query = query.filter(Trip.destination == destination)
    if budget:
        try:
            b = float(budget)
            # Show trips where user's budget falls between trip's min and max
            query = query.filter(Trip.budget_min <= b, Trip.budget_max >= b)
        except ValueError:
            pass

    browse_trips = query.order_by(Trip.start_date.asc()).all()
    # Hide trips that are already full unless "open only" not requested
    if open_only:
        browse_trips = [t for t in browse_trips if not t.is_full()]

    # Pending request trip ids for current user (to disable "request" button)
    pending_ids = {m.trip_id for m in
                   TripMember.query.filter_by(user_id=current_user.id, status='pending').all()}
    accepted_ids = {m.trip_id for m in
                     TripMember.query.filter_by(user_id=current_user.id, status='accepted').all()}

    return render_template('trips/index.html',
        my_trips=my_trips,
        browse_trips=browse_trips,
        pending_ids=pending_ids,
        accepted_ids=accepted_ids,
        destination=destination,
        budget=budget,
        open_only=open_only,
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
            status='upcoming',
            is_public=True
        )
        db.session.add(trip)
        db.session.commit()
        flash('Trip created successfully!', 'success')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    return render_template('trips/create.html', form=form)


@trips.route('/trips/<int:trip_id>')
@login_required
def detail(trip_id):
    trip = Trip.query.get_or_404(trip_id)

    is_owner = trip.owner_id == current_user.id
    membership = TripMember.query.filter_by(trip_id=trip.id, user_id=current_user.id).first()
    is_member = is_owner or (membership is not None and membership.status == 'accepted')

    pending_requests = []
    if is_owner:
        pending_requests = TripMember.query.filter_by(trip_id=trip.id, status='pending').all()

    expense_form = None
    if is_member:
        expense_form = ExpenseForm()
        expense_form.paid_by_id.choices = [
            (u.id, u.name) for u in trip.all_member_users()
        ]

    expenses_list = trip.expenses.order_by(Expense.created_at.desc()).all()

    return render_template('trips/detail.html',
        trip=trip,
        is_owner=is_owner,
        is_member=is_member,
        membership=membership,
        pending_requests=pending_requests,
        expense_form=expense_form,
        expenses_list=expenses_list,
        settlement=trip.settlement_summary(),
        today=date.today()
    )


@trips.route('/trips/<int:trip_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(trip_id):
    trip = Trip.query.get_or_404(trip_id)
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


@trips.route('/trips/<int:trip_id>/delete', methods=['POST'])
@login_required
def delete(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.owner_id != current_user.id:
        flash('Not authorised to delete this trip.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip.id))

    db.session.delete(trip)
    db.session.commit()
    flash('Trip deleted.', 'success')
    return redirect(url_for('trips.index'))


@trips.route('/trips/<int:trip_id>/request', methods=['POST'])
@login_required
def send_request(trip_id):
    trip = Trip.query.get_or_404(trip_id)

    if trip.owner_id == current_user.id:
        flash("You can't send a buddy request to your own trip.", 'error')
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
    trip = Trip.query.get_or_404(trip_id)
    member = TripMember.query.get_or_404(member_id)

    if trip.owner_id != current_user.id or member.trip_id != trip.id:
        flash('Not authorised.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    if trip.is_full():
        flash('Trip is already full. Cannot accept more members.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    member.status = 'accepted'
    db.session.commit()
    flash(f'{member.user.name} has been added to {trip.title}.', 'success')
    return redirect(url_for('trips.detail', trip_id=trip_id))


@trips.route('/trips/<int:trip_id>/request/<int:member_id>/decline', methods=['POST'])
@login_required
def decline_request(trip_id, member_id):
    trip = Trip.query.get_or_404(trip_id)
    member = TripMember.query.get_or_404(member_id)

    if trip.owner_id != current_user.id or member.trip_id != trip.id:
        flash('Not authorised.', 'error')
        return redirect(url_for('trips.detail', trip_id=trip_id))

    member.status = 'declined'
    db.session.commit()
    flash(f'Request from {member.user.name} declined.', 'success')
    return redirect(url_for('trips.detail', trip_id=trip_id))
