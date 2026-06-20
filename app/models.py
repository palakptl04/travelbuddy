from app.extensions import db, login_manager
from flask_login import UserMixin
from datetime import datetime, timezone, date as _date, timedelta
from sqlalchemy import select


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(100), nullable=False)
    email          = db.Column(db.String(150), unique=True, nullable=False)
    password_hash  = db.Column(db.String(255), nullable=False)
    travel_style   = db.Column(db.String(50), default='flexible')
    bio            = db.Column(db.Text, default='')
    interests      = db.Column(db.String(255), default='')
    phone          = db.Column(db.String(20), default='')
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def interests_list(self):
        return [i.strip() for i in self.interests.split(',') if i.strip()] if self.interests else []

    owned_trips    = db.relationship('Trip', back_populates='owner', lazy='dynamic')
    memberships    = db.relationship('TripMember', back_populates='user', lazy='dynamic')
    expenses_paid  = db.relationship('Expense', back_populates='paid_by', lazy='dynamic')

    def __repr__(self):
        return f'<User {self.email}>'

    def get_active_trips(self):
        """All active trips the user owns or has been accepted into — single query."""
        from sqlalchemy import or_
        # Trips owned by user with status ACTIVE
        owned = Trip.query.filter_by(owner_id=self.id, status='ACTIVE').all()
        # Trips the user is an accepted member of (not owner)
        joined = (
            Trip.query
            .join(TripMember, TripMember.trip_id == Trip.id)
            .filter(
                TripMember.user_id == self.id,
                TripMember.status == 'accepted',
                Trip.status == 'active',
                Trip.owner_id != self.id
            )
            .all()
        )
        return owned + joined

    def get_upcoming_trips(self):
        """All trips that are not active, completed, or cancelled."""
        upcoming_statuses = ['OPEN', 'AWAITING_CONFIRMATION', 'CONFIRMED']
        owned = Trip.query.filter(
            Trip.owner_id == self.id,
            Trip.status.in_(upcoming_statuses)
        ).all()
        joined = (
            Trip.query
            .join(TripMember, TripMember.trip_id == Trip.id)
            .filter(
                TripMember.user_id == self.id,
                TripMember.status == 'accepted',
                Trip.status.in_(upcoming_statuses),
                Trip.owner_id != self.id
            )
            .all()
        )
        return owned + joined

    def get_pending_requests(self):
        """Requests others sent to join MY trips."""
        my_trip_ids = [t.id for t in Trip.query.filter_by(owner_id=self.id).all()]
        return TripMember.query.filter(
            TripMember.trip_id.in_(my_trip_ids),
            TripMember.status == 'pending'
        ).all()

    def get_total_balance(self):
        """Net amount owed across all trips (positive = others owe you).
        Avoids N+1 by loading all trips in a single query.
        """
        total = 0.0
        all_trip_ids = self._all_trip_ids()
        if not all_trip_ids:
            return 0.0
        # Single query to fetch all relevant trips
        trips = Trip.query.filter(Trip.id.in_(all_trip_ids)).all()
        for trip in trips:
            total += trip.balance_for(self.id)
        return round(total, 2)

    def _all_trip_ids(self):
        owned = [t.id for t in Trip.query.filter_by(owner_id=self.id).all()]
        joined = [m.trip_id for m in
                  TripMember.query.filter_by(user_id=self.id, status='accepted').all()]
        return list(set(owned + joined))


