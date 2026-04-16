"""Strava API sync with a mocked stravalib.Client."""

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from strava_analytics.db import get_session_factory, init_engine, session_scope
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.models import Activity, SyncState


def _fake_strava_activity(aid: int, name: str, minutes: float = 30,
                          distance_m: float = 5000):
    """Build a minimal stravalib-shaped activity object."""
    return SimpleNamespace(
        id=aid,
        name=name,
        type="Run",
        sport_type="Run",
        start_date=datetime(2025, 4, 1, 9, 0, tzinfo=timezone.utc),
        start_date_local=datetime(2025, 4, 1, 9, 0),
        elapsed_time=minutes * 60,
        moving_time=minutes * 60,
        distance=distance_m,
        max_speed=3.5,
        average_speed=2.8,
        total_elevation_gain=50,
        elev_low=None,
        elev_high=None,
        max_heartrate=170,
        average_heartrate=150,
        average_watts=None,
        calories=400,
        average_temp=12,
        gear_id=None,
        description=None,
    )


def test_sync_inserts_new_activity(isolated_db, monkeypatch):
    init_engine()
    run_migrations()

    # Seed a sync_state row with fake refresh token
    with session_scope() as s:
        row = s.query(SyncState).filter(
            SyncState.user_id == 1, SyncState.provider == "strava",
        ).first()
        row.access_token = "dummy"
        row.refresh_token = "dummy"
        row.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=2)

    # Mock refresh + stravalib client
    from strava_analytics.auth import strava_oauth as oauth_mod
    from strava_analytics.services.ingestion import strava_api as sa_mod

    # Patch the binding inside strava_api (import captured at module load)
    monkeypatch.setattr(
        "strava_analytics.services.ingestion.strava_api.refresh_if_needed",
        lambda user_id, session: "fake_access_token",
    )

    class FakeClient:
        def __init__(self, access_token=None):
            pass
        def get_activities(self, after=None, limit=None):
            return iter([
                _fake_strava_activity(aid=9001, name="API activity 1"),
                _fake_strava_activity(aid=9002, name="API activity 2"),
            ])

    # Patch the Client class that strava_api imports lazily
    monkeypatch.setattr("stravalib.Client", FakeClient)

    with session_scope() as s:
        report = sa_mod.sync_incremental(user_id=1, session=s)

    assert report["inserted"] == 2
    assert report["errors"] == []

    with session_scope() as s:
        rows = s.query(Activity).filter(
            Activity.source == "strava", Activity.source_id.in_(["9001", "9002"])
        ).all()
        assert len(rows) == 2
        names = {r.name for r in rows}
        assert "API activity 1" in names
        assert "API activity 2" in names

        for r in rows:
            assert "strava_api" in (r.provenance or {}).get("ingested_from", [])


def test_sync_dedupes_against_csv_ingest(export_dir, isolated_db, monkeypatch):
    """If a Strava API sync returns an activity already ingested from CSV,
    it must update (not duplicate) the existing row.
    """
    init_engine()
    run_migrations()

    # First ingest the full CSV export
    from strava_analytics.services.ingestion.strava_csv import ingest_bulk
    with session_scope() as s:
        ingest_bulk(export_dir, user_id=1, session=s)

    # Grab a real source_id that already exists
    with session_scope() as s:
        row = s.query(Activity).first()
        existing_source_id = int(row.source_id)

    # Seed sync_state tokens
    with session_scope() as s:
        st = s.query(SyncState).filter(
            SyncState.user_id == 1, SyncState.provider == "strava",
        ).first()
        st.access_token = "dummy"
        st.refresh_token = "dummy"
        st.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=2)

    from strava_analytics.auth import strava_oauth as oauth_mod
    from strava_analytics.services.ingestion import strava_api as sa_mod

    monkeypatch.setattr(
        "strava_analytics.services.ingestion.strava_api.refresh_if_needed",
        lambda user_id, session: "fake",
    )

    class FakeClient:
        def __init__(self, access_token=None):
            pass
        def get_activities(self, after=None, limit=None):
            return iter([_fake_strava_activity(
                aid=existing_source_id, name="Should not dup"
            )])

    monkeypatch.setattr("stravalib.Client", FakeClient)

    with session_scope() as s:
        before_count = s.query(Activity).count()

    with session_scope() as s:
        report = sa_mod.sync_incremental(user_id=1, session=s)

    with session_scope() as s:
        after_count = s.query(Activity).count()

    assert report["updated"] == 1
    assert report["inserted"] == 0
    assert after_count == before_count  # no duplicate row

    with session_scope() as s:
        updated = s.query(Activity).filter(
            Activity.source == "strava",
            Activity.source_id == str(existing_source_id),
        ).first()
        # Both csv and api should now be in provenance
        sources = (updated.provenance or {}).get("ingested_from", [])
        assert "strava_csv" in sources
        assert "strava_api" in sources
