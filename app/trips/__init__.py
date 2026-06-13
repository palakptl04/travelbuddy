from flask import Blueprint

trips = Blueprint('trips', __name__)

from app.trips import routes  # noqa
