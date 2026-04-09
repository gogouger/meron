"""Data loading and caching layer for the web dashboard."""

import json
from pathlib import Path

import pandas as pd

from strava_analytics.loader import load_activities, load_profile
from strava_analytics.enrichment import enrich
from strava_analytics.lifting_program import BASELINE, END_PRS, PROGRAM


_df: pd.DataFrame | None = None
_profile: dict | None = None
_export_dir: Path | None = None
_athlete_config: dict | None = None
_best_efforts: pd.DataFrame | None = None

# Default athlete config
_DEFAULT_CONFIG = {
    "max_hr": 200,
    "hr_zones_pct": [60, 70, 80, 90],  # boundaries as % of max HR
    "zone_names": ["Recovery", "Easy", "Moderate", "Threshold", "Max"],
    "openai_api_key": "",  # OpenAI API key for ChatGPT chat widget
}


def _load_athlete_config(export_dir: Path) -> dict:
    """Load athlete config from JSON file, or return defaults."""
    cfg_path = export_dir / "athlete_config.json"
    if cfg_path.exists():
        with open(cfg_path) as f:
            user_cfg = json.load(f)
        return {**_DEFAULT_CONFIG, **user_cfg}
    return _DEFAULT_CONFIG.copy()


def save_athlete_config(config: dict) -> None:
    """Write athlete config to JSON file in the export directory."""
    global _athlete_config
    if _export_dir is None:
        return
    cfg_path = _export_dir / "athlete_config.json"
    with open(cfg_path, "w") as f:
        json.dump(config, f, indent=2)
    _athlete_config = config


def init(export_dir: str | Path) -> None:
    """Load and enrich the Strava data. Call once at startup."""
    global _df, _profile, _export_dir, _athlete_config, _best_efforts
    _export_dir = Path(export_dir)
    _athlete_config = _load_athlete_config(_export_dir)
    raw = load_activities(_export_dir)
    _df = enrich(raw, athlete_config=_athlete_config, export_dir=_export_dir)
    _profile = load_profile(_export_dir)

    # Build route fingerprint index (incremental, fast after first run)
    from strava_analytics.route_matching import build_route_index
    build_route_index(_df, _export_dir)

    # Compute best efforts at startup (cached after first run)
    from strava_analytics.fitness import compute_best_efforts
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Computing best efforts...")
    _best_efforts = compute_best_efforts(_df, _export_dir)
    logger.info("Best efforts: %d records", len(_best_efforts) if _best_efforts is not None else 0)


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


def get_athlete_config() -> dict:
    """Return athlete config dict."""
    return _athlete_config or _DEFAULT_CONFIG.copy()


def get_best_efforts() -> pd.DataFrame:
    """Return pre-computed best efforts DataFrame."""
    if _best_efforts is None:
        return pd.DataFrame()
    return _best_efforts


def get_export_dir() -> Path:
    """Return the export directory path."""
    if _export_dir is None:
        raise RuntimeError("Data not loaded.")
    return _export_dir


def reload() -> None:
    """Re-load data from disk."""
    if _export_dir:
        init(_export_dir)
