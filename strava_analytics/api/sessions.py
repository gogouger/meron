"""Login session helpers.

Web clients use Flask's signed-cookie session (``SECRET_KEY`` required,
already configured for the OAuth CSRF state). The session carries only
``user_id``; everything else is a fresh DB lookup so stale profile info
can't leak through a cookie.

Mobile / API clients don't use sessions — they authenticate via
``X-API-Key`` (per-user key stored in ``sync_state``).
"""

from __future__ import annotations

from flask import session


SESSION_USER_KEY = "user_id"


def login_session(user_id: int) -> None:
    """Bind a Flask session cookie to ``user_id``."""
    session.clear()
    session[SESSION_USER_KEY] = int(user_id)
    session.permanent = True


def logout_session() -> None:
    """Drop the session entirely."""
    session.clear()


def session_user_id() -> int | None:
    """Return the session's ``user_id`` if logged in, else ``None``."""
    uid = session.get(SESSION_USER_KEY)
    return int(uid) if uid is not None else None
