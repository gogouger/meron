"""Pydantic validation on the CRUD endpoints.

Every POST/PATCH goes through ActivityCreate / ActivityPatch. We verify
the happy path, missing-required-field → 400, wrong-type → 400, and
unknown-field → silently dropped (so old clients don't break).
"""

from flask import Flask

from strava_analytics.api import register_api
from strava_analytics.db import init_engine, session_scope
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.models import Activity, SyncState


def _make_client(_isolated_db) -> tuple:
    init_engine()
    run_migrations()
    from strava_analytics.web import data as data_mod
    data_mod.init(None)
    app = Flask("test")
    register_api(app)
    return app.test_client()


def _write_key() -> str:
    with session_scope() as s:
        row = s.query(SyncState).filter(
            SyncState.user_id == 1, SyncState.provider == "strava",
        ).first()
        return row.api_key_write


def test_missing_required_type_returns_400(isolated_db):
    client = _make_client(isolated_db)
    resp = client.post("/api/activities",
                       headers={"X-API-Key": _write_key()},
                       json={"start_time": "2025-04-10T09:00:00"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"]["code"] == "validation_error"


def test_missing_required_start_time_returns_400(isolated_db):
    client = _make_client(isolated_db)
    resp = client.post("/api/activities",
                       headers={"X-API-Key": _write_key()},
                       json={"type": "Run"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "validation_error"


def test_wrong_type_returns_400(isolated_db):
    client = _make_client(isolated_db)
    resp = client.post("/api/activities",
                       headers={"X-API-Key": _write_key()},
                       json={"type": "Run",
                             "start_time": "2025-04-10T09:00:00",
                             "distance_m": "not-a-number"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "validation_error"


def test_unknown_field_is_silently_dropped(isolated_db):
    client = _make_client(isolated_db)
    resp = client.post("/api/activities",
                       headers={"X-API-Key": _write_key()},
                       json={"type": "Run",
                             "start_time": "2025-04-10T09:00:00",
                             "this_field_does_not_exist": 42,
                             "name": "kept"})
    assert resp.status_code == 201
    body = resp.get_json()
    with session_scope() as s:
        act = s.get(Activity, body["id"])
        assert act.name == "kept"


def test_negative_hr_rejected(isolated_db):
    client = _make_client(isolated_db)
    resp = client.post("/api/activities",
                       headers={"X-API-Key": _write_key()},
                       json={"type": "Run",
                             "start_time": "2025-04-10T09:00:00",
                             "avg_hr": -5})
    assert resp.status_code == 400


def test_patch_empty_body_returns_400(isolated_db):
    client = _make_client(isolated_db)
    # Create first
    resp = client.post("/api/activities",
                       headers={"X-API-Key": _write_key()},
                       json={"type": "Run", "start_time": "2025-04-10T09:00:00"})
    act_id = resp.get_json()["id"]
    # Patch with no editable fields
    resp2 = client.patch(f"/api/activities/{act_id}",
                         headers={"X-API-Key": _write_key()},
                         json={})
    assert resp2.status_code == 400


def test_get_missing_activity_returns_404(isolated_db):
    client = _make_client(isolated_db)
    resp = client.get("/api/activities/99999",
                      headers={"X-API-Key": _write_key()})
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"
