"""REST API package for MERON.

This package is the standalone HTTP surface that the mobile app (and
ChatGPT's GPT Action / MCP server) talks to. It has no Dash dependency,
so it can be deployed without pulling in dash/plotly/dash-bootstrap.

Public entry points:

- ``strava_analytics.api.app.create_app()`` → a standalone Flask app.
- ``strava_analytics.api.register.register_api(flask_app)`` → mounts every
  ``/api/*`` route (plus ``/oauth/strava/*``) onto an existing Flask server.
  Used by the Dash combined server so one process can serve both.
"""

from .register import register_api, register_oauth

__all__ = ["register_api", "register_oauth"]
