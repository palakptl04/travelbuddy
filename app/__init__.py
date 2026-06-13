from flask import Flask
from config import Config
from app.extensions import db, bcrypt, login_manager, csrf


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.auth import auth as auth_bp
    from app.main import main as main_bp
    from app.dashboard import dashboard as dashboard_bp
    from app.profile import profile as profile_bp
    from app.trips import trips as trips_bp
    from app.expenses import expenses as expenses_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(expenses_bp)

    from datetime import datetime, timezone
    @app.template_global()
    def now():
        return datetime.now(timezone.utc)

    with app.app_context():
        db.create_all()

    return app
