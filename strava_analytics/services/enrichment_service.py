"""Enrichment cache + orchestration.

Loads raw activity rows from SQLite via the repository, passes them through
the existing `enrich()` pipeline (unchanged), and caches the result in
process memory. Invalidated on any activity mutation.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from ..db import get_session_factory, meron_dir
from ..db.repository import load_raw_activities_df, activity_max_updated_at
from ..enrichment import enrich

logger = logging.getLogger(__name__)

# Module-level cache
_cache: dict[tuple, pd.DataFrame] = {}


def _config_hash(athlete_config: dict) -> str:
    # Only hash fields that affect enrichment output
    relevant = {
        "max_hr": athlete_config.get("max_hr"),
        "hr_zones_pct": athlete_config.get("hr_zones_pct"),
    }
    return hashlib.md5(
        json.dumps(relevant, sort_keys=True, default=str).encode()
    ).hexdigest()


def get_enriched_df(
    user_id: int,
    athlete_config: dict,
    force: bool = False,
    fit_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Return the enriched DataFrame for `user_id`.

    Cache key: (user_id, max(updated_at), config_hash). Cache hit returns
    the cached DataFrame; miss re-runs enrich().
    """
    fit_dir = fit_dir or meron_dir()

    factory = get_session_factory()
    with factory() as session:
        max_updated = activity_max_updated_at(session, user_id)

    cache_key = (user_id, max_updated, _config_hash(athlete_config))
    if not force and cache_key in _cache:
        return _cache[cache_key]

    with factory() as session:
        raw = load_raw_activities_df(user_id, session)

    if raw.empty:
        logger.info("No activities for user %d; enrichment skipped", user_id)
        # Return empty frame with expected columns so downstream .empty checks work
        _cache.clear()
        _cache[cache_key] = raw
        return raw

    logger.info("Enriching %d activities for user %d", len(raw), user_id)
    enriched = enrich(raw, athlete_config=athlete_config, export_dir=fit_dir)
    _cache.clear()
    _cache[cache_key] = enriched
    return enriched


def invalidate_cache(user_id: int | None = None) -> None:
    """Drop cached enriched DataFrames. Called after any mutation."""
    _cache.clear()
