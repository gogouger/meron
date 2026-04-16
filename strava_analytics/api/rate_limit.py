"""Rate limiting for the API.

Uses ``flask-limiter`` when available. Gracefully degrades to a no-op if
the package isn't installed (e.g. slim runtime environments), so CI and
tests don't need to pull in yet another dep.

Default quotas:

- Global per API key: 60 req/min
- Sync endpoints:     5 req/min  (they do real work)
"""

from __future__ import annotations

import logging

from flask import Flask, request


logger = logging.getLogger(__name__)


def _key_func():
    """Rate-limit key: the API key if present, otherwise the remote address."""
    return request.headers.get("X-API-Key") or request.remote_addr or "anonymous"


def install_rate_limiter(app: Flask) -> None:
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address  # noqa: F401
    except ImportError:
        logger.info("flask-limiter not installed; rate limiting disabled")
        app.extensions.setdefault("meron_rate_limiter", None)
        return

    limiter = Limiter(
        key_func=_key_func,
        default_limits=["60/minute"],
        storage_uri="memory://",
    )
    limiter.init_app(app)
    app.extensions["meron_rate_limiter"] = limiter

    # Tighten the sync endpoints specifically — they do actual Strava
    # network work and should not be hammered.
    for endpoint in (
        "api_sync.sync_strava",
        "api_sync.sync_upload",
    ):
        try:
            limiter.limit("5/minute", per_method=True)(
                app.view_functions[endpoint]
            )
        except KeyError:
            # Endpoint might not be registered yet in test fixtures.
            continue
