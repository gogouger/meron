"""Shared registration helpers used by both the Dash combined server and the
standalone API app.

Exposes :func:`register_api` and :func:`register_oauth`, which are the only
symbols external code (like ``web/app.py``) needs to import.
"""

from __future__ import annotations

from flask import Flask

from .auth import install_api_key_gate
from .errors import register_error_handlers
from .middleware import install_request_id
from .oauth import register_oauth
from .rate_limit import install_rate_limiter
from .routes import register_routes


def register_api(server: Flask) -> None:
    """Attach every ``/api/*`` route + middleware to an existing Flask server.

    Order matters:
      1. Request-ID stamp  (so logs include it from the first line)
      2. API key gate      (so unauthorised requests short-circuit early)
      3. Rate limiter      (applied to /api/* only)
      4. Routes            (the actual endpoints)
      5. Error handlers    (catch-all envelope)
    """
    install_request_id(server)
    install_api_key_gate(server)
    install_rate_limiter(server)
    register_routes(server)
    register_error_handlers(server)


__all__ = ["register_api", "register_oauth"]
