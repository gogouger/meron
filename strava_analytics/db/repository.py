"""Repository layer — translates between SQLAlchemy rows and pandas DataFrames.

Produces a DataFrame with exactly the columns that today's
`loader.load_activities()` returns, so the existing `enrich()` pipeline
needs zero changes.
"""

from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RAW_ACTIVITY_COLUMNS, Activity


# Fields that are merged from `manual_overrides` at read time (strava rows).
_OVERRIDABLE_FIELDS = set(RAW_ACTIVITY_COLUMNS)


def _apply_overrides(row: Activity) -> dict:
    """Return a flat dict of raw fields, with manual_overrides layered on top."""
    base = {c: getattr(row, c) for c in RAW_ACTIVITY_COLUMNS}
    if row.manual_overrides:
        for k, v in row.manual_overrides.items():
            if k in _OVERRIDABLE_FIELDS:
                base[k] = v
    base["_id"] = row.id
    base["_source"] = row.source
    return base


def load_raw_activities_df(user_id: int, session: Session) -> pd.DataFrame:
    """Load all non-deleted activities as a DataFrame shaped like loader output."""
    q = (
        select(Activity)
        .where(Activity.user_id == user_id, Activity.deleted_at.is_(None))
    )
    rows = session.scalars(q).all()
    if not rows:
        return _empty_df()

    records = [_apply_overrides(r) for r in rows]
    df = pd.DataFrame.from_records(records)

    # Rename start_time -> date (loader.py output convention).
    df = df.rename(columns={"start_time": "date"})

    # Match loader.py handling: drop tz (localize to UTC, convert to the
    # user's local tz, then drop tz for pandas compat).
    if not df.empty and "date" in df.columns:
        from ..config import default_tz_name
        df["date"] = pd.to_datetime(df["date"])
        # Stored as UTC if tz-aware; naive values we assume are already local.
        if df["date"].dt.tz is not None:
            df["date"] = df["date"].dt.tz_convert(default_tz_name()).dt.tz_localize(None)

    # activity_id compatibility: downstream code (notably
    # route_matching.build_route_index + lifting_program mapping) keys off
    # activity_id. Use source_id when available, else the DB id.
    source_ids = []
    for r in rows:
        source_ids.append(int(r.source_id) if r.source_id and r.source_id.isdigit() else r.id)
    df["activity_id"] = source_ids

    # Numeric coerce, matching loader.py:100-103
    _NUMERIC = [
        "elapsed_time_s", "moving_time_s", "distance_m", "max_speed_ms",
        "avg_speed_ms", "elevation_gain_m", "elevation_loss_m",
        "elevation_low_m", "elevation_high_m", "max_hr", "avg_hr",
        "avg_watts", "calories", "relative_effort", "grade_adj_distance_m",
        "weather_temp_c", "total_steps", "training_load", "intensity",
    ]
    for col in _NUMERIC:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Derived columns exactly as loader.py:105-128
    df["weather_temp_f"] = df["weather_temp_c"] * 9 / 5 + 32
    df["distance_mi"] = df["distance_m"] / 1609.344
    df["distance_km"] = df["distance_m"] / 1000.0
    df["elevation_gain_ft"] = df["elevation_gain_m"] * 3.28084
    df["moving_time_min"] = df["moving_time_s"] / 60.0
    df["elapsed_time_min"] = df["elapsed_time_s"] / 60.0

    mask = df["distance_mi"] > 0
    df.loc[mask, "pace_min_per_mi"] = (
        df.loc[mask, "moving_time_min"] / df.loc[mask, "distance_mi"]
    )
    # Ensure the column exists even if no row satisfies the mask.
    if "pace_min_per_mi" not in df.columns:
        df["pace_min_per_mi"] = pd.NA

    # Sort by date ascending (matches loader.py:122)
    df = df.sort_values("date").reset_index(drop=True)

    # Period columns
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.to_period("M")
    df["week"] = df["date"].dt.to_period("W")
    df["day_of_week"] = df["date"].dt.day_name()

    return df


