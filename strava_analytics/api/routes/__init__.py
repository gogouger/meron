"""Route registration for the API.

:func:`register_routes` attaches every ``/api/*`` blueprint to a Flask app.
The same function is used by the standalone API factory and the Dash
combined server, so they share one definitive set of endpoints.
"""

from __future__ import annotations

from flask import Flask

from .activities import bp as activities_bp
from .auth import bp as auth_bp
from .metrics import bp as metrics_bp
from .openapi import bp as openapi_bp
from .plan import bp as plan_bp
from .routes_geo import bp as routes_bp
from .sync import bp as sync_bp
from .user import bp as user_bp


def register_routes(server: Flask) -> None:
    """Mount every API blueprint on the Flask server."""
    for bp in (
        metrics_bp,
        activities_bp,
        sync_bp,
        plan_bp,
        user_bp,
        routes_bp,
        auth_bp,
        openapi_bp,
    ):
        server.register_blueprint(bp)
