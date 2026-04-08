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


def _geohash(lat: float, lon: float, precision: int = 8) -> str:
    """Encode (lat, lon) as a geohash string.  Precision 8 ≈ 20 m × 40 m."""
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
    n_samples: int = 40,
) -> list[str]:
    """Sample *n_samples* evenly-spaced points and return ordered geohash cells.

    Returns an **ordered list** so sequence-based matching can distinguish
    routes through the same neighborhood but in different patterns.
    Consecutive duplicate cells are collapsed to keep the sequence concise.
    """
    if not coords or len(coords) < 3:
        return []

    raw: list[str] = []
    if distance_m and len(distance_m) == len(coords):
        total = distance_m[-1]
        if total <= 0:
            return []
        step = total / n_samples
        di = 0
        for s in range(n_samples):
            target = step * (s + 0.5)
            while di < len(distance_m) - 1 and distance_m[di] < target:
                di += 1
            raw.append(_geohash(coords[di][0], coords[di][1]))
    else:
        step = max(1, len(coords) // n_samples)
        raw = [_geohash(c[0], c[1]) for c in coords[::step]]

    # Collapse consecutive duplicates
    collapsed: list[str] = []
    for c in raw:
        if not collapsed or c != collapsed[-1]:
            collapsed.append(c)
    return collapsed


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Length of longest common subsequence (O(n*m) DP, bounded by sample count)."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    # Space-optimized: two rows
    prev = [0] * (m + 1)
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (m + 1)
    return max(prev)


def match_routes(
    fp_a: list[str],
    fp_b: list[str],
    dist_a: float = 0,
    dist_b: float = 0,
    threshold: float = 0.65,
) -> bool:
    """True if routes match by ordered subsequence overlap and similar distance."""
    if not fp_a or not fp_b:
        return False
    # Distance check: routes must be within 30% of each other
    if dist_a > 0 and dist_b > 0:
        ratio = min(dist_a, dist_b) / max(dist_a, dist_b)
        if ratio < 0.7:
            return False
    shorter = min(len(fp_a), len(fp_b))
    if shorter < 3:
        return False
    # Check forward and reverse (handles running route in opposite direction)
    lcs_fwd = _lcs_length(fp_a, fp_b)
    lcs_rev = _lcs_length(fp_a, fp_b[::-1])
    best = max(lcs_fwd, lcs_rev)
    return best / shorter >= threshold


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
            if saved.get("version") != 4:
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
                "cells": fp,
                "distance_m": stream.distance_m[-1] if stream.distance_m else 0,
            }
            new_count += 1

    if new_count > 0:
        # Persist
        try:
            index_path.write_text(json.dumps(
                {"version": 4, "fingerprints": fingerprints},
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

    fp = entry["cells"]
    dist = entry.get("distance_m", 0)
    matches: list[str] = []
    for fn, other in _index.items():
        if fn == filename:
            continue
        if match_routes(fp, other["cells"], dist, other.get("distance_m", 0)):
            matches.append(fn)
    return matches
