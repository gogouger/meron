"""Login / signup / invite / gating tests.

Covers:
  - admin bootstrap from env vars
  - login/logout round-trip + session cookie
  - invite code generation (admin) + consumption (signup)
  - unauthorised users can still read but not write
  - DEMO_USER_ID fallback for anonymous reads
  - cross-user edit protection
"""

from __future__ import annotations

import os

import pytest
from flask import Flask

from strava_analytics.api import register_api
from strava_analytics.api.passwords import hash_password, verify_password
from strava_analytics.db import init_engine, session_scope
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.models import Activity, InviteCode, SyncState, User


@pytest.fixture
def _schema(isolated_db, monkeypatch):
    monkeypatch.setenv("MERON_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MERON_ADMIN_PASSWORD", "correcthorsebattery")
    init_engine()
    run_migrations()
    from strava_analytics.web import data as data_mod
    data_mod.init(None)


def _client() -> Flask:
    app = Flask("auth_test")
    app.secret_key = "test-secret"
    register_api(app)
    return app.test_client()


# ─── Password helpers ─────────────────────────────────────────────────

def test_hash_and_verify_roundtrip():
    h = hash_password("my password")
    assert verify_password("my password", h)
    assert not verify_password("wrong", h)
    assert not verify_password("my password", None)


def test_hash_rejects_empty():
    with pytest.raises(ValueError):
        hash_password("")


# ─── Admin bootstrap ──────────────────────────────────────────────────

def test_admin_seeded_from_env(_schema):
    with session_scope() as s:
        u = s.query(User).filter_by(username="admin").first()
        assert u is not None
        assert u.is_admin == 1
        assert verify_password("correcthorsebattery", u.password_hash)


def test_admin_password_rotates_on_restart(_schema, monkeypatch):
    # Bump password via env, rerun migration → same user, new hash.
    monkeypatch.setenv("MERON_ADMIN_PASSWORD", "different-password")
    run_migrations()
    with session_scope() as s:
        u = s.query(User).filter_by(username="admin").first()
        assert verify_password("different-password", u.password_hash)


# ─── Login / logout / me ──────────────────────────────────────────────

def test_login_succeeds_with_correct_credentials(_schema):
    c = _client()
    resp = c.post("/api/auth/login",
                  json={"username": "admin", "password": "correcthorsebattery"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user"]["username"] == "admin"
    assert body["user"]["is_admin"] is True


def test_login_rejects_bad_password(_schema):
    c = _client()
    resp = c.post("/api/auth/login",
                  json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401


def test_login_rejects_unknown_user(_schema):
    c = _client()
    resp = c.post("/api/auth/login",
                  json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401


def test_me_reflects_session(_schema):
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    me = c.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["username"] == "admin"


def test_me_401_when_anonymous(_schema):
    assert _client().get("/api/auth/me").status_code == 401


def test_logout_clears_session(_schema):
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


# ─── Invite-gated signup ──────────────────────────────────────────────

def test_signup_requires_invite_code(_schema):
    c = _client()
    resp = c.post("/api/auth/signup",
                  json={"username": "alice", "password": "password123"})
    assert resp.status_code == 400


def test_admin_can_mint_invite(_schema):
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    resp = c.post("/api/auth/invites")
    assert resp.status_code == 201
    code = resp.get_json()["code"]
    assert len(code) == 8

    # Non-admin cannot.
    c2 = _client()
    resp2 = c2.post("/api/auth/invites")
    assert resp2.status_code == 401


def test_signup_with_valid_invite_creates_user(_schema):
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    invite = c.post("/api/auth/invites").get_json()["code"]
    c.post("/api/auth/logout")

    resp = c.post("/api/auth/signup", json={
        "username": "alice", "password": "password123",
        "invite_code": invite,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["user"]["username"] == "alice"
    assert body["user"]["is_admin"] is False

    # Alice is now logged in with her own session.
    assert c.get("/api/auth/me").get_json()["username"] == "alice"

    # Invite is consumed.
    with session_scope() as s:
        row = s.query(InviteCode).filter_by(code=invite).first()
        assert row.consumed_by_user_id is not None

    # New user got their own API keys.
    with session_scope() as s:
        ss = s.query(SyncState).join(User, User.id == SyncState.user_id)\
              .filter(User.username == "alice").first()
        assert ss is not None
        assert ss.api_key_read
        assert ss.api_key_write


def test_invite_code_is_single_use(_schema):
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    invite = c.post("/api/auth/invites").get_json()["code"]
    c.post("/api/auth/logout")

    c.post("/api/auth/signup", json={
        "username": "alice", "password": "password123",
        "invite_code": invite,
    })
    c2 = _client()
    resp = c2.post("/api/auth/signup", json={
        "username": "bob", "password": "password123",
        "invite_code": invite,
    })
    assert resp.status_code == 404


def test_signup_rejects_short_password(_schema):
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    invite = c.post("/api/auth/invites").get_json()["code"]
    c.post("/api/auth/logout")

    resp = c.post("/api/auth/signup", json={
        "username": "alice", "password": "short",
        "invite_code": invite,
    })
    assert resp.status_code == 400


def test_signup_rejects_taken_username(_schema):
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    invite = c.post("/api/auth/invites").get_json()["code"]
    c.post("/api/auth/logout")

    resp = c.post("/api/auth/signup", json={
        "username": "admin", "password": "password123",
        "invite_code": invite,
    })
    assert resp.status_code == 400


# ─── Gating ───────────────────────────────────────────────────────────

def test_anonymous_can_read_demo_data(_schema):
    """Anon reads return data (scoped to the demo user = admin)."""
    c = _client()
    resp = c.get("/api/stats")
    assert resp.status_code == 200  # no key, no session → demo fallback


def test_anonymous_cannot_sync(_schema):
    c = _client()
    resp = c.post("/api/sync/strava")
    assert resp.status_code == 401


def test_anonymous_cannot_create_activity(_schema):
    c = _client()
    resp = c.post("/api/activities",
                  json={"type": "Run", "start_time": "2025-01-01T00:00:00"})
    assert resp.status_code == 401


def test_logged_in_user_can_create_own_activity(_schema):
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    resp = c.post("/api/activities", json={
        "type": "Run", "start_time": "2025-04-10T09:00:00",
    })
    assert resp.status_code == 201


def test_cross_user_edits_404(_schema):
    """Alice cannot patch an activity owned by admin."""
    c = _client()
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correcthorsebattery"})
    created = c.post("/api/activities", json={
        "type": "Run", "start_time": "2025-04-10T09:00:00",
    }).get_json()
    activity_id = created["id"]
    invite = c.post("/api/auth/invites").get_json()["code"]
    c.post("/api/auth/logout")

    # Alice signs up and tries to patch admin's activity.
    c2 = _client()
    c2.post("/api/auth/signup", json={
        "username": "alice", "password": "password123",
        "invite_code": invite,
    })
    resp = c2.patch(f"/api/activities/{activity_id}",
                    json={"name": "Hacked"})
    assert resp.status_code == 404