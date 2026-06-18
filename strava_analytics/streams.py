"""Per-second activity streams pulled from the Strava API.

The CSV-export ingest path saves a .fit.gz per activity under DATA_DIR/fit/,
and routes.py parses those for HR, distance, GPS, etc. The Strava API path
gives us the same data via /activities/{id}/streams — but we have nowhere
to drop it that the FIT parsers know about.

This module is the bridge:
  * `serialize_streams` / `deserialize_streams` for DB storage (compact
    gzip+base64 of a Strava streams dict, fits in a TEXT column)
  * `fetch_streams_from_strava` wraps stravalib's `get_activity_streams`
    and normalizes the result to a plain dict of {stream_name: list}
  * `streams_to_activity_stream` / `streams_to_hr_points` /
    `streams_to_distance_points` build the same return shapes the FIT
    parsers in routes.py produce, so consumers can call either one
    transparently
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# Strava stream types we care about. Anything not in this list is dropped
# from the saved blob to keep size reasonable. Order doesn't matter at
# fetch time but matches the order in the Strava docs for readability.
STREAM_TYPES = [
    "time",
    "distance",
    "heartrate",
    "altitude",
    "latlng",
    "cadence",
    "velocity_smooth",
    "temp",
    "watts",
]


def serialize_streams(streams: dict) -> str:
    """Encode a streams dict to a compact text blob suitable for TEXT.

    Doubles as a no-op short-circuit for empty input.
    """
    if not streams:
        return ""
    payload = json.dumps(streams, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=6)
    return base64.b64encode(compressed).decode("ascii")


def deserialize_streams(blob: str | None) -> dict:
    """Reverse of `serialize_streams`. Returns {} on any failure."""
    if not blob:
        return {}
    try:
        compressed = base64.b64decode(blob.encode("ascii"))
        payload = gzip.decompress(compressed).decode("utf-8")
        result = json.loads(payload)
        return result if isinstance(result, dict) else {}
    except Exception as e:
        logger.warning("Failed to deserialize streams blob: %s", e)
        return {}


def fetch_streams_from_strava(client: Any, activity_id: int) -> dict | None:
    """Call stravalib's `get_activity_streams` and normalize the result.

    Returns a dict like ``{"time": [0, 1, ...], "heartrate": [120, ...]}``
    or None on failure / empty response.
    """
    try:
        raw = client.get_activity_streams(
            activity_id, types=STREAM_TYPES, resolution="high"
        )
    except Exception as e:
        logger.warning(
            "get_activity_streams failed for %s: %s", activity_id, e
        )
        return None
    if not raw:
        return None

    out: dict[str, list] = {}
    for name, stream_obj in raw.items():
        if stream_obj is None:
            continue
        data = getattr(stream_obj, "data", None)
        if data is None or not isinstance(data, (list, tuple)):
            continue
        # Coerce tuples / numpy-ish values to plain lists / floats so JSON
        # serialization stays small and deterministic.
        out[name] = [_coerce(v) for v in data]
    return out or None


def _coerce(v):
    """Push numpy scalars / tuples through JSON-friendly types."""
    if isinstance(v, (list, tuple)):
        return [_coerce(x) for x in v]
    if v is None:
        return None
    try:
        # int and float both pass through json.dumps directly; numpy
        # scalars need a cast.
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return v
        return float(v)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stream → ActivityStream-shaped conversions.
#
# routes.py defines an ActivityStream dataclass and three parsers that take a
# FIT file path: parse_activity, parse_hr_stream, parse_distance_stream. The
# Strava-API path produces the same data, just in a Strava-streams shape.
# The functions below match those parsers' output exactly so downstream
# consumers (charts, zone-time aggregations, best-effort search) can be
# pointed at either source.
# ---------------------------------------------------------------------------


def _abs_time(start_time: datetime | None, offset_s: int | float) -> datetime | None:
    """Add a Strava `time` stream offset (seconds) to the activity start.

    Returns None if start_time isn't known — callers handle that.
    """
    if start_time is None or offset_s is None:
        return None
    try:
        return start_time + timedelta(seconds=int(offset_s))
    except Exception:
        return None


def streams_to_activity_stream(
    streams: dict, start_time: datetime | None, max_points: int = 300
):
    """Mirror routes.parse_activity output from a Strava streams dict.

    Returns an ActivityStream (imported lazily to avoid a circular dep —
    routes.py imports streams.py inside its own helpers).
    """
    from .routes import ActivityStream
    out = ActivityStream()

    time_stream = streams.get("time") or []
    if not time_stream:
        return out

    distance = streams.get("distance") or []
    heartrate = streams.get("heartrate") or []
    altitude = streams.get("altitude") or []
    latlng = streams.get("latlng") or []
    cadence = streams.get("cadence") or []
    velocity = streams.get("velocity_smooth") or []
    temperature = streams.get("temp") or []

    n = len(time_stream)
    indices: list[int]
    if n > max_points:
        step = n / max_points
        indices = [int(i * step) for i in range(max_points)]
    else:
        indices = list(range(n))

    for i in indices:
        # Mirror routes.parse_activity: only emit a point when this
        # record has a distance value (the canonical x-axis). Missing
        # distance → skip the row entirely.
        if i >= len(distance) or distance[i] is None:
            continue
        out.distance_m.append(float(distance[i]))
        if i < len(latlng):
            ll = latlng[i]
            if isinstance(ll, (list, tuple)) and len(ll) == 2 and ll[0] is not None and ll[1] is not None:
                out.coords.append((float(ll[0]), float(ll[1])))
        if i < len(heartrate) and heartrate[i] is not None:
            out.heart_rate.append(int(heartrate[i]))
        if i < len(velocity) and velocity[i] is not None:
            out.speed_ms.append(float(velocity[i]))
        if i < len(altitude) and altitude[i] is not None:
            out.altitude_m.append(float(altitude[i]))
        if i < len(cadence) and cadence[i] is not None:
            out.cadence.append(int(cadence[i]))
        if i < len(temperature) and temperature[i] is not None:
            out.temperature_c.append(float(temperature[i]))
        ts = _abs_time(start_time, time_stream[i])
        if ts is not None:
            out.timestamps.append(ts)

    return out


def streams_to_hr_points(
    streams: dict, start_time: datetime | None
) -> list[tuple]:
    """Mirror routes.parse_hr_stream output.

    Returns ``[(timestamp, hr_int), ...]`` at full resolution.
    """
    if start_time is None:
        return []
    time_stream = streams.get("time") or []
    heartrate = streams.get("heartrate") or []
    out: list[tuple] = []
    n = min(len(time_stream), len(heartrate))
    for i in range(n):
        hr = heartrate[i]
        if hr is None or hr <= 0:
            continue
        ts = _abs_time(start_time, time_stream[i])
        if ts is None:
            continue
        out.append((ts, int(hr)))
    return out


def streams_to_distance_points(
    streams: dict, start_time: datetime | None
) -> list[tuple]:
    """Mirror routes.parse_distance_stream output.

    Returns ``[(timestamp, distance_m), ...]`` at full resolution.
    """
    if start_time is None:
        return []
    time_stream = streams.get("time") or []
    distance = streams.get("distance") or []
    out: list[tuple] = []
    n = min(len(time_stream), len(distance))
    for i in range(n):
        d = distance[i]
        if d is None:
            continue
        ts = _abs_time(start_time, time_stream[i])
        if ts is None:
            continue
        out.append((ts, float(d)))
    return out
