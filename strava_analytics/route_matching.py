"""GPS route matching via rasterized grid cell overlap.

Each route is projected onto a ~20 m grid and buffered by one cell in
every direction (~60 m corridor).  Two routes match when ≥ 80 % of the
shorter route's cells appear in the longer route's cell set **and**
they are within 30 % of each other's total distance.

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
# Grid projection — local (lat, lon) → integer (cx, cy)
# ---------------------------------------------------------------------------

_CELL_M = 20  # metres per grid cell

# Approximate metres-per-degree at mid-latitudes
_M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lon(lat_deg: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat_deg))


def _to_cell(lat: float, lon: float, origin_lat: float, origin_lon: float,
             mpdlon: float) -> tuple[int, int]:
    cx = int((lon - origin_lon) * mpdlon / _CELL_M)
    cy = int((lat - origin_lat) * _M_PER_DEG_LAT / _CELL_M)
    return (cx, cy)


# ---------------------------------------------------------------------------
# Route fingerprinting
# ---------------------------------------------------------------------------

def fingerprint_route(
    coords: list[tuple[float, float]],
    origin_lat: float,
    origin_lon: float,
) -> set[tuple[int, int]]:
    """Rasterise a route into buffered grid cells.

    *coords* — list of (lat, lon).
    Returns a **set** of (cx, cy) integer cell indices.
    """
    if not coords or len(coords) < 3:
        return set()

    mpdlon = _m_per_deg_lon(origin_lat)
    cells: set[tuple[int, int]] = set()

    for lat, lon in coords:
        cx, cy = _to_cell(lat, lon, origin_lat, origin_lon, mpdlon)
        # Buffer: mark cell + 8 neighbours
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cells.add((cx + dx, cy + dy))

    return cells


def match_routes(
    cells_a: set[tuple[int, int]],
    cells_b: set[tuple[int, int]],
    dist_a: float = 0,
    dist_b: float = 0,
    threshold: float = 0.80,
) -> bool:
    """True if routes overlap spatially by ≥ *threshold* and have similar length."""
    if not cells_a or not cells_b:
        return False
    # Distance pre-filter
    if dist_a > 0 and dist_b > 0:
        ratio = min(dist_a, dist_b) / max(dist_a, dist_b)
        if ratio < 0.7:
            return False
    smaller, larger = (cells_a, cells_b) if len(cells_a) <= len(cells_b) else (cells_b, cells_a)
    overlap = len(smaller & larger)
    return overlap / len(smaller) >= threshold


# ---------------------------------------------------------------------------
# Persistent index
# ---------------------------------------------------------------------------

_INDEX_FILE = "route_index.json"
_index: dict | None = None
_origin: tuple[float, float] | None = None


def _cells_to_json(cells: set[tuple[int, int]]) -> list[list[int]]:
    return [list(c) for c in cells]


def _cells_from_json(raw: list) -> set[tuple[int, int]]:
    return {(c[0], c[1]) for c in raw}


def build_route_index(df: pd.DataFrame, export_dir: Path) -> dict:
    """Build or update the route fingerprint index."""
    global _index, _origin
    index_path = export_dir / _INDEX_FILE

    saved: dict = {}
    if index_path.exists():
        try:
            saved = json.loads(index_path.read_text())
            if saved.get("version") != 6:
                saved = {}
        except (json.JSONDecodeError, KeyError):
            saved = {}

    fingerprints: dict = saved.get("fingerprints", {})
    origin = saved.get("origin")

    from strava_analytics.routes import parse_activity

    run_mask = df["type"].isin(["Run", "Walk", "Hike"])
    runs = df[run_mask & df["filename"].notna()]

    # Determine grid origin from first route if not set
    if origin is None and not fingerprints:
        for fn in runs["filename"].unique():
            try:
                stream = parse_activity(export_dir / fn, max_points=50)
            except Exception:
                continue
            if stream.coords and len(stream.coords) >= 3:
                origin = [stream.coords[0][0], stream.coords[0][1]]
                break
    if origin is None:
        _index = {}
        _origin = (0, 0)
        return {}

    _origin = (origin[0], origin[1])
    new_count = 0

    for fn in runs["filename"].unique():
        if fn in fingerprints:
            continue
        try:
            stream = parse_activity(export_dir / fn, max_points=200)
        except Exception:
            log.debug("route_matching: failed to parse %s", fn)
            continue
        if not stream.coords or len(stream.coords) < 5:
            continue
        cells = fingerprint_route(stream.coords, origin[0], origin[1])
        if cells:
            fingerprints[fn] = {
                "cells": _cells_to_json(cells),
                "distance_m": stream.distance_m[-1] if stream.distance_m else 0,
            }
            new_count += 1

    if new_count > 0:
        try:
            index_path.write_text(json.dumps(
                {"version": 6, "origin": origin, "fingerprints": fingerprints},
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

    fp = _cells_from_json(entry["cells"])
    dist = entry.get("distance_m", 0)
    matches: list[str] = []
    for fn, other in _index.items():
        if fn == filename:
            continue
        other_fp = _cells_from_json(other["cells"])
        other_dist = other.get("distance_m", 0)
        if match_routes(fp, other_fp, dist, other_dist):
            matches.append(fn)
    return matches
