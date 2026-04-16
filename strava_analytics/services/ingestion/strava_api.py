"""Strava API incremental sync via stravalib.

Pulls activities since `sync_state.last_sync_at`, upserts them into the DB,
and updates the cursor. Rate-limit aware (Strava: 100/15min, 1000/day).
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth.strava_oauth import load_tokens, refresh_if_needed
from ...db.models import SyncState
from ...db.repository import upsert_from_strava_record
from . import IngestReport

logger = logging.getLogger(__name__)


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

    return {
        "start_time": getattr(act, "start_date_local", None) or getattr(act, "start_date", None),
        "name": getattr(act, "name", None),
        "type": str(getattr(act, "type", "") or getattr(act, "sport_type", "") or ""),
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
    }


def sync_incremental(user_id: int, session: Session) -> dict:
    """Fetch new Strava activities since last sync and upsert them.

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

    after = sync_row.last_sync_at
    try:
        activities = client.get_activities(after=after, limit=None)
        count = 0
        for act in activities:
            source_id = str(getattr(act, "id", ""))
            if not source_id:
                report.skipped += 1
                continue
            payload = _strava_activity_to_payload(act)
            try:
                _, inserted = upsert_from_strava_record(
                    session,
                    user_id=user_id,
                    source_id=source_id,
                    payload=payload,
                    ingested_from="strava_api",
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
