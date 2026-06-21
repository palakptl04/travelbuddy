import os

from sqlalchemy.pool import StaticPool


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///travelbuddy.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    TESTING = False

    # JWT settings
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', SECRET_KEY)
    JWT_EXPIRY_SECONDS = int(os.environ.get('JWT_EXPIRY_SECONDS', 3600))  # 1 hour default

    # Flasgger / Swagger UI settings
    SWAGGER = {
        'title': 'TravelBuddy REST API',
        'version': '1.0',
        'description': (
            'Full REST API for TravelBuddy.\n\n'
            '**Authentication** (choose one per request):\n'
            '- **Bearer JWT**: `Authorization: Bearer <token>` — obtain via `POST /api/v1/auth/token`\n'
            '- **API Key**: `X-API-Key: <key>` — generate via `POST /api/v1/me/api-key`\n'
            '- **Session cookie**: same cookie as the web UI (for browser clients)'
        ),
        'uiversion': 3,
        'openapi': '2.0',
        'termsOfService': '',
        'specs_route': '/api/docs/',
    }


class TestingConfig(Config):
    TESTING = True
    # StaticPool forces all connections to reuse the same in-memory SQLite
    # connection, so data written by one test client is visible to another.
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'check_same_thread': False},
        'poolclass': StaticPool,
    }
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key-for-testing-only'
    JWT_SECRET_KEY = 'test-jwt-secret-key-long-enough-for-hs256'
    JWT_EXPIRY_SECONDS = 3600
