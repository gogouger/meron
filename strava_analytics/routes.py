"""Parse GPS routes and activity streams from Strava FIT.gz export files."""

import gzip
import logging
from pathlib import Path
from dataclasses import dataclass, field

import fitparse

logger = logging.getLogger(__name__)


def resolve_activity_path(export_dir, filename) -> Path | None:
    """Resolve a stored ``filename`` to an on-disk FIT path.

    Stored filenames come from the original Strava export layout as
    ``activities/<id>.fit.gz``. Newer MERON installs keep the files
    under ``<meron_dir>/fit/`` instead — we check both locations so
    older DB rows with the legacy prefix still resolve.

    Returns ``None`` when neither location contains the file.
    """
    if not filename or not isinstance(filename, str):
        return None
    export_dir = Path(export_dir)
    primary = export_dir / filename
    if primary.exists():
        return primary
    # Fall back to <export_dir>/fit/<basename> — current MERON layout.
    fallback = export_dir / "fit" / Path(filename).name
    if fallback.exists():
        return fallback
    return None


@dataclass
class ActivityStream:
    """Parsed activity data from a FIT file."""
    coords: list[tuple[float, float]] = field(default_factory=list)
    heart_rate: list[int] = field(default_factory=list)
    speed_ms: list[float] = field(default_factory=list)
    altitude_m: list[float] = field(default_factory=list)
    cadence: list[int] = field(default_factory=list)
    distance_m: list[float] = field(default_factory=list)
    timestamps: list = field(default_factory=list)
    temperature_c: list[float] = field(default_factory=list)


def parse_activity(fit_gz_path: str | Path, max_points: int = 300) -> ActivityStream:
    """Extract all activity streams from a FIT.gz file.

    Returns an ActivityStream with coords, HR, speed, altitude, etc.
    Downsampled to max_points for performance.
    """
    path = Path(fit_gz_path)
    logger.debug("Parsing FIT file: %s", path)
    if not path.exists():
        return ActivityStream()

    records = []
    try:
        with gzip.open(path) as f:
            fit = fitparse.FitFile(f)
            for record in fit.get_messages("record"):
                rec = {}
                lat = record.get_value("position_lat")
                lon = record.get_value("position_long")
                if lat is not None and lon is not None:
                    rec["lat"] = lat * (180 / 2**31)
                    rec["lon"] = lon * (180 / 2**31)

                hr = record.get_value("heart_rate")
                if hr is not None:
                    rec["hr"] = int(hr)

                speed = record.get_value("enhanced_speed")
                if speed is None:
                    speed = record.get_value("speed")
                if speed is not None:
                    rec["speed"] = float(speed)

                alt = record.get_value("enhanced_altitude")
                if alt is None:
                    alt = record.get_value("altitude")
                if alt is not None:
                    rec["alt"] = float(alt)

                cad = record.get_value("cadence")
                if cad is not None:
                    rec["cad"] = int(cad)

                dist = record.get_value("distance")
                if dist is not None:
                    rec["dist"] = float(dist)

                ts = record.get_value("timestamp")
                if ts is not None:
                    rec["ts"] = ts

                temp = record.get_value("temperature")
                if temp is not None:
                    rec["temp"] = float(temp)

                if rec:
                    records.append(rec)
    except Exception as e:
        logger.warning("Failed to parse %s: %s", path, e)
        return ActivityStream()

    if not records:
        return ActivityStream()

    # Downsample
    if len(records) > max_points:
        step = len(records) / max_points
        records = [records[int(i * step)] for i in range(max_points)]

    # Build aligned streams. Only include records that have a distance value
    # (the primary x-axis). Carry forward HR/speed/altitude/etc. for records
    # that have distance but are missing other fields.
    stream = ActivityStream()
    last = {}  # last-seen value per field for carry-forward
    for rec in records:
        last.update(rec)
        # Only emit a point when this record has its own distance
        if "dist" not in rec:
            continue
        if "lat" in last and "lon" in last:
            stream.coords.append((last["lat"], last["lon"]))
        if "hr" in last:
            stream.heart_rate.append(last["hr"])
        if "speed" in last:
            stream.speed_ms.append(last["speed"])
        if "alt" in last:
            stream.altitude_m.append(last["alt"])
        if "cad" in last:
            stream.cadence.append(last["cad"])
        stream.distance_m.append(rec["dist"])
        if "ts" in last:
            stream.timestamps.append(last["ts"])
        if "temp" in last:
            stream.temperature_c.append(last["temp"])

    return stream


