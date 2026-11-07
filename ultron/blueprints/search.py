"""Universal local workspace search."""

from flask import Blueprint, jsonify, render_template, request

from ..db import get_db
from ..services.workspace_search import SEARCH_TYPES, search_workspace

bp = Blueprint("search", __name__)


@bp.get("/search")
def index():
    query = (request.args.get("q") or "").strip()[:200]
    selected = [key for key in request.args.getlist("type") if key in SEARCH_TYPES]
    result = search_workspace(get_db(), query, selected or None, 60) if query else {"results": [], "fts": True}
    return render_template("search.html", page="search", page_title="Workspace Search",
                           query=query, selected=selected, types=SEARCH_TYPES, results=result["results"], used_fts=result["fts"])


@bp.get("/api/search")
def api_search():
    query = (request.args.get("q") or "").strip()[:200]
    if not query:
        return jsonify(results=[], fts=False)
    selected = [key for key in request.args.getlist("type") if key in SEARCH_TYPES]
    return jsonify(search_workspace(get_db(), query, selected or None, request.args.get("limit", 40, type=int)))
