"""
cleanup_test_data.py — Remove trips with inaccurate test data from the database.

Targets trips where:
  - budget_min == 0 AND budget_max == 0  (₹0 budget), OR
  - departure_city is blank/null

Run once:  python cleanup_test_data.py

Preview mode (no changes committed) is the default.
Pass --commit to actually delete the rows.
"""

import sys
sys.path.insert(0, '.')

from app import create_app
from app.extensions import db
from app.models import Trip, TripMember, Expense, Settlement

app = create_app()

DRY_RUN = '--commit' not in sys.argv

with app.app_context():
    # --- Find trips with bad data ---
    bad_trips = Trip.query.filter(
        db.or_(
            db.and_(Trip.budget_min == 0, Trip.budget_max == 0),
            db.or_(Trip.departure_city == None, Trip.departure_city == '')
        )
    ).all()

    if not bad_trips:
        print('[OK] No trips with missing/zero budget or departure city found.')
        sys.exit(0)

    print(f'Found {len(bad_trips)} trip(s) with inaccurate data:\n')
    for t in bad_trips:
        print(f'  ID={t.id}  "{t.title}"')
        print(f'    departure_city : {t.departure_city!r}')
        print(f'    budget         : {t.budget_min}–{t.budget_max}')
        print(f'    status         : {t.status}')
        print()

    if DRY_RUN:
        print('DRY RUN — no changes made.')
        print('Re-run with --commit to permanently delete these trips.')
    else:
        for t in bad_trips:
            # Cascade: expenses, members, settlements are deleted via FK cascade
            # but we explicitly clean them to be safe (SQLite may not enforce FKs)
            Settlement.query.filter_by(trip_id=t.id).delete()
            Expense.query.filter_by(trip_id=t.id).delete()
            TripMember.query.filter_by(trip_id=t.id).delete()
            db.session.delete(t)

        db.session.commit()
        print(f'[OK] Deleted {len(bad_trips)} trip(s) and their related data.')
