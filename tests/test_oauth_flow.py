"""End-to-end OAuth flow with stravalib fully mocked.

Covers: start → callback (exchange code) → stored encrypted → refresh when
near-expiry → disconnect clears tokens.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import Flask

from strava_analytics.api import register_api, register_oauth
from strava_analytics.auth import strava_oauth
from strava_analytics.db import init_engine, session_scope
from strava_analytics.db.migrations import run_migrations
from strava_analytics.db.models import SyncState


@pytest.fixture(autouse=True)
def _ensure_schema(isolated_db):
    """Every OAuth test needs the schema created."""
    init_engine()
    run_migrations()


FAKE_TOKENS = {
    "access_token": "fake_access_123",
    "refresh_token": "fake_refresh_456",
    "expires_at": int((datetime.now(timezone.utc) + timedelta(hours=6)).timestamp()),
    "athlete": {"id": 99999},
    "scope": "read,activity:read_all",
}


def _app(isolated_db):
    init_engine()
    run_migrations()
    from strava_analytics.web import data as data_mod
    data_mod.init(None)
    app = Flask("oauth_test")
    app.secret_key = "test-secret"
    register_oauth(app)
    register_api(app)
    return app


def test_exchange_code_stores_encrypted_tokens(isolated_db, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1234")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")

    with patch("stravalib.Client") as MockClient:
        MockClient.return_value.exchange_code_for_token.return_value = FAKE_TOKENS
        bundle = strava_oauth.exchange_code("fake_auth_code")

    assert bundle.access_token == "fake_access_123"
    assert bundle.refresh_token == "fake_refresh_456"
    assert bundle.athlete_id == 99999

    with session_scope() as session:
        strava_oauth.save_tokens(session, user_id=1, bundle=bundle)

    # The stored value must NOT equal the plaintext — it's Fernet-encrypted.
    with session_scope() as session:
        row = session.query(SyncState).filter_by(user_id=1, provider="strava").first()
        assert row is not None
        assert row.access_token != "fake_access_123"
        assert row.refresh_token != "fake_refresh_456"

    # But round-tripping the decrypt yields the original value.
    with session_scope() as session:
        row = session.query(SyncState).filter_by(user_id=1, provider="strava").first()
        assert strava_oauth._decrypt(row.access_token) == "fake_access_123"


def test_refresh_is_skipped_when_token_not_near_expiry(isolated_db, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1234")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")

    bundle = strava_oauth.TokenBundle(
        access_token="still_valid",
        refresh_token="refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
        athlete_id=1,
    )
    with session_scope() as session:
        strava_oauth.save_tokens(session, user_id=1, bundle=bundle)

    with patch("stravalib.Client") as MockClient:
        with session_scope() as session:
            access = strava_oauth.refresh_if_needed(user_id=1, session=session)
        # Should not have called the refresh endpoint.
        MockClient.return_value.refresh_access_token.assert_not_called()
    assert access == "still_valid"


def test_refresh_triggers_when_token_expired(isolated_db, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1234")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")

    expired = strava_oauth.TokenBundle(
        access_token="old",
        refresh_token="refresh",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        athlete_id=1,
    )
    with session_scope() as session:
        strava_oauth.save_tokens(session, user_id=1, bundle=expired)

    refreshed = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_at": int((datetime.now(timezone.utc) + timedelta(hours=6)).timestamp()),
        "scope": "read",
    }
    with patch("stravalib.Client") as MockClient:
        MockClient.return_value.refresh_access_token.return_value = refreshed
        with session_scope() as session:
            access = strava_oauth.refresh_if_needed(user_id=1, session=session)

    assert access == "new_access"
    with session_scope() as session:
        row = session.query(SyncState).filter_by(user_id=1, provider="strava").first()
        assert strava_oauth._decrypt(row.access_token) == "new_access"


def test_disconnect_clears_tokens(isolated_db):
    bundle = strava_oauth.TokenBundle(
        access_token="a", refresh_token="r",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
        athlete_id=1,
    )
    with session_scope() as session:
        strava_oauth.save_tokens(session, user_id=1, bundle=bundle)
        strava_oauth.disconnect(session, user_id=1)

    with session_scope() as session:
        row = session.query(SyncState).filter_by(user_id=1, provider="strava").first()
        assert row.access_token is None
        assert row.refresh_token is None
        assert row.token_expires_at is None


def test_oauth_start_redirects_anon_to_login(isolated_db, monkeypatch):
    """Anonymous visitors hitting /oauth/strava/start get bounced to /login."""
    monkeypatch.delenv("STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("STRAVA_CLIENT_SECRET", raising=False)
    app = _app(isolated_db)
    client = app.test_client()
    resp = client.get("/oauth/strava/start")
    assert resp.status_code == 302
    assert resp.location.endswith("/login")


def test_oauth_start_requires_configuration_when_logged_in(isolated_db, monkeypatch):
    """Once logged in, /oauth/strava/start 503s if env vars are missing."""
    monkeypatch.setenv("MERON_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MERON_ADMIN_PASSWORD", "password123")
    monkeypatch.delenv("STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("STRAVA_CLIENT_SECRET", raising=False)
    run_migrations()  # picks up the env creds
    app = _app(isolated_db)
    client = app.test_client()
    client.post("/api/auth/login",
                json={"username": "admin", "password": "password123"})
    resp = client.get("/oauth/strava/start")
    assert resp.status_code == 503


def test_oauth_callback_rejects_missing_code(isolated_db, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1234")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")
    app = _app(isolated_db)
    client = app.test_client()
    resp = client.get("/oauth/strava/callback")
    assert resp.status_code == 400
