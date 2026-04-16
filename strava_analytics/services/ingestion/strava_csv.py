"""Strava bulk-export CSV ingestion.

Reuses `loader.load_activities()` to parse the export dir, then UPSERTs
rows keyed by (user_id, 'strava', source_id=activity_id). FIT files are
copied into `~/.meron/fit/` so the existing `_compute_zone_times` logic
can find them post-migration.
"""

import logging
import shutil
from pathlib import Path

import pandas as pd

from ...db import meron_dir
from ...db.repository import upsert_from_strava_record
from ...loader import load_activities
from . import IngestReport

logger = logging.getLogger(__name__)


# Raw DataFrame columns from loader.load_activities that map 1:1 to model fields.
# Note loader uses "date" for start_time.
_LOADER_TO_MODEL = {
    "date": "start_time",
    "name": "name",
    "type": "type",
    "description": "description",
    "gear": "gear",
    "filename": "filename",
    "elapsed_time_s": "elapsed_time_s",
    "moving_time_s": "moving_time_s",
    "distance_m": "distance_m",
    "max_speed_ms": "max_speed_ms",
    "avg_speed_ms": "avg_speed_ms",
    "elevation_gain_m": "elevation_gain_m",
    "elevation_loss_m": "elevation_loss_m",
    "elevation_low_m": "elevation_low_m",
    "elevation_high_m": "elevation_high_m",
    "max_hr": "max_hr",
    "avg_hr": "avg_hr",
    "avg_watts": "avg_watts",
    "calories": "calories",
    "relative_effort": "relative_effort",
    "grade_adj_distance_m": "grade_adj_distance_m",
    "weather_condition": "weather_condition",
    "weather_temp_c": "weather_temp_c",
    "total_steps": "total_steps",
    "training_load": "training_load",
    "intensity": "intensity",
    "competition": "competition",
    "strava_with_kid": "strava_with_kid",
}


def _clean(val):
    """Turn pandas NaN → None; everything else passes through."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if pd.isna(val) if not isinstance(val, (list, dict)) else False:
        return None
    return val


def _copy_fit_files(export_dir: Path) -> None:
    """Copy FIT files from the export dir's activities/ subdir into ~/.meron/fit/."""
    src_dir = export_dir / "activities"
    if not src_dir.exists():
        return
    dst_dir = meron_dir() / "fit"
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in src_dir.iterdir():
        if not f.is_file():
            continue
        dst = dst_dir / f.name
        if dst.exists():
            continue
        try:
            shutil.copy2(f, dst)
            copied += 1
        except Exception as e:
            logger.warning("Failed to copy FIT %s: %s", f.name, e)
    if copied:
        logger.info("Copied %d FIT files to %s", copied, dst_dir)


def ingest_bulk(export_dir: str | Path, user_id: int, session) -> dict:
    """Ingest a Strava bulk export directory.

    Idempotent: second ingest of the same export updates `last_synced` only,
    no row duplication.
    """
    export_dir = Path(export_dir).expanduser()
    report = IngestReport()

    try:
        df = load_activities(export_dir)
    except FileNotFoundError as e:
        report.errors.append(str(e))
        return report.to_dict()

    for _, row in df.iterrows():
        activity_id = row.get("activity_id")
        if pd.isna(activity_id):
            report.skipped += 1
            continue
        source_id = str(int(activity_id))
        payload = {
            model_col: _clean(row.get(loader_col))
            for loader_col, model_col in _LOADER_TO_MODEL.items()
            if loader_col in row.index
        }
        try:
            _, inserted = upsert_from_strava_record(
                session,
                user_id=user_id,
                source_id=source_id,
                payload=payload,
                ingested_from="strava_csv",
            )
            if inserted:
                report.inserted += 1
            else:
                report.updated += 1
        except Exception as e:
            logger.exception("Failed to upsert activity %s", source_id)
            report.errors.append(f"{source_id}: {e}")

    # Copy FIT files alongside activity ingest (so zone-time enrichment works)
    try:
        _copy_fit_files(export_dir)
    except Exception as e:
        logger.warning("FIT copy failed: %s", e)
        report.errors.append(f"fit_copy: {e}")

    logger.info("Bulk ingest: %s", report.to_dict())
    return report.to_dict()
