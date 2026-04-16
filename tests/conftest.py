"""Shared pytest fixtures: isolated DB per test."""

import os
from pathlib import Path

import pytest

EXPORT_DIR = Path("/Users/gordongouger/Downloads/export_139099153")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at a scratch sqlite file under tmp_path."""
    db_path = tmp_path / "meron.db"
    monkeypatch.setenv("MERON_DB_PATH", str(db_path))

    # Reset the module-level engine/session factory so init_engine() picks up
    # the new path.
    from strava_analytics import db as db_pkg
    db_pkg._engine = None
    db_pkg._SessionFactory = None

    # Clear enrichment cache between tests
    from strava_analytics.services import enrichment_service
    enrichment_service._cache.clear()

    # Clear data.py module state
    from strava_analytics.web import data as data_mod
    data_mod._profile = None
    data_mod._athlete_config = None
    data_mod._best_efforts = None
    data_mod._export_dir = None

    yield db_path

    db_pkg._engine = None
    db_pkg._SessionFactory = None


@pytest.fixture
def export_dir():
    if not EXPORT_DIR.exists():
        pytest.skip(f"No Strava export available at {EXPORT_DIR}")
    return EXPORT_DIR


@pytest.fixture
def migrated_db(export_dir, isolated_db):
    """A fully-migrated DB containing the example Strava export."""
    from strava_analytics.db import init_engine
    from strava_analytics.db.migrations import run_migrations, migration_002_backfill_bulk
    init_engine()
    run_migrations()
    migration_002_backfill_bulk(export_dir)
    return isolated_db
