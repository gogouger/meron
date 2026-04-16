"""Cursor pagination on /api/activities/feed."""

from datetime import datetime, timedelta

import pytest
from flask import Flask

from strava_analytics.api import register_api
from strava_analytics.db import init_engine, session_scope
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.models import Activity, SyncState
from strava_analytics.db.repository import create_manual_activity
from strava_analytics.services.enrichment_service import invalidate_cache


@pytest.fixture(autouse=True)
def _schema(isolated_db):
    init_engine()
    run_migrations()
    from strava_analytics.web import data as data_mod
    data_mod.init(None)


def _seed_activities(n: int) -> list[int]:
    """Insert ``n`` manual runs, one per day, return their ids.

    Each run has slightly varied distance / duration / HR so the
    enrichment pipeline's fatigue binning has real variance to work with.
    """
    ids: list[int] = []
    with session_scope() as session:
        for i in range(n):
            act = create_manual_activity(
                session,
                user_id=1,
                payload={
                    "type": "Run",
                    "start_time": datetime(2025, 1, 1) + timedelta(days=i),
                    "name": f"Run #{i}",
                    "moving_time_s": 1800 + i * 30,
                    "distance_m": 5000 + i * 100,
                    "avg_hr": 140 + (i % 20),
                    "max_hr": 170 + (i % 10),
                    "elevation_gain_m": 30 + i,
                },
            )
            ids.append(act.id)
    invalidate_cache()
    from strava_analytics.web import data as data_mod
    data_mod.reload()
    return ids


def _client() -> Flask:
    app = Flask("pg_test")
    register_api(app)
    return app.test_client()


def _read_key() -> str:
    with session_scope() as s:
        row = s.query(SyncState).filter_by(user_id=1, provider="strava").first()
        return row.api_key_read


def test_feed_returns_items_and_cursor(isolated_db):
    _seed_activities(25)
    resp = _client().get("/api/activities/feed?limit=10",
                         headers={"X-API-Key": _read_key()})
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["items"]) == 10
    assert body["next_cursor"] is not None
    # Newest first.
    dates = [i["date"] for i in body["items"]]
    assert dates == sorted(dates, reverse=True)


def test_feed_paginates_to_end(isolated_db):
    _seed_activities(25)
    client = _client()
    headers = {"X-API-Key": _read_key()}
    seen_ids: set[int] = set()
    cursor = None
    pages = 0
    while True:
        url = "/api/activities/feed?limit=7"
        if cursor:
            url += f"&cursor={cursor}"
        resp = client.get(url, headers=headers)
        body = resp.get_json()
        for item in body["items"]:
            seen_ids.add(item["_id"])
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
        assert pages < 10, "should terminate well before this"
    # Every seeded activity is returned exactly once (set dedup confirms).
    assert len(seen_ids) == 25


def test_feed_without_cursor_starts_from_newest(isolated_db):
    ids = _seed_activities(5)
    resp = _client().get("/api/activities/feed",
                         headers={"X-API-Key": _read_key()})
    body = resp.get_json()
    # First item should be the newest — ids[-1] (Jan 5 run).
    assert body["items"][0]["_id"] == ids[-1]


def test_feed_limit_capped_at_100(isolated_db):
    _seed_activities(5)
    resp = _client().get("/api/activities/feed?limit=500",
                         headers={"X-API-Key": _read_key()})
    assert resp.status_code == 200
    assert len(resp.get_json()["items"]) <= 100


def test_invalid_cursor_returns_empty_page(isolated_db):
    _seed_activities(3)
    resp = _client().get("/api/activities/feed?cursor=garbage",
                         headers={"X-API-Key": _read_key()})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == []


def test_feed_empty_when_no_activities(isolated_db):
    resp = _client().get("/api/activities/feed",
                         headers={"X-API-Key": _read_key()})
    body = resp.get_json()
    assert body["items"] == []
    assert body["next_cursor"] is None


def test_feed_is_public_demo_readable(isolated_db):
    """Anonymous visitors see the demo user's feed — no key / login needed."""
    _seed_activities(5)
    resp = _client().get("/api/activities/feed")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["items"]) == 5
