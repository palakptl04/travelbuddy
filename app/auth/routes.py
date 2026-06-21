from flask import flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from app.auth import auth
from app.auth.forms import LoginForm, RegisterForm
from app.extensions import bcrypt, db
from app.models import User


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegisterForm()
    if form.validate_on_submit():
        hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(
            name=form.name.data.strip(),
            email=form.email.data.lower().strip(),
            password_hash=hashed_pw
        )
        db.session.add(user)
        db.session.commit()
        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(next_page or url_for('dashboard.index'))
        flash('Invalid email or password.', 'error')

    return render_template('auth/login.html', form=form)


@auth.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    # Redirect to home and ensure the redirect response itself is not cached.
    # This prevents bfcache from replaying the session-authenticated state
    # when the user presses the browser Back button after logging out.
    resp = make_response(redirect(url_for('main.home')))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp
