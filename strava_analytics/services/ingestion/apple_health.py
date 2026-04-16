"""Apple Health import — stub for future implementation.

Extension point:
    Apple Health exports a zip containing `export.xml`. Each `<Workout>`
    element corresponds to an activity. When this is implemented, parse
    workouts via streaming `xml.etree.ElementTree.iterparse` (don't add
    `lxml` — stdlib is enough), map each to our Activity model with
    `source='apple_health'` + `source_id = HKWorkout UUID`, and call
    `upsert_from_apple_health_record()` (parallel to the Strava one).
"""

from pathlib import Path

from sqlalchemy.orm import Session

from . import IngestReport


def ingest_export(xml_path: str | Path, user_id: int, session: Session) -> dict:
    """Apple Health import (not yet implemented)."""
    report = IngestReport()
    report.errors.append(
        "Apple Health ingest is not yet implemented. "
        "See strava_analytics/services/ingestion/apple_health.py for the "
        "extension point and planned schema."
    )
    return report.to_dict()
