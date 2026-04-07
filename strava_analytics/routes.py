"""Parse GPS routes and activity streams from Strava FIT.gz export files."""

import gzip
import logging
from pathlib import Path
from dataclasses import dataclass, field

import fitparse

logger = logging.getLogger(__name__)


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

                speed = record.get_value("enhanced_speed") or record.get_value("speed")
                if speed is not None:
                    rec["speed"] = float(speed)

                alt = record.get_value("enhanced_altitude") or record.get_value("altitude")
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

    stream = ActivityStream()
    for rec in records:
        if "lat" in rec and "lon" in rec:
            stream.coords.append((rec["lat"], rec["lon"]))
        if "hr" in rec:
            stream.heart_rate.append(rec["hr"])
        if "speed" in rec:
            stream.speed_ms.append(rec["speed"])
        if "alt" in rec:
            stream.altitude_m.append(rec["alt"])
        if "cad" in rec:
            stream.cadence.append(rec["cad"])
        if "dist" in rec:
            stream.distance_m.append(rec["dist"])
        if "ts" in rec:
            stream.timestamps.append(rec["ts"])
        if "temp" in rec:
            stream.temperature_c.append(rec["temp"])

    return stream


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

            # Elevation gain for the split
            elev_gain_ft = 0
            if stream.altitude_m:
                alt_slice = stream.altitude_m[split_start_idx:i+1]
                for j in range(1, len(alt_slice)):
                    if alt_slice[j] > alt_slice[j-1]:
                        elev_gain_ft += (alt_slice[j] - alt_slice[j-1]) * 3.28084

            splits.append({
                "split_num": split_num,
                "distance_mi": dist_mi,
                "pace_min_per_mi": pace,
                "avg_hr": avg_hr,
                "elevation_gain_ft": elev_gain_ft,
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

            splits.append({
                "split_num": split_num,
                "distance_mi": dist_mi,
                "pace_min_per_mi": pace,
                "avg_hr": avg_hr,
                "elevation_gain_ft": 0,
                "elapsed_s": time_s,
            })

    return splits


def parse_route(fit_gz_path: str | Path, max_points: int = 300) -> list[tuple[float, float]]:
    """Extract just lat/lon coordinates (backward compat)."""
    return parse_activity(fit_gz_path, max_points).coords
