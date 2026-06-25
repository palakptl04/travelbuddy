"""
conflict_utils.py — shared helpers for request conflict management.

Imported by both trips/routes.py and dashboard/routes.py to avoid
circular imports.
"""

from app.extensions import db
from app.models import Trip, TripMember


def check_date_overlap(start_a, end_a, start_b, end_b) -> bool:
    """True if two date ranges overlap (inclusive on both ends)."""
    return start_a <= end_b and start_b <= end_a


def find_confirmed_overlap(user_id: int, trip: Trip):
    """
    Check whether user_id is already an accepted member in any OTHER trip
    whose dates overlap with `trip` and whose status is CONFIRMED / ACTIVE /
    AWAITING_CONFIRMATION.

    Returns the conflicting Trip object if found, else None.
    """
    accepted_memberships = (
        TripMember.query
        .filter_by(user_id=user_id, status=TripMember.STATUS_ACCEPTED)
        .filter(TripMember.trip_id != trip.id)
        .all()
    )
    for membership in accepted_memberships:
        other_trip = membership.trip
        # Only block on trips the user is genuinely committed to
        if other_trip.status.upper() not in ('CONFIRMED', 'ACTIVE', 'AWAITING_CONFIRMATION'):
            continue
        if check_date_overlap(
            trip.start_date, trip.end_date,
            other_trip.start_date, other_trip.end_date
        ):
            return other_trip
    return None


def auto_cancel_conflicting_pending(user_id: int, confirmed_trip: Trip) -> int:
    """
    After user_id is confirmed on `confirmed_trip`, cancel all their other
    PENDING requests for trips with overlapping dates.

    Sets status=CANCELLED with cancel_reason='trip conflict'.
    Does NOT commit — caller is responsible for committing.

    Returns number of rows cancelled.
    """
    pending_memberships = (
        TripMember.query
        .filter_by(user_id=user_id, status=TripMember.STATUS_PENDING)
        .filter(TripMember.trip_id != confirmed_trip.id)
        .all()
    )
    cancelled_count = 0
    for membership in pending_memberships:
        other_trip = membership.trip
        if check_date_overlap(
            confirmed_trip.start_date, confirmed_trip.end_date,
            other_trip.start_date, other_trip.end_date
        ):
            membership.cancel(reason='trip conflict')
            cancelled_count += 1
    return cancelled_count


def do_accept_request(member: TripMember, trip: Trip):
    """
    Atomically accept a buddy request with conflict detection.

    Uses with_for_update() to lock the TripMember row and prevent race
    conditions when multiple owners try to accept the same user simultaneously.

    Returns (success: bool, error_message: str | None).
    Caller must NOT have started their own transaction.
    """
    try:
        # Re-fetch with row-level lock to prevent race conditions
        locked_member = (
            TripMember.query
            .filter_by(id=member.id)
            .with_for_update()
            .first()
        )
        if locked_member is None:
            return False, 'Request no longer exists.'

        if locked_member.status != TripMember.STATUS_PENDING:
            return False, (
                f'Request is no longer pending (current status: {locked_member.status_label}).'
            )

        # Check if user is already confirmed in an overlapping trip
        conflicting_trip = find_confirmed_overlap(locked_member.user_id, trip)
        if conflicting_trip:
            return False, (
                f'{locked_member.user.name} is already confirmed on '
                f'"{conflicting_trip.title}" '
                f'({conflicting_trip.start_date.strftime("%b %d")}–'
                f'{conflicting_trip.end_date.strftime("%b %d, %Y")}), '
                f'which overlaps with this trip. Cannot accept.'
            )

        # Accept the request
        locked_member.status = TripMember.STATUS_ACCEPTED

        # Auto-cancel other pending requests for overlapping trips
        auto_cancel_conflicting_pending(locked_member.user_id, trip)

        db.session.commit()
        return True, None

    except Exception as exc:
        db.session.rollback()
        return False, f'An error occurred while accepting the request: {exc}'