# ---------------------------------------------------------------------------
# Dual-source helpers: prefer a streams_blob (Strava-API rows) over a FIT
# file (CSV-export rows). Used by the consumers in enrichment / fitness /
# cards so they don't have to special-case the source. Each helper accepts
# either a dict-like row (DataFrame .iloc) or a mapping with `filename` and
# `streams_blob` keys, plus optional `start_time` / `date`.
# ---------------------------------------------------------------------------


def _row_blob(row) -> str | None:
    try:
        v = row.get("streams_blob") if hasattr(row, "get") else None
    except Exception:
        v = None
    if v is None:
        return None
    # pandas serializes NaN for absent strings — guard against that.
    try:
        import pandas as pd
        if isinstance(v, float) and pd.isna(v):
            return None
    except Exception:
        pass
    return v if isinstance(v, str) and v else None


def _row_start_time(row):
    """Pull a tz-naive (local) datetime out of a DataFrame row.

    Repository emits the activity start under ``date``; raw ORM rows
    expose ``start_time``. Accept either.
    """
    for key in ("date", "start_time"):
        try:
            v = row.get(key) if hasattr(row, "get") else None
        except Exception:
            continue
        if v is None:
            continue
        try:
            import pandas as pd
            ts = pd.to_datetime(v)
            return ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        except Exception:
            continue
    return None


def parse_activity_for_row(row, max_points: int = 300) -> "ActivityStream":
    """Return an ActivityStream from either streams_blob or the FIT sidecar.

    Order: streams_blob → resolve_activity_path(filename) → empty.
    """
    blob = _row_blob(row)
    if blob:
        from .streams import deserialize_streams, streams_to_activity_stream
        streams = deserialize_streams(blob)
        if streams:
            return streams_to_activity_stream(
                streams, _row_start_time(row), max_points
            )
    fn = row.get("filename") if hasattr(row, "get") else None
    if isinstance(fn, str) and fn:
        from .web import data as _data
        path = resolve_activity_path(_data.get_export_dir(), fn)
        if path is not None:
            return parse_activity(path, max_points)
    return ActivityStream()


def parse_hr_stream_for_row(row) -> list[tuple]:
    """Return [(ts, hr), ...] from either streams_blob or the FIT sidecar."""
    blob = _row_blob(row)
    if blob:
        from .streams import deserialize_streams, streams_to_hr_points
        streams = deserialize_streams(blob)
        if streams:
            return streams_to_hr_points(streams, _row_start_time(row))
    fn = row.get("filename") if hasattr(row, "get") else None
    if isinstance(fn, str) and fn:
        from .web import data as _data
        path = resolve_activity_path(_data.get_export_dir(), fn)
        if path is not None:
            return parse_hr_stream(path)
    return []


def parse_distance_stream_for_row(row) -> list[tuple]:
    """Return [(ts, distance_m), ...] from either streams_blob or the FIT sidecar."""
    blob = _row_blob(row)
    if blob:
        from .streams import deserialize_streams, streams_to_distance_points
        streams = deserialize_streams(blob)
        if streams:
            return streams_to_distance_points(streams, _row_start_time(row))
    fn = row.get("filename") if hasattr(row, "get") else None
    if isinstance(fn, str) and fn:
        from .web import data as _data
        path = resolve_activity_path(_data.get_export_dir(), fn)
        if path is not None:
            return parse_distance_stream(path)
    return []


def parse_hr_stream(fit_gz_path: str | Path) -> list[tuple]:
    """Extract HR + timestamp stream at full resolution from a FIT.gz file.

    Returns list of (timestamp, heart_rate) tuples — no downsampling.
    Lightweight: skips GPS, speed, altitude, etc.
    """
    path = Path(fit_gz_path)
    if not path.exists():
        return []

    points = []
    try:
        with gzip.open(path) as f:
            fit = fitparse.FitFile(f)
            for record in fit.get_messages("record"):
                ts = record.get_value("timestamp")
                hr = record.get_value("heart_rate")
                if ts is not None and hr is not None and hr > 0:
                    points.append((ts, int(hr)))
    except Exception as e:
        logger.warning("Failed to parse HR stream from %s: %s", path, e)
        return []

    return points


def parse_distance_stream(fit_gz_path: str | Path) -> list[tuple]:
    """Extract distance + timestamp stream at full resolution from a FIT.gz file.

    Returns list of (timestamp, distance_meters) tuples — no downsampling.
    Lightweight: skips GPS, HR, speed, altitude, etc.
    """
    path = Path(fit_gz_path)
    if not path.exists():
        return []

    points = []
    try:
        with gzip.open(path) as f:
            fit = fitparse.FitFile(f)
            for record in fit.get_messages("record"):
                ts = record.get_value("timestamp")
                dist = record.get_value("distance")
                if ts is not None and dist is not None:
                    points.append((ts, float(dist)))
    except Exception as e:
        logger.warning("Failed to parse distance stream from %s: %s", path, e)
        return []

    return points


