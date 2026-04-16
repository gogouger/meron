"""OpenAPI spec + health endpoints.

Both ``/api/openapi.yaml`` and ``/api/openapi.json`` are served so codegen
tools can pick whichever they prefer. ``/api/healthz`` is a simple
liveness probe the mobile client can call on launch without auth.
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, Response, send_file


bp = Blueprint("api_openapi", __name__, url_prefix="/api")


_SPEC_YAML = Path(__file__).resolve().parents[2] / "web" / "openapi.yaml"


@bp.route("/healthz")
def healthz():
    return {"ok": True}


@bp.route("/openapi.yaml")
def openapi_yaml():
    return send_file(str(_SPEC_YAML), mimetype="text/yaml")


@bp.route("/openapi.json")
def openapi_json():
    """Serve the YAML spec as JSON for tools that prefer JSON."""
    try:
        import yaml  # PyYAML is pulled in transitively (via dash); guard anyway
        data = yaml.safe_load(_SPEC_YAML.read_text())
        return Response(json.dumps(data, indent=2), mimetype="application/json")
    except Exception:
        # Fall back to raw YAML under a JSON MIME if PyYAML isn't available.
        return Response(_SPEC_YAML.read_text(), mimetype="text/yaml")
