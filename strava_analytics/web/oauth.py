"""Backwards-compatible re-export of the OAuth registration function.

The real implementation lives under ``strava_analytics.api.oauth``.
"""

from strava_analytics.api.oauth import register_oauth

__all__ = ["register_oauth"]
