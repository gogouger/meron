"""Data loading and caching layer — DB-backed since v2.

This module's public API is preserved for backwards compatibility with
every page that imports from it. Under the hood:
- Raw activities come from SQLite (`db/repository.py`).
- Enrichment is orchestrated via `services/enrichment_service`.
- Sidecar artifacts (athlete_config.json, route_index.json, best_efforts_cache.json,
  heatmap-data.json, FIT files) live under `~/.meron/` (the "export dir").

`init(path)` accepts either:
  - a legacy Strava export directory (triggers `migration_002_backfill_bulk`), OR
  - the `~/.meron/` MERON directory directly.
"""

import json
import logging
import os
from pathlib import Path

import pandas as pd

from strava_analytics.db import (
    get_session_factory,
    init_engine,
    meron_dir,
)
from strava_analytics.db.migrations import run_migrations
from strava_analytics.lifting_program import BASELINE, END_PRS, PROGRAM
from strava_analytics.services.enrichment_service import (
    get_enriched_df,
    invalidate_cache,
)


logger = logging.getLogger(__name__)


_profile: dict | None = None
_athlete_config: dict | None = None
_best_efforts: pd.DataFrame | None = None

# The "export dir" is now the MERON dir (~/.meron by default). FIT files,
# sidecar JSON, and route artifacts live here.
_export_dir: Path | None = None


# Default athlete config
_DEFAULT_CONFIG = {
    "max_hr": 200,
    "hr_zones_pct": [60, 70, 80, 90],  # boundaries as % of max HR
    "zone_names": ["Recovery", "Easy", "Moderate", "Threshold", "Max"],
    "openai_api_key": "",  # OpenAI API key for ChatGPT chat widget
}


def _load_athlete_config(meron_root: Path) -> dict:
    """Load athlete config from JSON file, or return defaults."""
    cfg_path = meron_root / "athlete_config.json"
    if cfg_path.exists():
        with open(cfg_path) as f:
            user_cfg = json.load(f)
        return {**_DEFAULT_CONFIG, **user_cfg}
    return _DEFAULT_CONFIG.copy()


def save_athlete_config(config: dict) -> None:
    """Write athlete config to JSON file in the MERON dir."""
    global _athlete_config
    if _export_dir is None:
        return
    cfg_path = _export_dir / "athlete_config.json"
    with open(cfg_path, "w") as f:
        json.dump(config, f, indent=2)
    _athlete_config = config
    # Config affects enrichment output → invalidate cache
    invalidate_cache()


def init(path: str | Path | None = None) -> None:
    """Initialize DB and load athlete config.

    `path` may be:
      - None → use `~/.meron/` (default)
      - A MERON dir (contains meron.db) → use directly
      - A legacy Strava export dir → trigger migration if DB is empty
    """
    global _profile, _export_dir, _athlete_config, _best_efforts

    # 1. Resolve meron_root
    meron_root = meron_dir()
    meron_root.mkdir(parents=True, exist_ok=True)
    _export_dir = meron_root

    # 2. Init engine + run migrations
    init_engine()
    run_migrations()

    # 3. If `path` points at a legacy Strava export dir that hasn't been
    #    migrated yet, pull it in.
    if path is not None:
        path = Path(path).expanduser()
        # Does it look like a Strava export?
        if (path / "activities.csv").exists() and path != meron_root:
            from strava_analytics.db.models import Activity
            factory = get_session_factory()
            with factory() as session:
                existing = session.query(Activity).limit(1).first()
                is_empty = existing is None
            if is_empty:
                logger.info("Auto-importing Strava export from %s", path)
                from strava_analytics.db.migrations import migration_002_backfill_bulk
                report = migration_002_backfill_bulk(path)
                logger.info("Import report: %s", report)

    # 4. Optional: `MERON_IMPORT_FROM` env var bootstrap
    import_from = os.environ.get("MERON_IMPORT_FROM")
    if import_from:
        import_path = Path(import_from).expanduser()
        if (import_path / "activities.csv").exists():
            from strava_analytics.db.models import Activity
            factory = get_session_factory()
            with factory() as session:
                existing = session.query(Activity).limit(1).first()
                is_empty = existing is None
            if is_empty:
                from strava_analytics.db.migrations import migration_002_backfill_bulk
                logger.info("MERON_IMPORT_FROM bootstrap from %s", import_path)
                migration_002_backfill_bulk(import_path)

    # 5. Load athlete config (used everywhere)
    _athlete_config = _load_athlete_config(meron_root)
    _profile = _load_profile(meron_root)

    # 6. Prime enrichment cache + sidecar artifacts
    df = get_enriched_df(user_id=1, athlete_config=_athlete_config, fit_dir=meron_root)

    # 7. Build route fingerprint index (incremental; uses FIT files in meron_root/fit)
    try:
        from strava_analytics.route_matching import build_route_index
        build_route_index(df, meron_root)
    except Exception as e:
        logger.warning("Route index build failed: %s", e)

    # 8. Best efforts (cached)
    try:
        from strava_analytics.fitness import compute_best_efforts
        logger.info("Computing best efforts...")
        _best_efforts = compute_best_efforts(df, meron_root)
        logger.info("Best efforts: %d records", len(_best_efforts) if _best_efforts is not None else 0)
    except Exception as e:
        logger.warning("Best efforts failed: %s", e)
        _best_efforts = pd.DataFrame()

    # 9. Precompute heatmap
    try:
        _precompute_heatmap(meron_root)
    except Exception as e:
        logger.warning("Heatmap precompute failed: %s", e)


