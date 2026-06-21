"""
API authentication utilities.

Priority order for every protected API request:
  1. Bearer JWT  (Authorization: Bearer <token>)
  2. API Key     (X-API-Key: <key>)
  3. Flask-Login session cookie  (same as web UI)

If none of these resolve to an authenticated user, abort(401) is called.

Usage
-----
    from app.api.auth_utils import require_api_auth, generate_token, api_user

    @api_v1.route('/some-route')
    def some_route():
        user = require_api_auth()
        ...
"""

from __future__ import annotations

import datetime

import jwt
from flask import abort, current_app, g, request
from flask_login import current_user

from app.extensions import db
from app.models import User

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def generate_token(user_id: int) -> str:
    """Return a signed JWT for the given user_id."""
    expiry = current_app.config.get('JWT_EXPIRY_SECONDS', 3600)
    payload = {
        'sub': user_id,
        'iat': datetime.datetime.now(datetime.timezone.utc),
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expiry),
    }
    return jwt.encode(
        payload,
        current_app.config['JWT_SECRET_KEY'],
        algorithm='HS256',
    )


def verify_token(token: str) -> int | None:
    """
    Decode a JWT and return the user_id (`sub` claim), or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=['HS256'],
        )
        return payload.get('sub')
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Main auth resolver
# ---------------------------------------------------------------------------

def require_api_auth() -> User:
    """
    Resolve the current API caller from JWT, API key, or session — in that order.

    Returns the authenticated User object.
    Calls abort(401) if no valid credential is found.

    The resolved user is also cached in ``g.api_user`` for the duration of
    the request so repeated calls are free.
    """
    # Return cached result within the same request
    if hasattr(g, 'api_user') and g.api_user is not None:
        return g.api_user

    user: User | None = None

    # 1. Bearer JWT
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        user_id = verify_token(token)
        if user_id is not None:
            user = db.session.get(User, user_id)

    # 2. API Key header
    if user is None:
        api_key = request.headers.get('X-API-Key', '').strip()
        if api_key:
            user = User.query.filter_by(api_key=api_key).first()

    # 3. Flask-Login session (web UI cookie)
    if user is None and current_user.is_authenticated:
        user = current_user._get_current_object()

    if user is None:
        abort(401)

    g.api_user = user
    return user
