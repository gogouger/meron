"""Step 3 guardrail: no more hard-coded user_id=1 in api/ or web/.

``current_user_id()`` is the single source of truth. When the multi-user
refactor lands, only that function changes — every caller keeps working.
"""

import re
from pathlib import Path

import pytest

from strava_analytics.api.context import current_user_id


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [
    PROJECT_ROOT / "strava_analytics" / "api",
    PROJECT_ROOT / "strava_analytics" / "web",
    PROJECT_ROOT / "strava_analytics" / "services",
]

# Files where the literal is permitted (docstrings referring to the old value).
ALLOWED_FILES = {
    PROJECT_ROOT / "strava_analytics" / "api" / "context.py",
}


_PATTERN = re.compile(r"\buser_id\s*(?:=|==)\s*1\b(?!\d)")


def test_current_user_id_returns_single_user():
    assert current_user_id() == 1


def test_no_hardcoded_user_id_in_api_web_services():
    hits: list[str] = []
    for root in SCAN_DIRS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path in ALLOWED_FILES:
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if _PATTERN.search(line):
                    hits.append(f"{path}:{lineno}: {line.strip()}")
    assert hits == [], (
        "Hard-coded user_id=1 / user_id == 1 found outside of context.py. "
        "Use current_user_id() instead:\n  " + "\n  ".join(hits)
    )