def _empty_df() -> pd.DataFrame:
    cols = ["activity_id", "date"] + [c for c in RAW_ACTIVITY_COLUMNS if c != "start_time"]
    return pd.DataFrame(columns=cols)


# ─── Writes ──────────────────────────────────────────────────────────


def upsert_from_strava_record(
    session: Session,
    *,
    user_id: int,
    source_id: str,
    payload: dict,
    ingested_from: str,
) -> tuple[Activity, bool]:
    """Insert-or-update one Strava activity. Returns (row, inserted)."""
    existing = session.scalar(
        select(Activity).where(
            Activity.user_id == user_id,
            Activity.source == "strava",
            Activity.source_id == source_id,
        )
    )
    inserted = False
    if existing is None:
        existing = Activity(
            user_id=user_id,
            source="strava",
            source_id=source_id,
            provenance={
                "ingested_from": [ingested_from],
                "first_seen": _now_iso(),
                "last_synced": _now_iso(),
            },
        )
        for k, v in payload.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
        session.add(existing)
        inserted = True
    else:
        # SQLAlchemy JSON columns don't track in-place mutations; build a
        # fresh dict so the change is detected on flush.
        prev = existing.provenance or {}
        ingested_list = list(prev.get("ingested_from", []))
        if ingested_from not in ingested_list:
            ingested_list.append(ingested_from)
        existing.provenance = {
            **prev,
            "ingested_from": ingested_list,
            "last_synced": _now_iso(),
        }
        # Never overwrite fields present in manual_overrides.
        locked = set((existing.manual_overrides or {}).keys())
        for k, v in payload.items():
            if k in locked:
                continue
            if hasattr(existing, k):
                setattr(existing, k, v)
    return existing, inserted


def create_manual_activity(session: Session, *, user_id: int, payload: dict) -> Activity:
    """Create a user-entered activity (source='manual')."""
    act = Activity(
        user_id=user_id,
        source="manual",
        source_id=None,
        provenance={
            "ingested_from": ["manual"],
            "first_seen": _now_iso(),
            "last_synced": _now_iso(),
        },
    )
    for k, v in payload.items():
        if hasattr(act, k):
            setattr(act, k, v)
    session.add(act)
    session.flush()
    return act


def patch_activity(session: Session, *, activity_id: int, patch: dict) -> Activity | None:
    """Apply a partial update to an activity.

    For `source='manual'` rows: mutate raw columns directly.
    For other sources: merge into `manual_overrides` (field-level override).
    """
    act = session.get(Activity, activity_id)
    if act is None or act.deleted_at is not None:
        return None
    if act.source == "manual":
        for k, v in patch.items():
            if hasattr(act, k):
                setattr(act, k, v)
    else:
        # Fresh dict so SQLAlchemy detects the JSON mutation.
        overrides = dict(act.manual_overrides or {})
        for k, v in patch.items():
            if k in _OVERRIDABLE_FIELDS:
                overrides[k] = v
        act.manual_overrides = overrides
    # Touch updated_at so enrichment cache invalidates.
    act.updated_at = datetime.now(timezone.utc)
    return act


def soft_delete_activity(session: Session, *, activity_id: int) -> bool:
    act = session.get(Activity, activity_id)
    if act is None or act.deleted_at is not None:
        return False
    act.deleted_at = datetime.now(timezone.utc)
    return True


def activity_max_updated_at(session: Session, user_id: int) -> datetime | None:
    from sqlalchemy import func
    result = session.scalar(
        select(func.max(Activity.updated_at)).where(Activity.user_id == user_id)
    )
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iter_activities(session: Session, user_id: int) -> Iterable[Activity]:
    q = select(Activity).where(
        Activity.user_id == user_id, Activity.deleted_at.is_(None)
    )
    yield from session.scalars(q)
