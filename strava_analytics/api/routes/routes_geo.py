"""Route polyline endpoints for native map rendering.

Returns raw coordinate arrays + per-second streams (pace, HR, elevation)
that the mobile app can render with MapKit / Google Maps / MapLibre.
Does NOT return the Dash-rendered Leaflet map HTML.
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, jsonify

from strava_analytics.web import data

from ..errors import NotFound


bp = Blueprint("api_routes_geo", __name__, url_prefix="/api")


@bp.route("/route-index")
def route_index():
    """Return every cached route fingerprint at once.

    Shape: ``{filename: [[lat, lon], ...]}``. Useful for heatmap rendering
    and for the route picker in the mobile app.
    """
    export_dir = data.get_export_dir()
    index_path: Path = export_dir / "route_index.json"
    if not index_path.exists():
        return jsonify({"routes": {}})

    try:
        raw = json.loads(index_path.read_text())
    except Exception:
        raise NotFound("route_index.json is malformed or missing")

    fps = raw.get("fingerprints", {})
    return jsonify({
        "routes": {
            fn: [[round(p[0], 5), round(p[1], 5)] for p in fp.get("points", [])]
            for fn, fp in fps.items()
            if len(fp.get("points", [])) >= 3
        },
    })


@bp.route("/routes/<path:filename>")
def route_detail(filename: str):
    """Return the polyline + available streams for a single activity.

    The mobile app uses this to draw a route on its native map view and
    plot pace / HR / elevation under it. Streams are extracted lazily
    from the FIT file if present.
    """
    fps_path = data.get_export_dir() / "route_index.json"
    if not fps_path.exists():
        raise NotFound("route index not available")

    try:
        raw = json.loads(fps_path.read_text())
    except Exception:
        raise NotFound("route index is malformed")

    fp = raw.get("fingerprints", {}).get(filename)
    if not fp or not fp.get("points"):
        raise NotFound(f"no route for {filename}")

    polyline = [[round(p[0], 5), round(p[1], 5)] for p in fp["points"]]

    # Streams are optional — only extract if the FIT file exists.
    streams: dict = {}
    fit_path = data.get_export_dir() / filename
    if fit_path.exists() and fit_path.suffix.lower() in (".fit", ".fit.gz"):
        streams = _extract_streams(fit_path)

    return jsonify({
        "filename": filename,
        "polyline": polyline,
        "streams": streams,
    })


def _extract_streams(fit_path: Path) -> dict:
    """Pull pace / HR / elevation per-second from a FIT file."""
    try:
        from fitparse import FitFile
    except ImportError:
        return {}
    try:
        fit = FitFile(str(fit_path))
        timestamps: list[str] = []
        hr: list[float | None] = []
        alt: list[float | None] = []
        speed: list[float | None] = []
        for record in fit.get_messages("record"):
            values = {d.name: d.value for d in record}
            t = values.get("timestamp")
            if t is not None:
                timestamps.append(t.isoformat())
                hr.append(values.get("heart_rate"))
                alt.append(values.get("altitude"))
                speed.append(values.get("enhanced_speed") or values.get("speed"))
        return {
            "timestamps": timestamps,
            "heart_rate": hr,
            "altitude_m": alt,
            "speed_m_per_s": speed,
        }
    except Exception:
        return {}
