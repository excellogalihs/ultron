"""ultron application factory."""

import os
import threading
import time

from flask import Flask, jsonify, render_template, request

from .constants import APP_VERSION, DEFAULT_SETTINGS
from .db import init_app as init_db_app
from .db import init_db
from .helpers import register_helpers

_scheduler_thread = None
_scheduler_guard = threading.Lock()


def _start_scheduler(app):
    global _scheduler_thread
    if app.config.get("TESTING") or (app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"):
        return
    with _scheduler_guard:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return

        def loop():
            from .blueprints.automations import run_due_jobs
            while True:
                try:
                    run_due_jobs(app)
                except Exception:
                    app.logger.exception("Automation scheduler iteration failed")
                time.sleep(20)

        _scheduler_thread = threading.Thread(target=loop, name="ultron-automation-scheduler", daemon=True)
        _scheduler_thread.start()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("ULTRON_SECRET_KEY", "ultron-local-development-key"),
        DATABASE=os.path.join(app.instance_path, "ultron.db"),
        ULTRON_WORKSPACE_ROOT=os.environ.get(
            "ULTRON_WORKSPACE_ROOT", os.path.dirname(app.root_path)
        ),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        APP_VERSION=APP_VERSION,
        DEFAULT_SETTINGS=DEFAULT_SETTINGS,
    )

    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    init_db_app(app)
    register_helpers(app)

    from .blueprints.calendar import bp as calendar_bp
    from .blueprints.automations import bp as automations_bp
    from .blueprints.chat import bp as chat_bp
    from .blueprints.documents import bp as documents_bp
    from .blueprints.evolution import bp as evolution_bp
    from .blueprints.home import bp as home_bp
    from .blueprints.knowledge import bp as knowledge_bp
    from .blueprints.memory import bp as memory_bp
    from .blueprints.marketing import bp as marketing_bp
    from .blueprints.notifications import bp as notifications_bp
    from .blueprints.search import bp as search_bp
    from .blueprints.tasks_projects import bp as tasks_projects_bp
    from .blueprints.settings import bp as settings_bp

    for blueprint in (
        home_bp,
        marketing_bp,
        notifications_bp,
        search_bp,
        chat_bp,
        documents_bp,
        knowledge_bp,
        calendar_bp,
        tasks_projects_bp,
        automations_bp,
        evolution_bp,
        memory_bp,
        settings_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found."), 404
        return render_template("404.html", page="not-found", page_title="Not found"), 404

    @app.errorhandler(500)
    def server_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Something went wrong on the local server."), 500
        return render_template("500.html", page="error", page_title="Error"), 500

    with app.app_context():
        init_db()

    _start_scheduler(app)

    return app
