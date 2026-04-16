"""Manual-override fields must not be clobbered on re-ingest."""

from strava_analytics.db import get_session_factory, init_engine, session_scope
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.models import Activity
from strava_analytics.db.repository import patch_activity
from strava_analytics.services.ingestion.strava_csv import ingest_bulk


def test_override_survives_reingest(export_dir, isolated_db):
    init_engine()
    run_migrations()
    factory = get_session_factory()

    with factory() as s:
        ingest_bulk(export_dir, user_id=1, session=s)
        s.commit()

    # Pick the first activity and override its name.
    with factory() as s:
        act = s.query(Activity).first()
        act_id = act.id
        original_name = act.name
        patch_activity(session=s, activity_id=act_id, patch={"name": "OVERRIDDEN"})
        s.commit()

    # Re-ingest the same export — name should remain overridden in
    # manual_overrides, raw `name` column may revert but override wins on read.
    with factory() as s:
        ingest_bulk(export_dir, user_id=1, session=s)
        s.commit()

    with factory() as s:
        act = s.get(Activity, act_id)
        # Raw column may or may not match original, but override must persist
        assert (act.manual_overrides or {}).get("name") == "OVERRIDDEN"

    # And the repository-driven DataFrame should reflect the override
    from strava_analytics.db.repository import load_raw_activities_df
    with factory() as s:
        df = load_raw_activities_df(1, s)
    row = df[df["_id"] == act_id].iloc[0]
    assert row["name"] == "OVERRIDDEN"
