from flask import Flask, request
from config import Config
from app.extensions import db, bcrypt, login_manager, csrf, migrate, swagger


def create_app(config_object=None):
    app = Flask(__name__)

    if config_object is None:
        app.config.from_object(Config)
    else:
        app.config.from_object(config_object)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    # Flasgger — must be initialised after app.config is populated
    swagger.init_app(app)


    from app.auth import auth as auth_bp
    from app.main import main as main_bp
    from app.dashboard import dashboard as dashboard_bp
    from app.profile import profile as profile_bp
    from app.trips import trips as trips_bp
    from app.expenses import expenses as expenses_bp
    from app.api import api_v1 as api_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(api_bp, url_prefix='/api/v1')

    # Exempt the API blueprint from CSRF (stateless JWT/API-key auth)
    csrf.exempt(api_bp)

    from datetime import datetime, timezone

    @app.template_global()
    def now():
        return datetime.now(timezone.utc)

    # -----------------------------------------------------------------------
    # bfcache / logout fix
    # Inject Cache-Control: no-store on all web (non-API, non-static) responses
    # so the browser never serves a stale cached page after logout.
    # @login_required already issues a 302 redirect on un-authenticated access,
    # so even if bfcache restores a page, the browser re-validates and the
    # server redirects to login.
    # -----------------------------------------------------------------------
    @app.after_request
    def set_no_cache_headers(response):
        path = request.path
        # Skip static assets and the API (API has its own cache semantics)
        if path.startswith('/static/') or path.startswith('/api/'):
            return response
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response


    return app
