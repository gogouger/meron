"""Standalone Flask application for the REST API.

Usage:

    strava-api --port 8051

Runs the API + OAuth routes without any Dash imports, so mobile-focused
deployments don't have to ship dash/plotly/dbc. Shares the exact same
``register_api`` registration used by the Dash combined server.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from flask import Flask

from . import register_api, register_oauth


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for path in (Path.cwd() / ".env", Path.home() / ".meron" / ".env"):
        if path.exists():
            load_dotenv(path, override=False)


def _apply_cors(app: Flask) -> None:
    """Configure CORS if ``flask-cors`` is available.

    ``MERON_ALLOWED_ORIGINS`` is a comma-separated list. When unset, no
    CORS headers are emitted (correct default for a first-party native app
    making non-browser HTTP requests).
    """
    origins = os.environ.get("MERON_ALLOWED_ORIGINS", "").strip()
    if not origins:
        return
    try:
        from flask_cors import CORS
    except ImportError:
        logging.getLogger(__name__).warning(
            "flask-cors not installed; MERON_ALLOWED_ORIGINS ignored"
        )
        return
    CORS(app, resources={r"/api/*": {"origins": [
        o.strip() for o in origins.split(",") if o.strip()
    ]}})


def create_app() -> Flask:
    """Build a Flask application that serves every /api/* and /oauth/* route."""
    _load_dotenv()

    app = Flask(__name__)
    if not app.secret_key:
        import secrets as _s
        app.secret_key = os.environ.get("MERON_SECRET_KEY") or _s.token_urlsafe(32)

    _apply_cors(app)
    register_oauth(app)
    register_api(app)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="MERON REST API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8051)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "export_dir", nargs="?", default=None,
        help="Optional path to a Strava export dir for bootstrapping. "
             "Omit when the DB at $MERON_DB_PATH already contains data.",
    )
    args = parser.parse_args()

    # Initialise DB + load athlete config + sidecar artifacts. Imported
    # here so `strava_analytics.api.app` itself stays Dash-free until main()
    # runs (so `from strava_analytics.api import ...` is cheap).
    from strava_analytics.web import data
    data.init(args.export_dir)

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
