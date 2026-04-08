"""GPS route matching via sampled-point geohash fingerprinting.

Matches runs that follow the same physical route regardless of direction,
name, or slight GPS drift.  Fingerprints are cached to ``route_index.json``
in the export directory for fast incremental updates.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Geohash encoding (no external dependency)
# ---------------------------------------------------------------------------

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def _geohash(lat: float, lon: float, precision: int = 7) -> str:
    """Encode (lat, lon) as a geohash string.  Precision 7 ≈ 150 m × 150 m."""
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    bits = [16, 8, 4, 2, 1]
    ch, bit, is_lon = 0, 0, True
    result: list[str] = []
    while len(result) < precision:
        if is_lon:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon >= mid:
                ch |= bits[bit]
                lon_range[0] = mid
            else:
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                ch |= bits[bit]
                lat_range[0] = mid
            else:
                lat_range[1] = mid
        is_lon = not is_lon
        bit += 1
        if bit == 5:
            result.append(_BASE32[ch])
            ch, bit = 0, 0
    return "".join(result)


# ---------------------------------------------------------------------------
# Route fingerprinting
# ---------------------------------------------------------------------------

def fingerprint_route(
    coords: list[tuple[float, float]],
    distance_m: list[float] | None = None,
    n_samples: int = 20,
) -> frozenset[str]:
    """Sample *n_samples* evenly-spaced points and return their geohash cells.

    If *distance_m* is provided, samples are spaced by distance; otherwise
    they are spaced by index.
    """
    if not coords or len(coords) < 3:
        return frozenset()

    if distance_m and len(distance_m) == len(coords):
        total = distance_m[-1]
        if total <= 0:
            return frozenset()
        step = total / n_samples
        cells: list[str] = []
        di = 0
        for s in range(n_samples):
            target = step * (s + 0.5)
            while di < len(distance_m) - 1 and distance_m[di] < target:
                di += 1
            cells.append(_geohash(coords[di][0], coords[di][1]))
        return frozenset(cells)

    # Fallback: index-based sampling
    step = max(1, len(coords) // n_samples)
    return frozenset(_geohash(c[0], c[1]) for c in coords[::step])


def match_routes(
    fp_a: frozenset[str],
    fp_b: frozenset[str],
    threshold: float = 0.75,
) -> bool:
    """True if the smaller fingerprint overlaps the larger by ≥ *threshold*."""
    if not fp_a or not fp_b:
        return False
    smaller, larger = (fp_a, fp_b) if len(fp_a) <= len(fp_b) else (fp_b, fp_a)
    overlap = len(smaller & larger)
    return overlap / len(smaller) >= threshold


# ---------------------------------------------------------------------------
# Persistent index
# ---------------------------------------------------------------------------

_INDEX_FILE = "route_index.json"
_index: dict | None = None


def build_route_index(df: pd.DataFrame, export_dir: Path) -> dict:
    """Build or update the route fingerprint index.

    Returns ``{filename: {"cells": [...], "distance_m": float}}``.
    """
    global _index
    index_path = export_dir / _INDEX_FILE

    # Load existing index
    saved: dict = {}
    if index_path.exists():
        try:
            saved = json.loads(index_path.read_text())
            if saved.get("version") != 2:
                saved = {}
        except (json.JSONDecodeError, KeyError):
            saved = {}

    fingerprints: dict = saved.get("fingerprints", {})

    from strava_analytics.routes import parse_activity

    run_mask = df["type"].isin(["Run", "Walk", "Hike"])
    runs = df[run_mask & df["filename"].notna()]
    new_count = 0

    for fn in runs["filename"].unique():
        if fn in fingerprints:
            continue
        try:
            stream = parse_activity(export_dir / fn, max_points=100)
        except Exception:
            log.debug("route_matching: failed to parse %s", fn)
            continue
        if not stream.coords or len(stream.coords) < 5:
            continue
        fp = fingerprint_route(stream.coords, stream.distance_m)
        if fp:
            fingerprints[fn] = {
                "cells": sorted(fp),
                "distance_m": stream.distance_m[-1] if stream.distance_m else 0,
            }
            new_count += 1

    if new_count > 0:
        # Persist
        try:
            index_path.write_text(json.dumps(
                {"version": 2, "fingerprints": fingerprints},
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

    fp = frozenset(entry["cells"])
    matches: list[str] = []
    for fn, other in _index.items():
        if fn == filename:
            continue
        other_fp = frozenset(other["cells"])
        if match_routes(fp, other_fp):
            matches.append(fn)
    return matches
