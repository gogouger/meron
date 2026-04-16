"""Backwards-compatible re-export of the API registration function.

The real implementation lives under ``strava_analytics.api``. This shim
keeps imports like ``from strava_analytics.web.api import register_api``
working while callers migrate.
"""

from strava_analytics.api import register_api

__all__ = ["register_api"]
