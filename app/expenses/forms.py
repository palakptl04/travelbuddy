from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange

EXPENSE_CATEGORIES = [
    ('food',          'Food'),
    ('transport',     'Transport'),
    ('accommodation', 'Accommodation'),
    ('activities',    'Activities'),
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
    category = SelectField('Category', choices=EXPENSE_CATEGORIES, validators=[DataRequired()])
    paid_by_id = SelectField('Paid By', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Add Expense')