def _load_profile(meron_root: Path) -> dict:
    """Load athlete profile from ~/.meron/profile.csv if present."""
    path = meron_root / "profile.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def get_df() -> pd.DataFrame:
    """Return the full enriched DataFrame (cached)."""
    cfg = get_athlete_config()
    return get_enriched_df(user_id=1, athlete_config=cfg, fit_dir=_export_dir or meron_dir())


def get_runs() -> pd.DataFrame:
    """Return only running activities."""
    df = get_df()
    return df[df["type"] == "Run"]


def get_lifts() -> pd.DataFrame:
    """Return only weight training activities."""
    df = get_df()
    return df[df["type"] == "Weight Training"]


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


def _precompute_heatmap(meron_root: Path) -> None:
    """Write route overlay data to assets/heatmap-data.json at startup."""
    index_path = meron_root / "route_index.json"
    if not index_path.exists():
        return

    try:
        raw = json.loads(index_path.read_text())
        fps = raw.get("fingerprints", {})
    except Exception:
        return

    routes = []
    all_lats = []
    all_lons = []
    for fn, fp in fps.items():
        pts = fp.get("points", [])
        if len(pts) < 3:
            continue
        route = [[round(p[0], 5), round(p[1], 5)] for p in pts]
        routes.append(route)
        for p in pts:
            all_lats.append(p[0])
            all_lons.append(p[1])

    if not routes:
        return

    all_lats.sort()
    all_lons.sort()
    center = [all_lats[len(all_lats) // 2], all_lons[len(all_lons) // 2]]

    data_out = {"routes": routes, "center": center}

    assets_dir = Path(__file__).parent / "assets"
    heat_path = assets_dir / "heatmap-data.json"
    try:
        heat_path.write_text(json.dumps(data_out, separators=(",", ":")))
        logger.info("Heatmap: wrote %d routes to %s", len(routes), heat_path)
    except Exception as e:
        logger.warning("Heatmap: failed to write: %s", e)


def get_export_dir() -> Path:
    """Return the MERON root directory (FIT files, sidecar JSON live here)."""
    if _export_dir is None:
        return meron_dir()
    return _export_dir


def reload() -> None:
    """Re-derive everything: invalidate cache, reload config, recompute sidecars."""
    global _athlete_config, _best_efforts
    invalidate_cache()
    root = get_export_dir()
    _athlete_config = _load_athlete_config(root)
    df = get_enriched_df(user_id=1, athlete_config=_athlete_config, fit_dir=root, force=True)
    try:
        from strava_analytics.fitness import compute_best_efforts
        _best_efforts = compute_best_efforts(df, root)
    except Exception as e:
        logger.warning("Best efforts failed on reload: %s", e)
    try:
        _precompute_heatmap(root)
    except Exception as e:
        logger.warning("Heatmap precompute failed on reload: %s", e)
