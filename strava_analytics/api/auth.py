"""API key gate — shared by the standalone API app and the Dash server.

Keys are looked up across every user's ``sync_state`` row (multi-user),
and the owning user id is stashed on ``flask.g`` for downstream handlers
via ``current_user_id``.

For paths in ``_PROTECTED_WRITE_PATHS`` the caller must present a key
with write scope. Reads accept either read or write key. Anonymous
visitors hit public paths + read-only endpoints that fall back to the
demo user — no key required, but they never see per-user write fns.
"""

from __future__ import annotations

from flask import Flask, Response, g, jsonify, request

from strava_analytics.db import session_scope
from strava_analytics.db.models import SyncState

from .errors import envelope
from .sessions import session_user_id


# Endpoints anyone can hit without a key: OpenAPI spec, healthz, the
# pair-code claim (whole point is to obtain a key), auth endpoints, and
# static assets / OAuth flow.
_PUBLIC_PATHS = frozenset({
    "/api/openapi.yaml",
    "/api/openapi.json",
    "/api/healthz",
    "/api/auth/pair/claim",
    "/api/auth/login",
    "/api/auth/signup",
    "/api/auth/logout",
    "/api/auth/me",
})


def _legacy_key() -> str:
    """The pre-DB ``athlete_config.json:api_key`` value, if any."""
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

        # Session cookie counts as authentication — web users skip the
        # header check.
        if session_user_id() is not None:
            return None

        provided = request.headers.get("X-API-Key", "")
        if not provided:
            if request.method in ("GET", "HEAD", "OPTIONS"):
                # Anonymous reads fall through to the demo user.
                return None
            return jsonify(envelope(
                "unauthorized", "Authentication required (login or API key)."
            )), 401

        # Look up the key across all users.
        with session_scope() as session:
            row = session.query(SyncState).filter(
                (SyncState.api_key_read == provided)
                | (SyncState.api_key_write == provided)
            ).first()
            if row is None and provided != _legacy_key():
                return jsonify(envelope(
                    "unauthorized", "Unknown API key."
                )), 401
            # For mutations, require a write-scope key.
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                is_write = (row is not None and row.api_key_write == provided)
                is_legacy = (provided == _legacy_key() and _legacy_key())
                if not (is_write or is_legacy):
                    return jsonify(envelope(
                        "unauthorized",
                        "Write access requires X-API-Key with write scope."
                    )), 401
            # Stash the user for downstream use — avoids re-querying.
            g.api_key_user_id = row.user_id if row else None
        return None
