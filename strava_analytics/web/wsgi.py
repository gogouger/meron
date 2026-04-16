"""WSGI entry point — used by gunicorn / any production WSGI server.

Importing this module has the side effect of initialising the MERON data
layer (DB migrations, enrichment cache warm-up, heatmap precompute).
That means the first HTTP request is fast; the cost is paid at boot.

Gunicorn invocation::

    gunicorn -b 0.0.0.0:8050 -w 1 --threads 4 strava_analytics.web.wsgi:app

Single worker + threads is the right shape: the enrichment cache lives in
process memory, so every worker would duplicate it. Threads share the
cache and let multiple concurrent requests hit the cached DataFrame.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    for _p in (Path.cwd() / ".env", Path.home() / ".meron" / ".env"):
        if _p.exists():
            load_dotenv(_p, override=False)
except ImportError:
    pass

logging.basicConfig(
    level=os.environ.get("MERON_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

from strava_analytics.web import data
from strava_analytics.web.app import create_app

# Bootstrap once, at import time. Gunicorn imports the module before
# forking workers (or in the single-worker mode we use), so this runs
# exactly once per process.
_export_dir = os.environ.get("MERON_IMPORT_FROM") or None
data.init(_export_dir)

app = create_app().server  # Flask instance underneath the Dash app
