"""Per-request user context.

MERON is single-user today. Every call site that used to hard-code
``user_id=1`` now calls :func:`current_user_id` instead. When we add
multi-user support later, this is the only function that changes — it
will read from a JWT or session cookie rather than returning a constant.
"""

from __future__ import annotations


# The canonical single-user id. The DB migration that seeds the users
# table also uses 1; keeping the literal here lets us grep and find the
# one remaining source of truth.
_SINGLE_USER_ID = 1


def current_user_id() -> int:
    """Return the id of the user making the current request.

    Today this is always ``1``. When multi-user lands, this function will
    inspect the current Flask ``request`` (JWT / session cookie) and raise
    ``werkzeug.exceptions.Unauthorized`` when no user is bound.
    """
    return _SINGLE_USER_ID