def compute_splits(stream: ActivityStream, split_distance_m: float = 1609.34) -> list[dict]:
    """Compute per-mile (or per-split) pace, HR, and elevation from activity stream.

    Returns list of dicts with keys: split_num, distance_mi, pace_min_per_mi,
    avg_hr, elevation_gain_ft, elapsed_s.
    """
    if not stream.distance_m or len(stream.distance_m) < 2:
        return []

    splits = []
    split_start_idx = 0
    split_num = 1

    for i in range(1, len(stream.distance_m)):
        dist_in_split = stream.distance_m[i] - stream.distance_m[split_start_idx]

        if dist_in_split >= split_distance_m:
            # Calculate split metrics
            time_s = 0
            if stream.timestamps and len(stream.timestamps) > i:
                t0 = stream.timestamps[split_start_idx]
                t1 = stream.timestamps[i]
                if hasattr(t0, 'timestamp') and hasattr(t1, 'timestamp'):
                    time_s = (t1 - t0).total_seconds()
                elif isinstance(t0, (int, float)):
                    time_s = t1 - t0

            dist_mi = dist_in_split / 1609.34
            pace = (time_s / 60.0) / dist_mi if dist_mi > 0 and time_s > 0 else 0

            # Avg HR for the split
            avg_hr = 0
            if stream.heart_rate:
                hr_slice = stream.heart_rate[split_start_idx:i+1]
                valid_hr = [h for h in hr_slice if h > 0]
                avg_hr = sum(valid_hr) / len(valid_hr) if valid_hr else 0

            # Elevation for the split
            elev_gain_ft = 0
            elev_change_ft = 0
            if stream.altitude_m and len(stream.altitude_m) > i:
                alt_slice = stream.altitude_m[split_start_idx:i+1]
                elev_change_ft = (alt_slice[-1] - alt_slice[0]) * 3.28084
                for j in range(1, len(alt_slice)):
                    if alt_slice[j] > alt_slice[j-1]:
                        elev_gain_ft += (alt_slice[j] - alt_slice[j-1]) * 3.28084

            splits.append({
                "split_num": split_num,
                "distance_mi": dist_mi,
                "pace_min_per_mi": pace,
                "avg_hr": avg_hr,
                "elevation_gain_ft": elev_gain_ft,
                "elevation_change_ft": elev_change_ft,
                "elapsed_s": time_s,
            })

            split_start_idx = i
            split_num += 1

    # Handle remaining partial split (if > 0.25 mi)
    if split_start_idx < len(stream.distance_m) - 1:
        remaining_dist = stream.distance_m[-1] - stream.distance_m[split_start_idx]
        if remaining_dist > 402:  # > 0.25 mi
            time_s = 0
            if stream.timestamps and len(stream.timestamps) > split_start_idx:
                t0 = stream.timestamps[split_start_idx]
                t1 = stream.timestamps[-1]
                if hasattr(t0, 'timestamp'):
                    time_s = (t1 - t0).total_seconds()

            dist_mi = remaining_dist / 1609.34
            pace = (time_s / 60.0) / dist_mi if dist_mi > 0 and time_s > 0 else 0

            avg_hr = 0
            if stream.heart_rate:
                hr_slice = stream.heart_rate[split_start_idx:]
                valid_hr = [h for h in hr_slice if h > 0]
                avg_hr = sum(valid_hr) / len(valid_hr) if valid_hr else 0

            elev_change_ft = 0
            if stream.altitude_m and len(stream.altitude_m) > split_start_idx:
                alt_slice = stream.altitude_m[split_start_idx:]
                elev_change_ft = (alt_slice[-1] - alt_slice[0]) * 3.28084

            splits.append({
                "split_num": split_num,
                "distance_mi": dist_mi,
                "pace_min_per_mi": pace,
                "avg_hr": avg_hr,
                "elevation_gain_ft": 0,
                "elevation_change_ft": elev_change_ft,
                "elapsed_s": time_s,
            })

    return splits


def parse_route(fit_gz_path: str | Path, max_points: int = 300) -> list[tuple[float, float]]:
    """Extract just lat/lon coordinates (backward compat)."""
    return parse_activity(fit_gz_path, max_points).coords
