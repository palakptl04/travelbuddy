from flask import Blueprint

api_v1 = Blueprint('api_v1', __name__)

from app.api import routes  # noqa: F401, E402
