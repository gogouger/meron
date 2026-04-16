"""QR pair-code flow: create → claim → claim-again-fails → expiry."""

import time
from unittest.mock import patch

import pytest
from flask import Flask

from strava_analytics.api import pairing, register_api
from strava_analytics.db import init_engine
from strava_analytics.db.migrations import run_migrations


@pytest.fixture(autouse=True)
def _schema(isolated_db):
    init_engine()
    run_migrations()
    from strava_analytics.web import data as data_mod
    data_mod.init(None)
    # Each test gets a clean in-memory pair store.
    pairing._store.clear()


def _client() -> Flask:
    app = Flask("pair_test")
    register_api(app)
    return app.test_client()


def test_claim_requires_code(isolated_db):
    resp = _client().post("/api/auth/pair/claim", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "validation_error"


def test_claim_unknown_code_returns_404(isolated_db):
    resp = _client().post("/api/auth/pair/claim", json={"code": "NOPENOPE"})
    assert resp.status_code == 404


def test_create_then_claim_returns_key(isolated_db):
    code, _expires = pairing.create_pair(
        api_key="test-read-key", api_base="http://localhost:8051"
    )
    resp = _client().post("/api/auth/pair/claim", json={"code": code})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["api_key"] == "test-read-key"
    assert body["api_base"] == "http://localhost:8051"


def test_code_is_single_use(isolated_db):
    code, _ = pairing.create_pair(api_key="k", api_base="http://x")
    client = _client()
    first = client.post("/api/auth/pair/claim", json={"code": code})
    assert first.status_code == 200
    # Second claim fails.
    second = client.post("/api/auth/pair/claim", json={"code": code})
    assert second.status_code == 404


def test_code_is_case_insensitive_and_trims(isolated_db):
    code, _ = pairing.create_pair(api_key="k", api_base="http://x")
    resp = _client().post("/api/auth/pair/claim",
                          json={"code": f"  {code.lower()}  "})
    assert resp.status_code == 200


def test_pretty_code_with_hyphen_is_accepted(isolated_db):
    """Users type ABCD-1234 from the QR card; we strip the hyphen server-side."""
    code, _ = pairing.create_pair(api_key="k", api_base="http://x")
    pretty = f"{code[:4]}-{code[4:]}"
    resp = _client().post("/api/auth/pair/claim", json={"code": pretty})
    assert resp.status_code == 200


def test_expired_code_not_claimable(isolated_db):
    """Force the stored expiry into the past and claim should 404."""
    code, _ = pairing.create_pair(api_key="k", api_base="http://x")
    # Tamper with the stored expiry (whitebox — fine for tests).
    pairing._store[code].expires_at = time.time() - 1
    resp = _client().post("/api/auth/pair/claim", json={"code": code})
    assert resp.status_code == 404


def test_pair_claim_does_not_require_api_key(isolated_db):
    """The whole point of pairing is to obtain the key. The endpoint is public."""
    code, _ = pairing.create_pair(api_key="k", api_base="http://x")
    # No X-API-Key header.
    resp = _client().post("/api/auth/pair/claim", json={"code": code})
    assert resp.status_code == 200


def test_generate_code_has_safe_alphabet(isolated_db):
    for _ in range(50):
        c = pairing.generate_code()
        assert len(c) == 8
        assert not any(ch in c for ch in "01OIL")
