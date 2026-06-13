from flask import render_template
from flask_login import login_required
from app.main import main


@main.route('/')
def home():
    return render_template('main/home.html')