class Trip(db.Model):
    __tablename__ = 'trips'
    __table_args__ = (
        db.Index('ix_trips_owner_status', 'owner_id', 'status'),
        db.Index('ix_trips_public_start', 'is_public', 'start_date'),
    )

    id          = db.Column(db.Integer, primary_key=True)
    owner_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title       = db.Column(db.String(150), nullable=False)
    destination = db.Column(db.String(150), nullable=False)
    departure_city = db.Column(db.String(100), default='')
    start_date  = db.Column(db.Date, nullable=False)
    end_date    = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, default='')
    budget_min  = db.Column(db.Float, default=0)
    budget_max  = db.Column(db.Float, default=0)
    max_members = db.Column(db.Integer, default=4)
    status      = db.Column(db.String(20), default='OPEN')  # OPEN, AWAITING_CONFIRMATION, CONFIRMED, ACTIVE, COMPLETED, CANCELLED
    confirmation_deadline = db.Column(db.DateTime, nullable=True)
    confirmation_started_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    is_public   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    owner    = db.relationship('User', back_populates='owned_trips')
    members  = db.relationship('TripMember', back_populates='trip', lazy='dynamic',
                               cascade='all, delete-orphan')
    expenses = db.relationship('Expense', back_populates='trip', lazy='dynamic',
                               cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Trip {self.title}>'

    # ------------------------------------------------------------------ #
    # Date-derived computed properties (never stored in DB)              #
    # ------------------------------------------------------------------ #

    @property
    def computed_status(self):
        """Compatibility helper for date-only display.

        Returns 'upcoming', 'ongoing', or 'completed' based on today's date.
        """
        today = _date.today()
        if today < self.start_date:
            return 'upcoming'
        elif today <= self.end_date:
            return 'ongoing'
        else:
            return 'completed'

    @property
    def joining_closed(self):
        """Joining closes when the trip is no longer OPEN or 1 day before start."""
        if self.status and self.status.upper() != 'OPEN':
            return True
        return _date.today() >= (self.start_date - timedelta(days=1))

    @property
    def main_confirmation_deadline(self):
        return self.start_date - timedelta(days=2)

    @property
    def confirmation_window_deadline(self):
        if not self.confirmation_started_at:
            return None
        return self.confirmation_started_at + timedelta(hours=24)

    def is_open(self):
        return self.status and self.status.upper() == 'OPEN'

    def is_awaiting_confirmation(self):
        return self.status and self.status.upper() == 'AWAITING_CONFIRMATION'

    def is_confirmed(self):
        return self.status and self.status.upper() == 'CONFIRMED'

    def is_active(self):
        return self.status and self.status.upper() == 'ACTIVE'

    def is_completed(self):
        return self.status and self.status.upper() == 'COMPLETED'

    def is_cancelled(self):
        return self.status and self.status.upper() == 'CANCELLED'

    @property
    def status_label(self):
        return {
            'OPEN': 'Open',
            'AWAITING_CONFIRMATION': 'Awaiting Confirmation',
            'CONFIRMED': 'Confirmed',
            'ACTIVE': 'Active',
            'COMPLETED': 'Completed',
            'CANCELLED': 'Cancelled',
        }.get(self.status.upper() if self.status else '', 'Unknown')

    def member_count(self):
        return self.members.filter_by(status='accepted').count() + 1  # +1 for owner

    def accepted_members(self):
        return self.members.filter_by(status='accepted').all()

    def confirmed_members(self):
        return self.members.filter_by(status='accepted', is_confirmed=True).all()

    def all_participants(self):
        participants = [self.owner]
        participants.extend(self.accepted_members())
        return participants

    def is_full(self):
        return self.member_count() >= self.max_members

    def all_members_confirmed(self):
        accepted = self.accepted_members()
        if not accepted:
            return True
        return all(member.is_confirmed for member in accepted)

    def can_join(self):
        return self.is_open() and not self.joining_closed and not self.is_full()

    def can_leave(self):
        return self.is_open() and not self.joining_closed

    def can_cancel(self):
        today = _date.today()
        return self.status and self.status.upper() != 'CANCELLED' and today < self.start_date

    def cancel(self):
        self.status = 'CANCELLED'
        self.cancelled_at = datetime.now(timezone.utc)

    def can_add_expense(self):
        return self.status and self.status.upper() in ('CONFIRMED', 'ACTIVE')

    def confirmation_window_open(self):
        if not self.confirmation_window_deadline:
            return False
        return self.confirmation_started_at is not None and _date.today() < self.confirmation_window_deadline.date()

    def confirmation_window_expired(self):
        if not self.confirmation_started_at:
            return False
        # SQLite returns datetimes as offset-naive; compare with utcnow() to avoid
        # TypeError: can't compare offset-naive and offset-aware datetimes
        deadline = self.confirmation_window_deadline
        if deadline is None:
            return False
        now_naive = datetime.utcnow()
        # Strip tzinfo if the deadline was somehow stored with it
        if deadline.tzinfo is not None:
            deadline = deadline.replace(tzinfo=None)
        return now_naive >= deadline

    def start_confirmation(self):
        if self.status and self.status.upper() == 'AWAITING_CONFIRMATION':
            return
        self.status = 'AWAITING_CONFIRMATION'
        self.confirmation_started_at = datetime.now(timezone.utc)
        if not self.confirmation_deadline:
            self.confirmation_deadline = datetime.combine(self.main_confirmation_deadline, datetime.min.time()).replace(tzinfo=timezone.utc)

    def finalize_confirmed_members(self):
        for member in self.accepted_members():
            if not member.is_confirmed:
                member.status = 'declined'
        self.status = 'CONFIRMED'
        if not self.confirmation_started_at:
            self.confirmation_started_at = datetime.now(timezone.utc)

    def reopen_missing_slots(self):
        if self.status and self.status.upper() != 'AWAITING_CONFIRMATION':
            return
        self.status = 'OPEN'
        self.confirmation_started_at = None
        self.confirmation_deadline = datetime.combine(self.main_confirmation_deadline, datetime.min.time()).replace(tzinfo=timezone.utc)
        for member in self.accepted_members():
            if not member.is_confirmed:
                member.status = 'declined'

    def maybe_start_confirmation_if_needed(self):
        today = _date.today()
        if not self.is_open():
            return False
        if self.is_full() or today >= self.main_confirmation_deadline:
            self.start_confirmation()
            return True
        return False

    def refresh_status(self):
        if self.is_cancelled() or self.status is None:
            return False

        today = _date.today()
        updated = False

        if self.status.upper() in ('OPEN', 'AWAITING_CONFIRMATION', 'CONFIRMED'):
            if today > self.end_date:
                self.status = 'COMPLETED'
                updated = True
            elif today >= self.start_date:
                self.status = 'ACTIVE'
                updated = True
        elif self.status.upper() == 'ACTIVE':
            if today > self.end_date:
                self.status = 'COMPLETED'
                updated = True

        return updated

    def confirm_member(self, member):
        if member.trip_id != self.id:
            return False
        member.is_confirmed = True
        member.confirmed_at = datetime.now(timezone.utc)
        if self.all_members_confirmed():
            self.status = 'CONFIRMED'
        return True

    def total_spent(self):
        return round(sum(e.amount for e in self.expenses), 2)

    def your_share(self, user_id):
        mc = self.member_count()
        return round(self.total_spent() / mc, 2) if mc else 0.0

    def balance_for(self, user_id):
        paid = sum(e.amount for e in self.expenses.filter_by(paid_by_id=user_id))
        share = self.your_share(user_id)
        return round(paid - share, 2)

    def accepted_members(self):
        return TripMember.query.filter_by(trip_id=self.id, status='accepted').all()

    def is_full(self):
        return self.member_count() >= self.max_members

    def all_member_users(self):
        """Owner + accepted members, as User objects."""
        users = [self.owner]
        for m in self.accepted_members():
            users.append(m.user)
        return users

    def settlement_summary(self):
        """List of dicts: user, paid, share, balance for each member."""
        summary = []
        for user in self.all_member_users():
            paid = sum(e.amount for e in self.expenses.filter_by(paid_by_id=user.id))
            share = self.your_share(user.id)
            summary.append({
                'user': user,
                'paid': round(paid, 2),
                'share': share,
                'balance': round(paid - share, 2)
            })
        return summary

    def calculate_settlements(self):
        """
        Greedy minimum-transfers algorithm (Splitwise-style).

        Returns a list of dicts:
          { 'debtor': User, 'creditor': User, 'amount': float }

        Example: A paid ₹900, B paid ₹1200, C paid ₹0  →  3 members, share = ₹700
          Net: A=+200, B=+500, C=-700
          Result: [C→B ₹500, C→A ₹200]  (only 2 transactions for 3 people)
        """
        members = self.all_member_users()
        mc = len(members)
        if mc == 0:
            return []

        total = sum(e.amount for e in self.expenses)
        share = total / mc

        # Build net balance list [(user, net_balance)]
        balances = []
        for user in members:
            paid = sum(e.amount for e in self.expenses.filter_by(paid_by_id=user.id))
            balances.append([user, round(paid - share, 2)])

        # Separate into creditors (balance > 0) and debtors (balance < 0)
        creditors = sorted([b for b in balances if b[1] > 0.009], key=lambda x: -x[1])
        debtors   = sorted([b for b in balances if b[1] < -0.009], key=lambda x: x[1])

        settlements = []
        i, j = 0, 0
        while i < len(debtors) and j < len(creditors):
            debtor, debt     = debtors[i]
            creditor, credit = creditors[j]
            transfer = round(min(-debt, credit), 2)

            settlements.append({
                'debtor':   debtor,
                'creditor': creditor,
                'amount':   transfer
            })

            debtors[i][1]   = round(debt + transfer, 2)
            creditors[j][1] = round(credit - transfer, 2)

            if abs(debtors[i][1]) < 0.01:
                i += 1
            if abs(creditors[j][1]) < 0.01:
                j += 1

        return settlements

    def pending_request_for(self, user_id):
        return TripMember.query.filter_by(trip_id=self.id, user_id=user_id).first()


class TripMember(db.Model):
    __tablename__ = 'trip_members'
    __table_args__ = (
        db.Index('ix_trip_members_user_status', 'user_id', 'status'),
        db.Index('ix_trip_members_trip_status', 'trip_id', 'status'),
        db.UniqueConstraint('trip_id', 'user_id', name='uq_trip_member'),
    )

    id            = db.Column(db.Integer, primary_key=True)
    trip_id       = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status        = db.Column(db.String(20), default='pending')  # pending, accepted, declined
    is_confirmed  = db.Column(db.Boolean, default=False, nullable=False)
    confirmed_at  = db.Column(db.DateTime, nullable=True)
    joined_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    trip = db.relationship('Trip', back_populates='members')
    user = db.relationship('User', back_populates='memberships')

    def __repr__(self):
        return f'<TripMember trip={self.trip_id} user={self.user_id} status={self.status} confirmed={self.is_confirmed}>'


class Settlement(db.Model):
    __tablename__ = 'settlements'
    __table_args__ = (
        db.Index('ix_settlements_trip_payer', 'trip_id', 'payer_id'),
        db.Index('ix_settlements_trip_payee', 'trip_id', 'payee_id'),
    )

    id         = db.Column(db.Integer, primary_key=True)
    trip_id    = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    payer_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)   # debtor
    payee_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)   # creditor
    amount     = db.Column(db.Float, nullable=False)
    is_settled = db.Column(db.Boolean, default=False, nullable=False)
    settled_at = db.Column(db.DateTime, nullable=True)

    trip  = db.relationship('Trip', backref=db.backref('settlements', lazy='dynamic',
                                                        cascade='all, delete-orphan'))
    payer = db.relationship('User', foreign_keys=[payer_id])
    payee = db.relationship('User', foreign_keys=[payee_id])

    def __repr__(self):
        return f'<Settlement trip={self.trip_id} {self.payer_id}→{self.payee_id} ₹{self.amount} settled={self.is_settled}>'


class Expense(db.Model):
    __tablename__ = 'expenses'
    __table_args__ = (
        db.Index('ix_expenses_trip_paid', 'trip_id', 'paid_by_id'),
        db.Index('ix_expenses_trip_date', 'trip_id', 'date'),
    )

    id          = db.Column(db.Integer, primary_key=True)
    trip_id     = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    paid_by_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title       = db.Column(db.String(150), nullable=False)
    amount      = db.Column(db.Float, nullable=False)
    category    = db.Column(db.String(50), default='general')
    date        = db.Column(db.Date, default=lambda: datetime.now(timezone.utc).date())
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    trip    = db.relationship('Trip', back_populates='expenses')
    paid_by = db.relationship('User', back_populates='expenses_paid')

    def __repr__(self):
        return f'<Expense {self.title} ₹{self.amount}>'
