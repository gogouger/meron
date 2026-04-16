"""The DB-backed enrichment path must produce the same numbers as the
legacy CSV-only loader+enrich pipeline.

This is the key regression check: no dashboard number may drift as a
result of the migration.
"""

import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from strava_analytics.db import get_session_factory, init_engine, meron_dir
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.repository import load_raw_activities_df
from strava_analytics.enrichment import enrich
from strava_analytics.loader import load_activities
from strava_analytics.services.ingestion.strava_csv import ingest_bulk


_ATHLETE_CFG = {"max_hr": 200, "hr_zones_pct": [60, 70, 80, 90]}


def _copy_fits(src_dir: Path, dst_dir: Path) -> None:
    src = src_dir / "activities"
    dst = dst_dir / "fit"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        target = dst / f.name
        if not target.exists():
            shutil.copy2(f, target)


def test_enrichment_parity(export_dir, isolated_db, tmp_path):
    # 1. Legacy path: loader → enrich
    old_raw = load_activities(export_dir)
    old = enrich(old_raw, athlete_config=_ATHLETE_CFG, export_dir=export_dir)

    # 2. New path: ingest → repository → enrich
    init_engine()
    run_migrations()
    factory = get_session_factory()
    with factory() as s:
        ingest_bulk(export_dir, user_id=1, session=s)
        s.commit()
    _copy_fits(Path(export_dir), meron_dir())

    with factory() as s:
        new_raw = load_raw_activities_df(1, s)

    new = enrich(new_raw, athlete_config=_ATHLETE_CFG, export_dir=meron_dir())

    # Row count
    assert len(new) == len(old)

    # Core aggregates (insensitive to ordering)
    assert abs(new["distance_mi"].sum() - old["distance_mi"].sum()) < 0.5
    assert (new["calories"].sum() == old["calories"].sum()) or (
        abs(new["calories"].sum() - old["calories"].sum()) < 1
    )

    # Count per activity type
    old_counts = old["type"].value_counts().sort_index()
    new_counts = new["type"].value_counts().sort_index()
    pd.testing.assert_series_equal(new_counts, old_counts, check_names=False)

    # Tail-state fatigue metrics (last non-null row)
    for col in ("acute_load_7d", "chronic_load_28d", "freshness"):
        if col not in old.columns or col not in new.columns:
            continue
        old_tail = old[col].dropna().iloc[-1]
        new_tail = new[col].dropna().iloc[-1]
        assert np.isclose(old_tail, new_tail, atol=0.5), (
            f"{col}: old={old_tail}, new={new_tail}"
        )
