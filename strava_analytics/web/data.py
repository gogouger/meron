"""Data loading and caching layer for the web dashboard."""

from pathlib import Path

import pandas as pd

from strava_analytics.loader import load_activities, load_profile
from strava_analytics.enrichment import enrich
from strava_analytics.lifting_program import BASELINE, END_PRS, PROGRAM


_df: pd.DataFrame | None = None
_profile: dict | None = None
_export_dir: Path | None = None


def init(export_dir: str | Path) -> None:
    """Load and enrich the Strava data. Call once at startup."""
    global _df, _profile, _export_dir
    _export_dir = Path(export_dir)
    raw = load_activities(_export_dir)
    _df = enrich(raw)
    _profile = load_profile(_export_dir)


def get_df() -> pd.DataFrame:
    """Return the full enriched DataFrame."""
    if _df is None:
        raise RuntimeError("Data not loaded. Call data.init(export_dir) first.")
    return _df


def get_runs() -> pd.DataFrame:
    """Return only running activities."""
    return get_df()[get_df()["type"] == "Run"]


def get_lifts() -> pd.DataFrame:
    """Return only weight training activities."""
    return get_df()[get_df()["type"] == "Weight Training"]


def get_profile() -> dict:
    """Return athlete profile dict."""
    return _profile or {}


def get_baseline() -> dict:
    """Return baseline PRs from lifting program."""
    return BASELINE


def get_end_prs() -> dict:
    """Return end-of-program PRs."""
    return END_PRS


def get_program() -> list:
    """Return the lifting program."""
    return PROGRAM


def get_export_dir() -> Path:
    """Return the export directory path."""
    if _export_dir is None:
        raise RuntimeError("Data not loaded.")
    return _export_dir


def reload() -> None:
    """Re-load data from disk."""
    if _export_dir:
        init(_export_dir)
