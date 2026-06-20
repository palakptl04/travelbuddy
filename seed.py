"""
Run once to populate the database with test data.
Usage: python seed.py
"""

from app import create_app
from app.extensions import db, bcrypt
from app.models import User, Trip, TripMember, Expense
from datetime import date, timedelta

app = create_app()

with app.app_context():
    db.drop_all()
    db.create_all()

    # ── Users ────────────────────────────────────────────────────
    u1 = User(
        name='Aryan Shah',
        email='aryan@test.com',
        password_hash=bcrypt.generate_password_hash('test123').decode(),
        travel_style='adventurous',
        bio='Love road trips and mountains.'
    )
    u2 = User(
        name='Priya Mehta',
        email='priya@test.com',
        password_hash=bcrypt.generate_password_hash('test123').decode(),
        travel_style='relaxed',
        bio='Beach lover, foodie, budget traveller.'
    )
    u3 = User(
        name='Rohan Patel',
        email='rohan@test.com',
        password_hash=bcrypt.generate_password_hash('test123').decode(),
        travel_style='flexible',
        bio='Backpacker at heart.'
    )
    db.session.add_all([u1, u2, u3])
    db.session.flush()

    today = date.today()

    # ── Trips ────────────────────────────────────────────────────
    t1 = Trip(
        owner_id=u1.id,
        title='Gujarat Road Trip',
        destination='Ahmedabad → Dwarka → Somnath',
        start_date=today - timedelta(days=2),
        end_date=today + timedelta(days=3),
        status='ACTIVE',
        is_public=True,
        description='Covering the Saurashtra coast — temples, beaches, and local food.'
    )
    t2 = Trip(
        owner_id=u1.id,
        title='Manali Backpack',
        destination='Manali, Himachal Pradesh',
        start_date=today + timedelta(days=30),
        end_date=today + timedelta(days=37),
        status='OPEN',
        is_public=True,
        description='High altitude trek and cafe hopping in the hills.'
    )
    t3 = Trip(
        owner_id=u2.id,
        title='Goa Weekend',
        destination='North Goa',
        start_date=today + timedelta(days=10),
        end_date=today + timedelta(days=13),
        status='OPEN',
        is_public=True,
        description='Quick beach escape — sunsets, seafood, and chill vibes.'
    )
    db.session.add_all([t1, t2, t3])
    db.session.flush()

    # ── Memberships ──────────────────────────────────────────────
    # Priya accepted on Aryan's Gujarat trip
    m1 = TripMember(trip_id=t1.id, user_id=u2.id, status='accepted')
    # Rohan pending on Aryan's Gujarat trip
    m2 = TripMember(trip_id=t1.id, user_id=u3.id, status='pending')
    # Aryan pending on Priya's Goa trip
    m3 = TripMember(trip_id=t3.id, user_id=u1.id, status='pending')
    db.session.add_all([m1, m2, m3])

    # ── Expenses ─────────────────────────────────────────────────
    expenses = [
        Expense(trip_id=t1.id, paid_by_id=u1.id, title='Hotel Dwarka',
                amount=2400, category='accommodation', date=today - timedelta(days=1)),
        Expense(trip_id=t1.id, paid_by_id=u2.id, title='Petrol',
                amount=800,  category='transport',     date=today - timedelta(days=1)),
        Expense(trip_id=t1.id, paid_by_id=u1.id, title='Dinner at Somnath',
                amount=600,  category='food',          date=today),
        Expense(trip_id=t1.id, paid_by_id=u2.id, title='Temple entry tickets',
                amount=300,  category='activity',      date=today),
        Expense(trip_id=t1.id, paid_by_id=u1.id, title='Breakfast',
                amount=220,  category='food',          date=today),
    ]
    db.session.add_all(expenses)
    db.session.commit()

    print('[OK] Database seeded successfully.\n')
    print('Test accounts:')
    print('  aryan@test.com  / test123  -- 1 active trip, 1 upcoming, owner')
    print('  priya@test.com  / test123  -- member of Gujarat trip, owns Goa trip')
    print('  rohan@test.com  / test123  -- pending request on Gujarat trip')
