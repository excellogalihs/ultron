"""Public promotional page."""

from flask import Blueprint, render_template

bp = Blueprint("marketing", __name__)


@bp.get("/about")
def index():
    return render_template("marketing.html")
