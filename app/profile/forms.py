from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp

TRAVEL_STYLES = [
    ('flexible',    'Flexible'),
    ('adventurous', 'Adventurous'),
    ('relaxed',     'Relaxed'),
    ('budget',      'Budget'),
]

INTERESTS = [
    'Mountains',
    'Beaches',
    'Heritage',
    'Food',
    'Wildlife',
    'Road Trips',
]


class ProfileForm(FlaskForm):
    name = StringField('Full Name', validators=[
        DataRequired(message='Name is required.'),
        Length(min=2, max=100, message='Name must be between 2 and 100 characters.')
    ])
    bio = TextAreaField('Bio', validators=[
        Optional(),
        Length(max=160, message='Bio must be 160 characters or fewer.')
    ])
    travel_style = SelectField('Travel Style', choices=TRAVEL_STYLES, validators=[
        DataRequired()
    ])
    phone = StringField('Contact Number (optional)', validators=[
        Optional(),
        Regexp(r'^[0-9+\-\s]{7,15}$', message='Enter a valid phone number.')
    ])
    submit = SubmitField('Save Changes')
