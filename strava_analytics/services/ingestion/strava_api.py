"""Strava API incremental sync via stravalib.

Pulls activities since `sync_state.last_sync_at`, upserts them into the DB,
and updates the cursor. Rate-limit aware (Strava: 100/15min, 1000/day).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth.strava_oauth import load_tokens, refresh_if_needed
from ...db import meron_dir
from ...db.models import SyncState
from ...db.repository import upsert_from_strava_record
from . import IngestReport

logger = logging.getLogger(__name__)


def _merge_route_index(new_polylines: dict[str, list]) -> None:
    """Add API-fetched polylines to route_index.json under ``strava:<id>``.

    The fingerprint index is the canonical source for mini-map data.
    Keeping API polylines in the same file means ``_mini_map`` and the
    REST route endpoint both Just Work without a second lookup path.
    """
    index_path = meron_dir() / "route_index.json"
    try:
        raw = json.loads(index_path.read_text()) if index_path.exists() else {}
    except Exception:
        raw = {}
    fingerprints = dict(raw.get("fingerprints") or {})
    for source_id, points in new_polylines.items():
        fingerprints[f"strava:{source_id}"] = {
            "points": points, "source": "strava_api_summary",
        }
    raw["fingerprints"] = fingerprints
    try:
        index_path.write_text(json.dumps(raw, separators=(",", ":")))
        logger.info("route_index: merged %d API polylines", len(new_polylines))
    except Exception as e:
        logger.warning("route_index write failed: %s", e)


def _extract_type(act) -> str:
    """stravalib 2.x wraps type/sport_type in pydantic RootModels.

    Returns the clean activity-type string (e.g. "Run"), matching the CSV
    export convention (adds a space to "WeightTraining").
    """
    raw = getattr(act, "type", None) or getattr(act, "sport_type", None)
    if raw is None:
        return ""
    # Pydantic RootModel → .root holds the enum string
    val = getattr(raw, "root", None)
    if val is None:
        val = str(raw)
    val = str(val)
    # Normalize API spellings to match the CSV convention used everywhere else
    return _SPORT_TYPE_NORMALIZE.get(val, val)


# Map Strava API sport types to the spelling the rest of MERON uses
# (matches the Strava bulk-CSV export conventions).
_SPORT_TYPE_NORMALIZE = {
    "WeightTraining": "Weight Training",
    "VirtualRun": "Virtual Run",
    "VirtualRide": "Virtual Ride",
    "TrailRun": "Trail Run",
    "RockClimbing": "Rock Climbing",
    "StairStepper": "Stair Stepper",
    "EBikeRide": "E-Bike Ride",
    "MountainBikeRide": "Mountain Bike Ride",
    "GravelRide": "Gravel Ride",
    "HighIntensityIntervalTraining": "HIIT",
    "AlpineSki": "Alpine Ski",
    "BackcountrySki": "Backcountry Ski",
    "NordicSki": "Nordic Ski",
    "InlineSkate": "Inline Skate",
    "IceSkate": "Ice Skate",
    "StandUpPaddling": "Stand Up Paddling",
    "WaterSport": "Water Sport",
    "RollerSki": "Roller Ski",
}


def _strava_activity_to_payload(act) -> dict:
    """Map a stravalib Activity to our model fields."""
    # stravalib returns Quantity-wrapped numbers; stringify/coerce.
    def n(q):
        if q is None:
            return None
        try:
            return float(q)
        except Exception:
            try:
                return float(q.magnitude)
            except Exception:
                return None

    # Extract the encoded summary polyline if present (free from the
    # summary list endpoint). DetailedActivity also has ``map.polyline``
    # which is higher-resolution but we only ask for summary to save
    # bandwidth — mini-maps don't need every point.
    polyline_str = None
    m = getattr(act, "map", None)
    if m is not None:
        polyline_str = (
            getattr(m, "summary_polyline", None)
            or getattr(m, "polyline", None)
        )

    return {
        "start_time": getattr(act, "start_date_local", None) or getattr(act, "start_date", None),
        "name": getattr(act, "name", None),
        "type": _extract_type(act),
        "description": getattr(act, "description", None),
        "gear": str(getattr(act, "gear_id", "") or "") or None,
        "elapsed_time_s": n(getattr(act, "elapsed_time", None)),
        "moving_time_s": n(getattr(act, "moving_time", None)),
        "distance_m": n(getattr(act, "distance", None)),
        "max_speed_ms": n(getattr(act, "max_speed", None)),
        "avg_speed_ms": n(getattr(act, "average_speed", None)),
        "elevation_gain_m": n(getattr(act, "total_elevation_gain", None)),
        "elevation_high_m": n(getattr(act, "elev_high", None)),
        "elevation_low_m": n(getattr(act, "elev_low", None)),
        "max_hr": n(getattr(act, "max_heartrate", None)),
        "avg_hr": n(getattr(act, "average_heartrate", None)),
        "avg_watts": n(getattr(act, "average_watts", None)),
        "calories": n(getattr(act, "calories", None)),
        "weather_temp_c": n(getattr(act, "average_temp", None)),
        # Non-model-column hints the upsert path consumes separately:
        "_summary_polyline": polyline_str,
    }


def _decode_polyline(encoded: str) -> list[list[float]]:
    """Decode a Google Encoded Polyline string to ``[[lat, lon], ...]``.

    Implements the standard algorithm (same one Strava uses). Pure
    Python so we don't pull in another dep just for this.
    """
    if not encoded:
        return []
    coords: list[list[float]] = []
    index = 0
    lat = 0
    lng = 0
    n_chars = len(encoded)
    while index < n_chars:
        for target in ("lat", "lng"):
            shift = 0
            result = 0
            while True:
                if index >= n_chars:
                    return coords
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if target == "lat":
                lat += delta
            else:
                lng += delta
        coords.append([round(lat * 1e-5, 5), round(lng * 1e-5, 5)])
    return coords


def sync_incremental(
    user_id: int,
    session: Session,
    since: Optional[datetime] = None,
) -> dict:
    """Fetch new Strava activities since last sync and upsert them.

    Pass ``since`` (a tz-aware datetime) to force a re-pull of everything
    after that point — used when new payload fields (descriptions,
    polylines) need to backfill onto already-synced rows. When ``None``
    the stored ``sync_state.last_sync_at`` cursor is used (default).

    Returns an IngestReport dict.
    """
    report = IngestReport()

    sync_row = session.scalar(
        select(SyncState).where(
            SyncState.user_id == user_id,
            SyncState.provider == "strava",
        )
    )
    if sync_row is None or not sync_row.refresh_token:
        report.errors.append("not_connected: Strava OAuth not configured")
        return report.to_dict()

    try:
        token = refresh_if_needed(user_id=user_id, session=session)
    except Exception as e:
        logger.exception("Token refresh failed")
        report.errors.append(f"auth: {e}")
        return report.to_dict()

    try:
        from stravalib import Client
    except ImportError:
        report.errors.append("stravalib not installed")
        return report.to_dict()

    client = Client(access_token=token)

    after = since if since is not None else sync_row.last_sync_at
    try:
        activities = client.get_activities(after=after, limit=None)
        count = 0
        polylines_new: dict[str, list] = {}  # {source_id: [[lat, lon], ...]}
        for act in activities:
            source_id = str(getattr(act, "id", ""))
            if not source_id:
                report.skipped += 1
                continue
            payload = _strava_activity_to_payload(act)

            # Descriptions are only on DetailedActivity. One extra API
            # call per activity is cheap on incremental syncs (typically
            # a handful per day); the original bulk backfill stays free
            # because CSV export gives us descriptions + FIT files.
            if not payload.get("description"):
                try:
                    detail = client.get_activity(int(source_id))
                    payload["description"] = getattr(detail, "description", None)
                except Exception as e:
                    logger.debug("detail fetch failed for %s: %s", source_id, e)

            # Capture the encoded polyline for later sidecar write.
            encoded = payload.pop("_summary_polyline", None)

            try:
                row, inserted = upsert_from_strava_record(
                    session,
                    user_id=user_id,
                    source_id=source_id,
                    payload=payload,
                    ingested_from="strava_api",
                )

                # If a real description just arrived and the row still
                # carries a backfill-written description override, clear
                # the override so the real one surfaces. Also write the
                # payload description to the raw column — the upsert
                # above skipped it because 'description' was treated as
                # a locked override field.
                if payload.get("description") and row.manual_overrides:
                    ov = dict(row.manual_overrides)
                    if "_program_day" in ov and ov.get("description"):
                        ov.pop("description", None)
                        row.manual_overrides = ov
                        row.description = payload["description"]

                if encoded:
                    decoded = _decode_polyline(encoded)
                    if len(decoded) >= 3:
                        polylines_new[source_id] = decoded

                # Per-second streams. CSV-import rows already have a .fit.gz
                # on disk; API-only rows need this blob to power HR zones,
                # best-effort splits, the per-card HR chart, etc. Skip if
                # the row already has one (lets backfill be idempotent).
                if not row.streams_blob:
                    try:
                        from ...streams import (
                            fetch_streams_from_strava, serialize_streams,
                        )
                        streams = fetch_streams_from_strava(
                            client, int(source_id)
                        )
                        if streams:
                            row.streams_blob = serialize_streams(streams)
                    except Exception:
                        # Don't let a stream-fetch glitch (rate limit, GPS-less
                        # activity, etc.) abort the activity upsert.
                        logger.debug(
                            "stream fetch skipped for %s", source_id, exc_info=True
                        )

                if inserted:
                    report.inserted += 1
                else:
                    report.updated += 1
                count += 1
                # Soft cap per sync to avoid marathon sessions
                if count >= 500:
                    logger.warning("Sync cap hit at %d — run again to continue", count)
                    break
            except Exception as e:
                logger.exception("upsert failed for activity %s", source_id)
                report.errors.append(f"{source_id}: {e}")

        # Merge newly captured polylines into ~/.meron/route_index.json so
        # mini-maps for API-synced runs (no FIT file) render. Keyed by
        # ``strava:<id>`` to avoid colliding with FIT filenames.
        if polylines_new:
            _merge_route_index(polylines_new)

        sync_row.last_sync_at = datetime.now(timezone.utc)
    except Exception as e:
        logger.exception("Strava API sync failed")
        report.errors.append(str(e))
        # Detect rate limit (stravalib raises RateLimitExceeded)
        if "rate" in str(e).lower():
            sync_row.last_rate_limit_hit = datetime.now(timezone.utc)

    return report.to_dict()


def backfill(user_id: int, session: Session, since: Optional[datetime] = None) -> dict:
    """One-shot fetch from a specified start date. Use after first OAuth connect."""
    sync_row = session.scalar(
        select(SyncState).where(
            SyncState.user_id == user_id,
            SyncState.provider == "strava",
        )
    )
    if sync_row is not None:
        sync_row.last_sync_at = since
    return sync_incremental(user_id, session)


# Re-export for callers that want a stable import path
__all__ = ["sync_incremental", "backfill", "load_tokens"]
