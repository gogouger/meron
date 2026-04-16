"""End-to-end CRUD tests via the Flask test client."""

import json
from datetime import datetime

from flask import Flask

from strava_analytics.db import get_session_factory, init_engine, session_scope
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.models import Activity, SyncState
from strava_analytics.web.api import register_api


def _make_client(isolated_db):
    """Create a minimal Flask app with our API registered + init MERON data."""
    init_engine()
    run_migrations()

    # Initialize data module so register_api's auth middleware can read config
    from strava_analytics.web import data as data_mod
    data_mod.init(None)

    app = Flask("test")
    register_api(app.server if hasattr(app, "server") else app)
    return app.test_client()


def _write_key() -> str:
    with session_scope() as s:
        row = s.query(SyncState).filter(
            SyncState.user_id == 1, SyncState.provider == "strava",
        ).first()
        return row.api_key_write


def test_post_creates_manual_activity(isolated_db):
    client = _make_client(isolated_db)
    headers = {"X-API-Key": _write_key()}

    resp = client.post("/api/activities", headers=headers, json={
        "type": "Run",
        "start_time": "2025-04-10T09:00:00",
        "moving_time_s": 1800,
        "distance_m": 5000,
        "name": "Test run",
    })
    assert resp.status_code == 201, resp.data
    body = resp.get_json()
    assert "id" in body

    # Verify it landed
    with session_scope() as s:
        act = s.get(Activity, body["id"])
        assert act is not None
        assert act.source == "manual"
        assert act.name == "Test run"
        assert act.deleted_at is None


def test_patch_updates_activity(migrated_db):
    client = _make_client(migrated_db)
    headers = {"X-API-Key": _write_key()}

    # Grab any existing activity id
    with session_scope() as s:
        act_id = s.query(Activity.id).first()[0]

    resp = client.patch(f"/api/activities/{act_id}",
                        headers=headers, json={"name": "Patched name"})
    assert resp.status_code == 200
    assert "name" in resp.get_json()["updated"]

    # Strava row → goes into manual_overrides
    with session_scope() as s:
        act = s.get(Activity, act_id)
        if act.source == "manual":
            assert act.name == "Patched name"
        else:
            assert (act.manual_overrides or {}).get("name") == "Patched name"


def test_delete_soft_deletes(migrated_db):
    client = _make_client(migrated_db)
    headers = {"X-API-Key": _write_key()}

    with session_scope() as s:
        act_id = s.query(Activity.id).first()[0]

    resp = client.delete(f"/api/activities/{act_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] is True

    with session_scope() as s:
        act = s.get(Activity, act_id)
        assert act.deleted_at is not None


def test_unauthorized_write_rejected(isolated_db):
    client = _make_client(isolated_db)
    resp = client.post("/api/activities", json={"type": "Run",
                                                 "start_time": "2025-04-10T09:00:00"})
    assert resp.status_code == 401


def test_read_key_cannot_write(isolated_db):
    client = _make_client(isolated_db)
    with session_scope() as s:
        row = s.query(SyncState).filter(
            SyncState.user_id == 1, SyncState.provider == "strava",
        ).first()
        read_key = row.api_key_read
    resp = client.post("/api/activities", headers={"X-API-Key": read_key},
                       json={"type": "Run", "start_time": "2025-04-10T09:00"})
    assert resp.status_code == 401


def test_read_endpoints_accessible(migrated_db):
    client = _make_client(migrated_db)
    headers = {"X-API-Key": _write_key()}
    r = client.get("/api/stats", headers=headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body["total_activities"] > 0
