"""Tests for bulk CSV ingest + idempotency."""

from strava_analytics.db import get_session_factory, init_engine
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.models import Activity
from strava_analytics.services.ingestion.strava_csv import ingest_bulk


def test_bulk_ingest_inserts_activities(export_dir, isolated_db):
    init_engine()
    run_migrations()
    factory = get_session_factory()
    with factory() as s:
        report = ingest_bulk(export_dir, user_id=1, session=s)
        s.commit()
    assert report["inserted"] > 0
    assert report["errors"] == []

    with factory() as s:
        count = s.query(Activity).count()
    assert count == report["inserted"]


def test_bulk_ingest_idempotent(export_dir, isolated_db):
    init_engine()
    run_migrations()
    factory = get_session_factory()

    with factory() as s:
        first = ingest_bulk(export_dir, user_id=1, session=s)
        s.commit()
    with factory() as s:
        second = ingest_bulk(export_dir, user_id=1, session=s)
        s.commit()

    # Second ingest: every row should be an UPDATE, not an insert
    assert second["inserted"] == 0
    assert second["updated"] == first["inserted"]

    # Row count is unchanged
    with factory() as s:
        count = s.query(Activity).count()
    assert count == first["inserted"]


def test_ingest_records_provenance(export_dir, isolated_db):
    init_engine()
    run_migrations()
    factory = get_session_factory()
    with factory() as s:
        ingest_bulk(export_dir, user_id=1, session=s)
        s.commit()
    with factory() as s:
        act = s.query(Activity).first()
        assert act.provenance is not None
        assert "strava_csv" in act.provenance.get("ingested_from", [])
        assert act.source == "strava"
        assert act.source_id is not None
