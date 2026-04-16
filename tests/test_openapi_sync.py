"""Guardrail: every registered /api/* rule appears in openapi.yaml.

Prevents the drift where someone adds a route but forgets to document it.
"""

from pathlib import Path

import pytest
import yaml
from flask import Flask

from strava_analytics.api import register_api
from strava_analytics.db import init_engine
from strava_analytics.db.migrations import run_migrations


SPEC = Path(__file__).resolve().parent.parent / "strava_analytics" / "web" / "openapi.yaml"


def _rules() -> set[tuple[str, str]]:
    init_engine()
    run_migrations()
    from strava_analytics.web import data as data_mod
    data_mod.init(None)
    app = Flask("t")
    register_api(app)
    rules: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        for m in rule.methods or set():
            if m in ("HEAD", "OPTIONS"):
                continue
            rules.add((m.lower(), rule.rule))
    return rules


def _spec_paths() -> set[tuple[str, str]]:
    doc = yaml.safe_load(SPEC.read_text())
    out: set[tuple[str, str]] = set()
    for path, methods in (doc.get("paths") or {}).items():
        # Convert OpenAPI's {activity_id} to Flask's <int:activity_id>
        for method in methods:
            if method.lower() not in {"get", "post", "patch", "delete", "put"}:
                continue
            out.add((method.lower(), path))
    return out


def _normalize(flask_path: str) -> str:
    """Flask's <int:activity_id> → OpenAPI's {activity_id}."""
    import re
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", flask_path)


def test_every_api_route_is_documented(isolated_db):
    flask_rules = {(m, _normalize(p)) for m, p in _rules()}
    spec_rules = _spec_paths()
    missing = flask_rules - spec_rules
    assert not missing, (
        f"Routes exist in code but not in openapi.yaml: {sorted(missing)}"
    )


def test_every_documented_route_exists(isolated_db):
    flask_rules = {(m, _normalize(p)) for m, p in _rules()}
    spec_rules = _spec_paths()
    # Allow OAuth routes in the spec that aren't under /api/
    extra = {(m, p) for m, p in spec_rules if p.startswith("/api/")} - flask_rules
    assert not extra, (
        f"openapi.yaml has routes that don't exist: {sorted(extra)}"
    )
