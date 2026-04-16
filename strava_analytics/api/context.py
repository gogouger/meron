"""Per-request user context.

Resolution order (first match wins):

  1. Flask session cookie      (web browser login)
  2. X-API-Key header           (mobile + ChatGPT + MCP)
  3. Demo fallback              (anonymous visitor → DEMO_USER_ID)

Outside a Flask request context (CLI, background jobs, tests), this
always returns ``DEMO_USER_ID``.

``require_user_id()`` is the strict variant — raises ``Unauthorized``
when the caller isn't actually authenticated (session + key both
missing). Use it on write endpoints and settings callbacks.
"""

from __future__ import annotations

from typing import Optional

from flask import has_request_context, request

from .errors import Unauthorized


# User 1 is the site admin today; their data is shown to anonymous
# visitors as a sample dashboard.
DEMO_USER_ID = 1


def _user_id_from_api_key() -> Optional[int]:
    """Look up ``request['X-API-Key']`` across every user's sync_state row."""
    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        return None
    from strava_analytics.db import session_scope
    from strava_analytics.db.models import SyncState
    with session_scope() as session:
        row = session.query(SyncState).filter(
            (SyncState.api_key_read == api_key)
            | (SyncState.api_key_write == api_key)
        ).first()
        return row.user_id if row else None


def _resolve() -> tuple[int, bool]:
    """Return ``(user_id, is_authenticated)`` for the current request."""
    if not has_request_context():
        return DEMO_USER_ID, False

    from .sessions import session_user_id
    uid = session_user_id()
    if uid is not None:
        return uid, True

    uid = _user_id_from_api_key()
    if uid is not None:
        return uid, True

    return DEMO_USER_ID, False


def current_user_id() -> int:
    """The user id whose data should be served for this request.

    Falls back to ``DEMO_USER_ID`` for anonymous visitors so read-only
    pages can still render a demo dashboard.
    """
    return _resolve()[0]


def is_authenticated() -> bool:
    """True when the request is backed by a session or a valid API key."""
    return _resolve()[1]


def require_user_id() -> int:
    """Return the authenticated user id, or raise ``Unauthorized``.

    Use on write endpoints, settings callbacks, and anything else that
    must not silently target the demo user.
    """
    uid, authed = _resolve()
    if not authed:
        raise Unauthorized("login required")
    return uid


def current_is_admin() -> bool:
    """True if the authenticated user has ``is_admin`` set."""
    if not is_authenticated():
        return False
    from strava_analytics.db import session_scope
    from strava_analytics.db.models import User
    with session_scope() as session:
        user = session.get(User, current_user_id())
        return bool(user and user.is_admin)
