from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DateField, FloatField, IntegerField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError
from app.cities import CITY_CHOICES


class TripForm(FlaskForm):
    title = StringField('Trip Title', validators=[
        DataRequired(message='Title is required.'),
        Length(min=3, max=150, message='Title must be between 3 and 150 characters.')
    ])
    departure_city = SelectField('Departure City', choices=CITY_CHOICES, validators=[
        DataRequired(message='Departure city is required.')
    ])
    destination = SelectField('Destination', choices=CITY_CHOICES, validators=[
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
    submit = SubmitField('Save Trip')

    def validate_destination(self, field):
        if self.departure_city.data and field.data == self.departure_city.data:
            raise ValidationError('Destination must differ from departure city.')

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError('End date must be on or after the start date.')

    def validate_budget_max(self, field):
        if self.budget_min.data is not None and field.data is not None \
                and field.data < self.budget_min.data:
            raise ValidationError('Max budget must be greater than or equal to min budget.')
