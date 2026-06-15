from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SelectField, SubmitField, DateField, HiddenField
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from datetime import date

EXPENSE_CATEGORIES = [
    ('food',          'Food'),
    ('transport',     'Transport'),
    ('accommodation', 'Accommodation'),
    ('activities',    'Activities'),
    ('other',         'Other'),
]


class ExpenseForm(FlaskForm):
    title = StringField('Expense Title', validators=[
        DataRequired(message='Title is required.'),
        Length(min=2, max=150)
    ])
    amount = FloatField('Amount (₹)', validators=[
        DataRequired(message='Amount is required.'),
        NumberRange(min=0.01, message='Amount must be greater than 0.')
    ])
    category    = SelectField('Category', choices=EXPENSE_CATEGORIES, validators=[DataRequired()])
    expense_date = DateField('Date', default=date.today, validators=[Optional()])
    # paid_by_id is kept as a SelectField for server-side validation, but is
    # always forced to current_user.id in the route — it is NOT shown in the UI.
    paid_by_id  = SelectField('Paid By', coerce=int, validators=[DataRequired()])
    submit      = SubmitField('Add Expense')
