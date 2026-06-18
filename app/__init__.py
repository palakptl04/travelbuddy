from flask import Flask
from config import Config
from app.extensions import db, bcrypt, login_manager, csrf, migrate


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

    from datetime import datetime, timezone

    @app.template_global()
    def now():
        return datetime.now(timezone.utc)

    return app
