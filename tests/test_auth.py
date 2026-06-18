"""Tests for auth routes: register, login, logout."""

import pytest
from app.models import User
from app.extensions import bcrypt


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_get_returns_form(self, client):
        resp = client.get('/auth/register')
        assert resp.status_code == 200
        assert b'Register' in resp.data or b'register' in resp.data.lower()

    def test_register_success_creates_user(self, client, app):
        resp = client.post('/auth/register', data={
            'name': 'Alice',
            'email': 'alice@example.com',
            'password': 'Secure123!',
            'confirm_password': 'Secure123!',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            user = User.query.filter_by(email='alice@example.com').first()
        assert user is not None
        assert user.name == 'Alice'

    def test_register_hashes_password(self, client, app):
        client.post('/auth/register', data={
            'name': 'Bob',
            'email': 'bob@example.com',
            'password': 'Secure123!',
            'confirm_password': 'Secure123!',
        })
        with app.app_context():
            user = User.query.filter_by(email='bob@example.com').first()
        assert user is not None
        assert user.password_hash != 'Secure123!'
        assert bcrypt.check_password_hash(user.password_hash, 'Secure123!')

    def test_register_duplicate_email_rejected(self, client, app):
        data = {
            'name': 'Carol',
            'email': 'carol@example.com',
            'password': 'Secure123!',
            'confirm_password': 'Secure123!',
        }
        client.post('/auth/register', data=data)
        resp = client.post('/auth/register', data=data, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            users = User.query.filter_by(email='carol@example.com').all()
        assert len(users) == 1  # Only one record created

    def test_register_redirects_to_login(self, client):
        resp = client.post('/auth/register', data={
            'name': 'Dave',
            'email': 'dave@example.com',
            'password': 'Secure123!',
            'confirm_password': 'Secure123!',
        })
        # Should redirect (302) to login
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers.get('Location', '')


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_get_returns_form(self, client):
        resp = client.get('/auth/login')
        assert resp.status_code == 200

    def test_login_success_redirects_to_dashboard(self, client):
        # Register first
        client.post('/auth/register', data={
            'name': 'Eve',
            'email': 'eve@example.com',
            'password': 'Secure123!',
            'confirm_password': 'Secure123!',
        })
        resp = client.post('/auth/login', data={
            'email': 'eve@example.com',
            'password': 'Secure123!',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/dashboard' in resp.headers.get('Location', '')

    def test_login_wrong_password_shows_error(self, client):
        client.post('/auth/register', data={
            'name': 'Frank',
            'email': 'frank@example.com',
            'password': 'Correct123!',
            'confirm_password': 'Correct123!',
        })
        resp = client.post('/auth/login', data={
            'email': 'frank@example.com',
            'password': 'WrongPass!',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invalid' in resp.data or b'invalid' in resp.data.lower()

    def test_login_unknown_email_shows_error(self, client):
        resp = client.post('/auth/login', data={
            'email': 'nobody@example.com',
            'password': 'AnyPass123!',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invalid' in resp.data or b'invalid' in resp.data.lower()


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_redirects_to_home(self, auth_client):
        client, _ = auth_client
        resp = client.get('/auth/logout', follow_redirects=False)
        assert resp.status_code == 302

    def test_logout_clears_session(self, auth_client):
        client, _ = auth_client
        client.get('/auth/logout', follow_redirects=True)
        # After logout, /dashboard should redirect to login
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers.get('Location', '')
