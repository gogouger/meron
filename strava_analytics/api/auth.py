"""API key gate — shared by the standalone API app and the Dash-combined server.

GET/HEAD requests accept either read or write keys; mutations require the
write key. The legacy ``athlete_config.json:api_key`` (pre-DB) is still
accepted so old ChatGPT actions don't break during the transition.
"""

from __future__ import annotations

from flask import Flask, Response, jsonify, request

from strava_analytics.db import session_scope
from strava_analytics.db.models import SyncState

from .context import current_user_id
from .errors import envelope


# Routes that should bypass the key check. ``/api/openapi.*`` is public so
# schema consumers (codegen, ChatGPT, Swagger UI) can fetch it without a
# key. ``/api/healthz`` is a liveness probe.
_PUBLIC_PATHS = frozenset({
    "/api/openapi.yaml",
    "/api/openapi.json",
    "/api/healthz",
})


def _api_keys() -> tuple[str, str]:
    """Return (read_key, write_key) for the current user."""
    with session_scope() as session:
        row = session.query(SyncState).filter(
            SyncState.user_id == current_user_id(),
            SyncState.provider == "strava",
        ).first()
        if row is None:
            return "", ""
        return row.api_key_read or "", row.api_key_write or ""


def _legacy_key() -> str:
    """The pre-DB ``athlete_config.json:api_key`` value, if any.

    Imported lazily so the auth module doesn't force a ``web.data`` import
    when running the standalone API server.
    """
    try:
        from strava_analytics.web import data
        return data.get_athlete_config().get("api_key", "") or ""
    except Exception:
        return ""


def install_api_key_gate(app: Flask) -> None:
    """Install the ``before_request`` guard on the Flask app."""

    @app.before_request
    def _check_api_key() -> Response | None:
        path = request.path
        if not path.startswith("/api/"):
            return None
        if path in _PUBLIC_PATHS:
            return None

        read_key, write_key = _api_keys()
        provided = request.headers.get("X-API-Key", "")
        legacy = _legacy_key()

        if request.method in ("GET", "HEAD", "OPTIONS"):
            allowed = {read_key, write_key, legacy} - {""}
            if allowed and provided not in allowed:
                return jsonify(envelope(
                    "unauthorized", "Valid X-API-Key header required."
                )), 401
        else:
            allowed = {write_key, legacy} - {""}
            if not allowed or provided not in allowed:
                return jsonify(envelope(
                    "unauthorized", "Write access requires X-API-Key with write scope."
                )), 401
        return None
