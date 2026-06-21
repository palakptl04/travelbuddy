from datetime import date, timedelta

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    FloatField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from app.cities import DEPARTURE_CITY_CHOICES, DESTINATION_CHOICES


class TripForm(FlaskForm):
    title = StringField('Trip Title', validators=[
        DataRequired(message='Title is required.'),
        Length(min=3, max=150, message='Title must be between 3 and 150 characters.')
    ])
    departure_city = SelectField('Departure City', choices=DEPARTURE_CITY_CHOICES, validators=[
        DataRequired(message='Departure city is required.')
    ])
    destination = SelectField('Destination', choices=DESTINATION_CHOICES, validators=[
        DataRequired(message='Destination is required.')
    ])
    description = TextAreaField('Description', validators=[Length(max=500)])
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])
    budget_min = FloatField('Min Budget (₹)', validators=[
        DataRequired(message='Minimum budget is required.'),
        NumberRange(min=0, message='Budget must be 0 or greater.')
    ])
    budget_max = FloatField('Max Budget (₹)', validators=[
        DataRequired(message='Maximum budget is required.'),
        NumberRange(min=0, message='Budget must be 0 or greater.')
    ])
    max_members = IntegerField('Max Members', validators=[
        DataRequired(message='Max members is required.'),
        NumberRange(min=1, max=50, message='Max members must be between 1 and 50.')
    ])
    # ── New fields ───────────────────────────────────────────────────────────
    join_deadline = DateField(
        'Join Deadline (optional)',
        validators=[Optional()],
        description='Last day for new members to join. Leaving is also blocked after this date.'
    )
    open_roster = BooleanField(
        'Open Roster',
        description='Allow confirmed members to see each other\'s phone and email.'
    )
    submit = SubmitField('Save Trip')

    # ── Validators ───────────────────────────────────────────────────────────

    def validate_destination(self, field):
        if self.departure_city.data and field.data == self.departure_city.data:
            raise ValidationError('Destination must differ from departure city.')

    def validate_start_date(self, field):
        if field.data and field.data < date.today() + timedelta(days=2):
            raise ValidationError('Start date must be at least 2 days from today.')

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError('End date must be on or after the start date.')

    def validate_budget_max(self, field):
        if self.budget_min.data is not None and field.data is not None \
                and field.data < self.budget_min.data:
            raise ValidationError('Max budget must be greater than or equal to min budget.')

    def validate_join_deadline(self, field):
        if field.data is None:
            return  # optional — no deadline is fine
        if field.data < date.today():
            raise ValidationError('Join deadline must be today or a future date.')
        if self.start_date.data and field.data >= self.start_date.data:
            raise ValidationError('Join deadline must be before the start date.')
