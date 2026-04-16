"""CORS behaviour driven by MERON_ALLOWED_ORIGINS.

Default (unset) → no Access-Control-Allow-Origin header.
Set to ``app://meron`` → header echoed on matching Origin.
"""

import os

import pytest
from flask import Flask

from strava_analytics.api import register_api
from strava_analytics.db import init_engine
from strava_analytics.db.migrations import run_migrations


flask_cors = pytest.importorskip("flask_cors")


def _app(isolated_db):
    init_engine()
    run_migrations()
    from strava_analytics.web import data as data_mod
    data_mod.init(None)
    from strava_analytics.api.app import create_app
    return create_app()


def test_no_cors_headers_by_default(isolated_db, monkeypatch):
    monkeypatch.delenv("MERON_ALLOWED_ORIGINS", raising=False)
    app = _app(isolated_db)
    client = app.test_client()
    resp = client.get("/api/healthz")
    assert resp.status_code == 200
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_cors_header_set_when_origin_allowed(isolated_db, monkeypatch):
    monkeypatch.setenv("MERON_ALLOWED_ORIGINS", "app://meron,app://other")
    app = _app(isolated_db)
    client = app.test_client()
    resp = client.get("/api/healthz", headers={"Origin": "app://meron"})
    assert resp.status_code == 200
    assert resp.headers.get("Access-Control-Allow-Origin") == "app://meron"


def test_cors_rejects_unlisted_origin(isolated_db, monkeypatch):
    monkeypatch.setenv("MERON_ALLOWED_ORIGINS", "app://meron")
    app = _app(isolated_db)
    client = app.test_client()
    resp = client.get("/api/healthz", headers={"Origin": "https://evil.com"})
    # flask-cors simply doesn't set the header for un-matched origins;
    # the request still succeeds but browsers will block it.
    assert resp.headers.get("Access-Control-Allow-Origin") != "https://evil.com"
