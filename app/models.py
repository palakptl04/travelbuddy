import secrets
from datetime import date as _date
from datetime import datetime, timedelta, timezone

from flask_login import UserMixin

from app.extensions import db, login_manager


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Extensible contact-encryption hook
# ---------------------------------------------------------------------------
# Currently stores data as plain text.  To enable encryption at rest, replace
# the method below with a Fernet/KMS implementation — no model changes needed.

def _decrypt_contact(value: str) -> str:
    """Decrypt a contact field after loading. Override for real encryption."""
    return value or ''


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

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
    # REST API key (nullable — only created on demand)
    api_key        = db.Column(db.String(64), unique=True, nullable=True, index=True)

    def interests_list(self):
        return [i.strip() for i in self.interests.split(',') if i.strip()] if self.interests else []

    owned_trips    = db.relationship('Trip', back_populates='owner', lazy='dynamic')
    memberships    = db.relationship('TripMember', back_populates='user', lazy='dynamic')
    expenses_paid  = db.relationship('Expense', back_populates='paid_by', lazy='dynamic')

    def __repr__(self):
        return f'<User {self.email}>'

    # ------------------------------------------------------------------ #
    # Contact encryption hooks (extensible — swap for real crypto later) #
    # ------------------------------------------------------------------ #

    def get_phone(self) -> str:
        """Return decrypted phone."""
        return _decrypt_contact(self.phone)

    def get_email(self) -> str:
        """Return decrypted email (email is also the login key — kept plain)."""
        return _decrypt_contact(self.email)

    def generate_api_key(self) -> str:
        """Generate (or rotate) this user's API key. Caller must commit."""
        self.api_key = secrets.token_hex(32)  # 64-char hex string
        return self.api_key

    # ------------------------------------------------------------------ #
    # Dashboard helpers                                                    #
    # ------------------------------------------------------------------ #

    def get_active_trips(self):
        """All active trips the user owns or has been accepted into."""
        owned = Trip.query.filter_by(owner_id=self.id, status='ACTIVE').all()
        joined = (
            Trip.query
            .join(TripMember, TripMember.trip_id == Trip.id)
            .filter(
                TripMember.user_id == self.id,
                TripMember.status == 'accepted',
                Trip.status == 'ACTIVE',
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
        """Net amount owed across all trips (positive = others owe you)."""
        total = 0.0
        all_trip_ids = self._all_trip_ids()
        if not all_trip_ids:
            return 0.0
        trips = Trip.query.filter(Trip.id.in_(all_trip_ids)).all()
        for trip in trips:
            total += trip.balance_for(self.id)
        return round(total, 2)

    def _all_trip_ids(self):
        owned = [t.id for t in Trip.query.filter_by(owner_id=self.id).all()]
        joined = [m.trip_id for m in
                  TripMember.query.filter_by(user_id=self.id, status='accepted').all()]
        return list(set(owned + joined))


# ---------------------------------------------------------------------------
# Trip
# ---------------------------------------------------------------------------

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
    status      = db.Column(db.String(20), default='OPEN')
    # ── New fields ──────────────────────────────────────────────────────────
    join_deadline           = db.Column(db.DateTime, nullable=True)
    open_roster             = db.Column(db.Boolean, default=False, nullable=False,
                                        server_default='0')
    # ── Legacy fields (kept for backward compat / migration) ────────────────
    confirmation_deadline   = db.Column(db.DateTime, nullable=True)
    confirmation_started_at = db.Column(db.DateTime, nullable=True)
    cancelled_at            = db.Column(db.DateTime, nullable=True)
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
    # Status helpers                                                       #
    # ------------------------------------------------------------------ #

    @property
    def computed_status(self):
        """Returns 'upcoming', 'ongoing', or 'completed' based on today's date."""
        today = _date.today()
        if today < self.start_date:
            return 'upcoming'
        elif today <= self.end_date:
            return 'ongoing'
        else:
            return 'completed'

    @property
    def joining_closed(self):
        """Joining is closed when:
        - Trip is not OPEN, OR
        - join_deadline is set and has passed, OR
        - 1 day before start_date (legacy fallback when no join_deadline set)
        """
        if self.status and self.status.upper() != 'OPEN':
            return True
        now_naive = datetime.utcnow()
        if self.join_deadline is not None:
            dl = self.join_deadline
            if dl.tzinfo is not None:
                dl = dl.replace(tzinfo=None)
            return now_naive >= dl
        # Legacy fallback: close 1 day before start
        return _date.today() >= (self.start_date - timedelta(days=1))

    @property
    def join_deadline_passed(self) -> bool:
        """True if the join_deadline datetime has passed (regardless of status)."""
        if self.join_deadline is None:
            return False
        now_naive = datetime.utcnow()
        dl = self.join_deadline
        if dl.tzinfo is not None:
            dl = dl.replace(tzinfo=None)
        return now_naive >= dl

    @property
    def main_confirmation_deadline(self):
        """Legacy: kept for backward compat. Uses join_deadline if set."""
        if self.join_deadline:
            return self.join_deadline.date()
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

    # ------------------------------------------------------------------ #
    # Member helpers                                                       #
    # ------------------------------------------------------------------ #

    def member_count(self):
        return self.members.filter_by(status='accepted').count() + 1  # +1 for owner

    @property
    def has_accepted_members(self) -> bool:
        """True once at least one non-owner member has been accepted.
        Used as the single source-of-truth for the trip-lock check:
        once this is True, core trip fields (destination, dates, budget,
        departure_city) become immutable."""
        return self.members.filter_by(status='accepted').count() > 0

    def accepted_members(self):
        return TripMember.query.filter_by(trip_id=self.id, status='accepted').all()

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

    def all_member_users(self):
        """Owner + accepted members, as User objects."""
        users = [self.owner]
        for m in self.accepted_members():
            users.append(m.user)
        return users

    # ------------------------------------------------------------------ #
    # Action guards                                                        #
    # ------------------------------------------------------------------ #

    def can_join(self):
        return self.is_open() and not self.joining_closed and not self.is_full()

    def can_leave(self):
        """Members can leave while trip is OPEN and joining has not closed.
        Joining closes when join_deadline passes (if set) or 1 day before start (legacy).
        """
        return self.is_open() and not self.joining_closed

    def can_cancel(self):
        today = _date.today()
        return self.status and self.status.upper() != 'CANCELLED' and today < self.start_date

    def can_owner_confirm(self):
        """Owner can confirm the trip when it is AWAITING_CONFIRMATION."""
        return self.is_awaiting_confirmation()

    def can_add_expense(self):
        return self.status and self.status.upper() in ('CONFIRMED', 'ACTIVE')

    # ------------------------------------------------------------------ #
    # State transitions                                                    #
    # ------------------------------------------------------------------ #

    def cancel(self):
        self.status = 'CANCELLED'
        self.cancelled_at = datetime.now(timezone.utc)

    def owner_confirm_trip(self):
        """Owner explicitly confirms the trip → CONFIRMED."""
        if not self.is_awaiting_confirmation():
            return False
        self.status = 'CONFIRMED'
        if not self.confirmation_started_at:
            self.confirmation_started_at = datetime.now(timezone.utc)
        return True

    def maybe_transition_to_awaiting(self):
        """
        If join_deadline has passed and trip is still OPEN, move to AWAITING_CONFIRMATION.
        Returns True if a transition occurred.
        """
        if not self.is_open():
            return False
        if self.join_deadline_passed:
            self.status = 'AWAITING_CONFIRMATION'
            if not self.confirmation_started_at:
                self.confirmation_started_at = datetime.now(timezone.utc)
            return True
        return False

    def refresh_status(self):
        """Auto-advance OPEN/AWAITING_CONFIRMATION/CONFIRMED → ACTIVE → COMPLETED by date."""
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

    # ── Legacy: kept so existing routes that call these don't break ─────────

    def start_confirmation(self):
        if self.status and self.status.upper() == 'AWAITING_CONFIRMATION':
            return
        self.status = 'AWAITING_CONFIRMATION'
        self.confirmation_started_at = datetime.now(timezone.utc)

    def finalize_confirmed_members(self):
        for member in self.accepted_members():
            if not member.is_confirmed:
                member.status = 'declined'
        self.status = 'CONFIRMED'
        if not self.confirmation_started_at:
            self.confirmation_started_at = datetime.now(timezone.utc)

    def confirm_member(self, member):
        """Legacy: individual member confirmation (kept for backward compat)."""
        if member.trip_id != self.id:
            return False
        member.is_confirmed = True
        member.confirmed_at = datetime.now(timezone.utc)
        if self.all_members_confirmed():
            self.status = 'CONFIRMED'
        return True

    def maybe_start_confirmation_if_needed(self):
        """Legacy stub — now delegates to maybe_transition_to_awaiting."""
        return self.maybe_transition_to_awaiting()

    def confirmation_window_open(self):
        if not self.confirmation_window_deadline:
            return False
        return (self.confirmation_started_at is not None and
                _date.today() < self.confirmation_window_deadline.date())

    def confirmation_window_expired(self):
        if not self.confirmation_started_at:
            return False
        deadline = self.confirmation_window_deadline
        if deadline is None:
            return False
        now_naive = datetime.utcnow()
        if deadline.tzinfo is not None:
            deadline = deadline.replace(tzinfo=None)
        return now_naive >= deadline

    def reopen_missing_slots(self):
        if self.status and self.status.upper() != 'AWAITING_CONFIRMATION':
            return
        self.status = 'OPEN'
        self.confirmation_started_at = None
        for member in self.accepted_members():
            if not member.is_confirmed:
                member.status = 'declined'

    def pending_request_for(self, user_id):
        return TripMember.query.filter_by(trip_id=self.id, user_id=user_id).first()

    # ------------------------------------------------------------------ #
    # Contact visibility                                                   #
    # ------------------------------------------------------------------ #

    def contact_visible_for(self, viewer_id: int, target_user_id: int) -> bool:
        """
        Determine whether viewer_id can see phone/email of target_user_id
        in the context of this trip.

        Rules:
        - CANCELLED trip → never show contacts
        - Viewer sees their own contacts always
        - Before CONFIRMED (OPEN / AWAITING_CONFIRMATION) → no contacts shown
        - After CONFIRMED / ACTIVE / COMPLETED:
          - Owner sees all confirmed members
          - Any member sees the owner's contacts
          - Members see each other only if open_roster=True
        - Removed/left members lose access (checked via is_active_member below)
        """
        if self.is_cancelled():
            return False

        # Always show your own data to yourself
        if viewer_id == target_user_id:
            return True

        # Only after confirmation do contacts become visible
        if self.status.upper() not in ('CONFIRMED', 'ACTIVE', 'COMPLETED'):
            return False

        # Viewer must be an active participant (owner or accepted member)
        if not self._is_active_participant(viewer_id):
            return False

        # Target must also be an active participant
        if not self._is_active_participant(target_user_id):
            return False

        is_viewer_owner = (viewer_id == self.owner_id)
        is_target_owner = (target_user_id == self.owner_id)

        if is_viewer_owner:
            # Owner sees everyone's contacts
            return True

        if is_target_owner:
            # All members see owner's contacts
            return True

        # Member ↔ Member: only if open_roster enabled
        return bool(self.open_roster)

    def _is_active_participant(self, user_id: int) -> bool:
        """True if user_id is the owner OR an accepted (non-removed) member."""
        if user_id == self.owner_id:
            return True
        m = TripMember.query.filter_by(
            trip_id=self.id, user_id=user_id, status='accepted'
        ).first()
        return m is not None

    # ------------------------------------------------------------------ #
    # Finance                                                              #
    # ------------------------------------------------------------------ #

    def total_spent(self):
        return round(sum(e.amount for e in self.expenses), 2)

    def your_share(self, user_id):
        mc = self.member_count()
        return round(self.total_spent() / mc, 2) if mc else 0.0

    def balance_for(self, user_id):
        paid = sum(e.amount for e in self.expenses.filter_by(paid_by_id=user_id))
        share = self.your_share(user_id)
        return round(paid - share, 2)

    def settlement_summary(self):
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
        Returns list of dicts: { 'debtor': User, 'creditor': User, 'amount': float }
        """
        members = self.all_member_users()
        mc = len(members)
        if mc == 0:
            return []

        total = sum(e.amount for e in self.expenses)
        share = total / mc

        balances = []
        for user in members:
            paid = sum(e.amount for e in self.expenses.filter_by(paid_by_id=user.id))
            balances.append([user, round(paid - share, 2)])

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


# ---------------------------------------------------------------------------
# TripMember
# ---------------------------------------------------------------------------

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
        return f'<TripMember trip={self.trip_id} user={self.user_id} status={self.status}>'


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

class Settlement(db.Model):
    __tablename__ = 'settlements'
    __table_args__ = (
        db.Index('ix_settlements_trip_payer', 'trip_id', 'payer_id'),
        db.Index('ix_settlements_trip_payee', 'trip_id', 'payee_id'),
    )

    id         = db.Column(db.Integer, primary_key=True)
    trip_id    = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    payer_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    payee_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount     = db.Column(db.Float, nullable=False)
    is_settled = db.Column(db.Boolean, default=False, nullable=False)
    settled_at = db.Column(db.DateTime, nullable=True)

    trip  = db.relationship('Trip', backref=db.backref('settlements', lazy='dynamic',
                                                        cascade='all, delete-orphan'))
    payer = db.relationship('User', foreign_keys=[payer_id])
    payee = db.relationship('User', foreign_keys=[payee_id])

    def __repr__(self):
        return f'<Settlement trip={self.trip_id} {self.payer_id}→{self.payee_id} ₹{self.amount}>'


# ---------------------------------------------------------------------------
# Expense
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ContactAccessLog
# ---------------------------------------------------------------------------

class ContactAccessLog(db.Model):
    """Audit log: every time a user's contact details are revealed to another user."""
    __tablename__ = 'contact_access_logs'
    __table_args__ = (
        db.Index('ix_cal_viewer_trip', 'viewer_id', 'trip_id'),
        db.Index('ix_cal_target_trip', 'target_user_id', 'trip_id'),
    )

    id             = db.Column(db.Integer, primary_key=True)
    viewer_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                               nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                               nullable=False)
    trip_id        = db.Column(db.Integer, db.ForeignKey('trips.id', ondelete='CASCADE'),
                               nullable=False)
    viewed_at      = db.Column(db.DateTime,
                               default=lambda: datetime.now(timezone.utc))

    viewer      = db.relationship('User', foreign_keys=[viewer_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])
    trip        = db.relationship('Trip')

    def __repr__(self):
        return (f'<ContactAccessLog viewer={self.viewer_id} '
                f'target={self.target_user_id} trip={self.trip_id}>')
