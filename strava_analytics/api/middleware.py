"""Request-lifecycle middleware.

Stamps a ``X-Request-ID`` on every request (echoed back in the response)
and logs one line per API call with ``{method, path, status, duration_ms}``.
Makes it easy to correlate mobile-side bug reports with server logs.
"""

from __future__ import annotations

import logging
import time
import uuid

from flask import Flask, Response, g, request

from .context import current_user_id


logger = logging.getLogger("strava_analytics.api")


def install_request_id(app: Flask) -> None:
    @app.before_request
    def _start_timer():
        g.start_ts = time.monotonic()
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]

    @app.after_request
    def _finish(response: Response):
        if not request.path.startswith("/api/"):
            return response
        duration_ms = int((time.monotonic() - getattr(g, "start_ts", time.monotonic())) * 1000)
        request_id = getattr(g, "request_id", "-")
        response.headers["X-Request-ID"] = request_id
        try:
            uid = current_user_id()
        except Exception:
            uid = None
        logger.info(
            "api request_id=%s method=%s path=%s status=%s user_id=%s ms=%d",
            request_id, request.method, request.path,
            response.status_code, uid, duration_ms,
        )
        return response
