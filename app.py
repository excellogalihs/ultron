"""ultron — local-first AI workspace."""

import os

from ultron import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("ULTRON_HOST", "127.0.0.1"),
        port=int(os.environ.get("ULTRON_PORT", "5000")),
        debug=os.environ.get("ULTRON_DEBUG") == "1",
        threaded=True,
    )
