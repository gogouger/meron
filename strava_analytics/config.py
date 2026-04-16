"""Central configuration for timezone, paths, and defaults.

Everything that used to be hard-coded (like ``US/Mountain``) lives here.
Per-user fields (e.g. a User row's ``timezone`` column) take precedence over
the env default when a user context is known.
"""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo


_DEFAULT_TZ_NAME = "US/Mountain"


def default_tz_name() -> str:
    """The timezone to use when no user override exists.

    Reads ``MERON_TZ`` from the environment; falls back to ``US/Mountain``
    for backwards compatibility with the original hard-coded value.
    """
    return os.environ.get("MERON_TZ", _DEFAULT_TZ_NAME)


def default_tz() -> ZoneInfo:
    return ZoneInfo(default_tz_name())


def get_user_tz(user_tz_name: str | None = None) -> ZoneInfo:
    """Resolve a user's timezone, falling back to the env default.

    Pass the User.timezone column value when available.
    """
    if user_tz_name:
        try:
            return ZoneInfo(user_tz_name)
        except Exception:
            pass
    return default_tz()
