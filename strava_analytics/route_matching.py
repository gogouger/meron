"""GPS route matching via point-to-polyline corridor distance.

Each route is sampled to ~50 evenly-spaced (lat, lon) points.  Two routes
match when ≥ 80 % of each route's points fall within 35 m of the other
route's polyline (bidirectional check), **and** total distances are within
30 % of each other.

Fingerprints are cached to ``route_index.json`` for incremental updates.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CORRIDOR_M = 35.0          # max distance (metres) to count as "on route"
_MATCH_THRESHOLD = 0.80     # fraction of points that must be on route
_DIST_TOLERANCE = 0.70      # min ratio of shorter/longer distance
_N_SAMPLES = 50             # points per route fingerprint
_M_PER_DEG_LAT = 111_320.0  # metres per degree of latitude

# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _m_per_deg_lon(lat_deg: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat_deg))


def _to_metres(lat: float, lon: float, ref_lat: float, mpdlon: float) -> tuple[float, float]:
    """Convert (lat, lon) to local (x, y) metres relative to *ref_lat*."""
    return (lon * mpdlon, lat * _M_PER_DEG_LAT)


# ---------------------------------------------------------------------------
# Point-to-segment distance
# ---------------------------------------------------------------------------

def _pt_seg_dist_sq(px: float, py: float,
                    ax: float, ay: float, bx: float, by: float) -> float:
    """Squared distance from point P to line segment AB."""
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    dot_ab = abx * abx + aby * aby
    if dot_ab < 1e-12:
        return apx * apx + apy * apy
    t = (apx * abx + apy * aby) / dot_ab
    if t < 0:
        t = 0.0
    elif t > 1:
        t = 1.0
    cx, cy = ax + t * abx, ay + t * aby
    dx, dy = px - cx, py - cy
    return dx * dx + dy * dy


def _min_dist_to_polyline(px: float, py: float,
                          poly: list[tuple[float, float]]) -> float:
    """Minimum distance (metres) from point to polyline segments."""
    best = float("inf")
    for i in range(len(poly) - 1):
        d2 = _pt_seg_dist_sq(px, py, poly[i][0], poly[i][1],
                             poly[i + 1][0], poly[i + 1][1])
        if d2 < best:
            best = d2
    return math.sqrt(best) if best < float("inf") else float("inf")


# ---------------------------------------------------------------------------
# Route fingerprinting
# ---------------------------------------------------------------------------

def _sample_route(
    coords: list[tuple[float, float]],
    distance_m: list[float] | None = None,
    n: int = _N_SAMPLES,
) -> list[tuple[float, float]]:
    """Sample *n* evenly-spaced (lat, lon) points along a route."""
    if not coords or len(coords) < 3:
        return []

    if distance_m and len(distance_m) == len(coords):
        total = distance_m[-1]
        if total <= 0:
            return []
        step = total / n
        pts: list[tuple[float, float]] = []
        di = 0
        for s in range(n):
            target = step * (s + 0.5)
            while di < len(distance_m) - 1 and distance_m[di] < target:
                di += 1
            pts.append(coords[di])
        return pts

    step = max(1, len(coords) // n)
    return [coords[i] for i in range(0, len(coords), step)][:n]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _fraction_on_route(pts_a: list[tuple[float, float]],
                       poly_b_m: list[tuple[float, float]],
                       ref_lat: float, mpdlon: float,
                       corridor: float = _CORRIDOR_M) -> float:
    """Fraction of A's points that fall within *corridor* of B's polyline.

    *poly_b_m* is B's polyline already converted to local metres.
    """
    if not pts_a or not poly_b_m:
        return 0.0
    on = 0
    for lat, lon in pts_a:
        mx, my = _to_metres(lat, lon, ref_lat, mpdlon)
        d = _min_dist_to_polyline(mx, my, poly_b_m)
        if d <= corridor:
            on += 1
    return on / len(pts_a)


def match_routes(
    pts_a: list[tuple[float, float]],
    pts_b: list[tuple[float, float]],
    dist_a: float = 0,
    dist_b: float = 0,
) -> bool:
    """True if routes A and B are the same route (bidirectional corridor check)."""
    if len(pts_a) < 3 or len(pts_b) < 3:
        return False
    # Distance pre-filter
    if dist_a > 0 and dist_b > 0:
        if min(dist_a, dist_b) / max(dist_a, dist_b) < _DIST_TOLERANCE:
            return False

    # Reference latitude for metre conversion
    ref_lat = pts_a[len(pts_a) // 2][0]
    mpdlon = _m_per_deg_lon(ref_lat)

    # Convert polylines to local metres
    poly_a_m = [_to_metres(lat, lon, ref_lat, mpdlon) for lat, lon in pts_a]
    poly_b_m = [_to_metres(lat, lon, ref_lat, mpdlon) for lat, lon in pts_b]

    # Bidirectional check
    frac_a_on_b = _fraction_on_route(pts_a, poly_b_m, ref_lat, mpdlon)
    if frac_a_on_b < _MATCH_THRESHOLD:
        return False
    frac_b_on_a = _fraction_on_route(pts_b, poly_a_m, ref_lat, mpdlon)
    return frac_b_on_a >= _MATCH_THRESHOLD


# ---------------------------------------------------------------------------
# Persistent index
# ---------------------------------------------------------------------------

_INDEX_FILE = "route_index.json"
_INDEX_VERSION = 7
_index: dict | None = None


def build_route_index(df: pd.DataFrame, export_dir: Path) -> dict:
    """Build or update the route fingerprint index."""
    global _index
    index_path = export_dir / _INDEX_FILE

    saved: dict = {}
    if index_path.exists():
        try:
            saved = json.loads(index_path.read_text())
            if saved.get("version") != _INDEX_VERSION:
                saved = {}
        except (json.JSONDecodeError, KeyError):
            saved = {}

    fingerprints: dict = saved.get("fingerprints", {})

    from strava_analytics.routes import parse_activity

    run_mask = df["type"].isin(["Run", "Walk", "Hike"])
    runs = df[run_mask & df["filename"].notna()]
    new_count = 0

    from .routes import resolve_activity_path

    for fn in runs["filename"].unique():
        if fn in fingerprints:
            continue
        fit_path = resolve_activity_path(export_dir, fn)
        if fit_path is None:
            continue
        try:
            stream = parse_activity(fit_path, max_points=300)
        except Exception:
            log.debug("route_matching: failed to parse %s", fn)
            continue
        if not stream.coords or len(stream.coords) < 5:
            continue
        pts = _sample_route(stream.coords, stream.distance_m)
        if len(pts) >= 3:
            fingerprints[fn] = {
                "points": [[round(p[0], 6), round(p[1], 6)] for p in pts],
                "distance_m": stream.distance_m[-1] if stream.distance_m else 0,
            }
            new_count += 1

    if new_count > 0 or not saved:
        try:
            index_path.write_text(json.dumps(
                {"version": _INDEX_VERSION, "fingerprints": fingerprints},
                indent=None, separators=(",", ":"),
            ))
        except OSError:
            log.warning("route_matching: failed to write index")

    _index = fingerprints
    log.info("route_matching: %d fingerprints (%d new)", len(fingerprints), new_count)
    return fingerprints


def get_route_matches(filename: str, df: pd.DataFrame, export_dir: Path) -> list[str]:
    """Return filenames of all other activities on the same route."""
    global _index
    if _index is None:
        build_route_index(df, export_dir)
    assert _index is not None

    entry = _index.get(filename)
    if not entry:
        return []

    pts_a = [(p[0], p[1]) for p in entry["points"]]
    dist_a = entry.get("distance_m", 0)
    matches: list[str] = []
    for fn, other in _index.items():
        if fn == filename:
            continue
        pts_b = [(p[0], p[1]) for p in other["points"]]
        dist_b = other.get("distance_m", 0)
        if match_routes(pts_a, pts_b, dist_a, dist_b):
            matches.append(fn)
    return matches
