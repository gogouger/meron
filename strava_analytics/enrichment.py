"""Enrich activity data with kid detection, HR adjustments, fatigue, and lifting."""

import logging
import re

import numpy as np
import pandas as pd

from .lifting_program import PROGRAM, get_lift_days, get_primary_lifts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kid / stroller detection
# ---------------------------------------------------------------------------

_KID_PATTERNS = [
    r"stroll",
    r"wind\s*sail",
    r"windsail",
    r"both\s+kids",
    r"double\s+stroller",
    r"with\s+kid",
]
_KID_RE = re.compile("|".join(_KID_PATTERNS), re.IGNORECASE)


def detect_kid(name: str, description: str) -> bool:
    """Return True if the activity involved pushing kids (stroller/windsail)."""
    text = f"{name or ''} {description or ''}"
    return bool(_KID_RE.search(text))


# ---------------------------------------------------------------------------
# Run type classification
# ---------------------------------------------------------------------------

def classify_run(name: str, description: str, distance_mi: float, pace: float) -> str:
    """Classify a run into a training type based on name, description, distance, and pace."""
    text = f"{name or ''} {description or ''}".lower()

    if any(w in text for w in ["race", "10k", "5k", "marathon", "trot", "dash", "frisco"]):
        return "race"
    if any(w in text for w in ["interval", "tempo", "fast", "speed", "800"]):
        return "workout"
    if "ruck" in text:
        return "ruck"
    if any(w in text for w in ["long run", "long"]) or distance_mi >= 8:
        return "long"
    if any(w in text for w in ["recovery", "shake", "shakeout", "easy"]):
        return "easy"
    if distance_mi <= 2.5:
        return "short/easy"
    if pd.notna(pace) and pace >= 12:
        return "easy"
    return "moderate"


# ---------------------------------------------------------------------------
# Heart rate adjustment
# ---------------------------------------------------------------------------

# ACSM: HR rises ~1 bpm per 1°C above ~15°C (59°F).
# Per °F above 60: ~0.56 bpm. We'll use 0.5 bpm/°F for simplicity.
_TEMP_NEUTRAL_F = 60.0
_HR_PER_DEGREE_F = 0.5

# Stroller penalty: studies suggest +5-10 bpm at same pace. Use 7.
_STROLLER_HR_PENALTY = 7.0

# Elevation penalty: ~1 bpm per 300ft above 5000ft (Parker CO is ~5800ft baseline,
# so most runs are at altitude already. We skip altitude adjustment since it's
# a constant for this athlete.)


def adjust_hr(avg_hr: float, temp_f: float, with_kid: bool) -> tuple[float, float]:
    """Return (adjusted_hr, total_adjustment).

    adjusted_hr represents what the effort would have been at 60°F without stroller.
    A lower adjusted_hr means the raw HR was inflated by conditions.
    """
    if pd.isna(avg_hr):
        return np.nan, 0.0

    adj = 0.0

    # Temperature adjustment — heat raises HR, cold lowers it
    if pd.notna(temp_f):
        if temp_f > _TEMP_NEUTRAL_F:
            adj += (temp_f - _TEMP_NEUTRAL_F) * _HR_PER_DEGREE_F
        elif temp_f < _TEMP_NEUTRAL_F:
            adj -= (_TEMP_NEUTRAL_F - temp_f) * 0.25  # smaller effect in cold

    # Stroller adjustment
    if with_kid:
        adj += _STROLLER_HR_PENALTY

    return avg_hr - adj, adj


# ---------------------------------------------------------------------------
# Fatigue scoring
# ---------------------------------------------------------------------------

def _training_stress(row: pd.Series) -> float:
    """Estimate a single training stress score for one activity.

    Running uses pace-based intensity factor, weighted by HR when available.
    This avoids undervaluing slow hard efforts (hills, heat, stroller).
    Falls back to pace-only when HR data is missing (~40% of activities).
    """
    atype = row.get("type", "")
    dist = row.get("distance_mi", 0) or 0
    time_min = row.get("moving_time_min", 0) or 0
    pace = row.get("pace_min_per_mi", None)
    avg_hr = row.get("avg_hr", None)

    if atype == "Run":
        # Pace-based intensity: baseline ~10:30 = factor 1.0
        if pd.notna(pace) and pace > 0:
            factor = max(0.6, min(2.0, 10.5 / pace))
        else:
            factor = 1.0
        # HR weighting: scale by cardiac effort when available
        if pd.notna(avg_hr) and avg_hr > 0:
            hr_factor = min(avg_hr / 160.0, 1.5)
            factor *= (0.5 + 0.5 * hr_factor)
        return dist * factor * 10
    elif atype == "Weight Training":
        return time_min * 0.5
    elif atype in ("Walk", "Hike"):
        return dist * 4
    else:
        return time_min * 0.2


def _compute_training_stress_vectorized(df: pd.DataFrame) -> pd.Series:
    """Vectorized training stress computation across all activities."""
    stress = pd.Series(0.0, index=df.index)
    dist = df["distance_mi"].fillna(0)
    time_min = df["moving_time_min"].fillna(0)
    pace = df["pace_min_per_mi"]
    avg_hr = df["avg_hr"]

    # Running
    run_mask = df["type"] == "Run"
    factor = pd.Series(1.0, index=df.index)
    valid_pace = pace.notna() & (pace > 0)
    factor[valid_pace] = (10.5 / pace[valid_pace]).clip(0.6, 2.0)
    # HR weighting
    valid_hr = avg_hr.notna() & (avg_hr > 0)
    hr_factor = (avg_hr / 160.0).clip(upper=1.5)
    factor[valid_hr] *= (0.5 + 0.5 * hr_factor[valid_hr])
    stress[run_mask] = dist[run_mask] * factor[run_mask] * 10

    # Weight Training
    wt_mask = df["type"] == "Weight Training"
    stress[wt_mask] = time_min[wt_mask] * 0.5

    # Walk/Hike
    walk_mask = df["type"].isin(["Walk", "Hike"])
    stress[walk_mask] = dist[walk_mask] * 4

    # Other
    other_mask = ~(run_mask | wt_mask | walk_mask)
    stress[other_mask] = time_min[other_mask] * 0.2

    return stress


def compute_fatigue(df: pd.DataFrame) -> pd.DataFrame:
    """Add fatigue columns: acute_load (7d), chronic_load (28d), freshness (TSB).

    Positive freshness = rested. Negative = fatigued.
    Also adds a simple label: Fresh / Neutral / Tired / Overreaching.
    """
    df = df.copy()
    df["training_stress"] = _compute_training_stress_vectorized(df)

    # Group by date and sum stress (multiple activities per day)
    daily = df.groupby(df["date"].dt.date)["training_stress"].sum()
    # Reindex to full date range
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_range.date, fill_value=0)

    # Exponentially weighted loads (Banister model, matches TrainingPeaks)
    acute = daily.ewm(span=7, min_periods=1).mean()
    chronic = daily.ewm(span=42, min_periods=1).mean()

    # Map back to each activity
    date_to_acute = dict(zip(acute.index, acute.values))
    date_to_chronic = dict(zip(chronic.index, chronic.values))

    df["acute_load_7d"] = df["date"].dt.date.map(date_to_acute)
    df["chronic_load_28d"] = df["date"].dt.date.map(date_to_chronic)
    df["freshness"] = df["chronic_load_28d"] - df["acute_load_7d"]

    # Use percentile-based thresholds relative to athlete's own history
    p25 = df["freshness"].quantile(0.25)
    p50 = df["freshness"].quantile(0.50)
    p75 = df["freshness"].quantile(0.75)

    fatigue_cat = pd.cut(
        df["freshness"],
        bins=[-np.inf, p25, p50, p75, np.inf],
        labels=["Heavy Load", "Fatigued", "Normal", "Fresh"],
    )
    df["fatigue_level"] = fatigue_cat.astype(str)
    df.loc[df["freshness"].isna(), "fatigue_level"] = "Unknown"
    return df


# ---------------------------------------------------------------------------
# Lifting integration
# ---------------------------------------------------------------------------

def map_lifting_program(df: pd.DataFrame) -> pd.DataFrame:
    """Map the lifting program days to Weight Training activities.

    Takes the N most recent Weight Training activities (where N = number of
    lift days in the program) and assigns program day and exercise details.
    """
    df = df.copy()

    # Initialize lifting columns
    lift_cols = [
        "program_day", "bench_weight", "bench_volume", "bench_sets", "bench_reps",
        "squat_weight", "squat_volume", "squat_sets", "squat_reps",
        "deadlift_weight", "deadlift_volume", "deadlift_sets", "deadlift_reps",
        "ohp_weight", "ohp_volume", "ohp_sets", "ohp_reps",
        "pullup_sets", "pullup_reps",
        "hip_thrust_weight", "lift_exercises",
    ]
    for col in lift_cols:
        df[col] = np.nan
    df["lift_exercises"] = ""

    lift_days = get_lift_days()
    n_lift_days = len(lift_days)

    # Get weight training activities sorted by date descending
    wt_mask = df["type"] == "Weight Training"
    wt_indices = df[wt_mask].sort_values("date", ascending=False).index.tolist()

    if len(wt_indices) < n_lift_days:
        # Not enough activities to map the full program — map what we can
        n_lift_days = len(wt_indices)

    # Map most recent N lift activities to program days (reverse order)
    for i, (day_num, _, exercises) in enumerate(reversed(lift_days)):
        if i >= n_lift_days:
            break
        idx = wt_indices[i]
        df.at[idx, "program_day"] = day_num
        lifts = get_primary_lifts(exercises)
        for k, v in lifts.items():
            if v is not None:
                df.at[idx, k] = v

        # Readable exercise summary
        parts = []
        for name, sets, reps, weight in exercises:
            if sets and reps and weight:
                parts.append(f"{name} {sets}x{reps}@{weight}")
            elif sets and reps:
                parts.append(f"{name} {sets}x{reps}")
            else:
                parts.append(name)
        df.at[idx, "lift_exercises"] = "; ".join(parts)

    return df


# ---------------------------------------------------------------------------
# HR zone computation
# ---------------------------------------------------------------------------

# Default zone boundaries as % of max HR
_DEFAULT_MAX_HR = 200
_DEFAULT_ZONE_PCT = [60, 70, 80, 90]  # Z1/Z2 boundary, Z2/Z3, Z3/Z4, Z4/Z5
_ZONE_NAMES = ["Recovery", "Easy", "Moderate", "Threshold", "Max"]


def _compute_hr_zones(df: pd.DataFrame, max_hr: int, zone_pct: list[int]) -> pd.DataFrame:
    """Add hr_zone (1-5) and hr_zone_name columns based on adjusted_hr."""
    # Use adjusted_hr for more accurate classification (accounts for heat/stroller)
    hr = df["adjusted_hr"]

    # Compute zone boundaries in bpm
    boundaries = [max_hr * p / 100 for p in zone_pct]  # e.g. [120, 140, 160, 180]

    conditions = [
        hr < boundaries[0],                           # Z1: < 60%
        (hr >= boundaries[0]) & (hr < boundaries[1]), # Z2: 60-70%
        (hr >= boundaries[1]) & (hr < boundaries[2]), # Z3: 70-80%
        (hr >= boundaries[2]) & (hr < boundaries[3]), # Z4: 80-90%
        hr >= boundaries[3],                           # Z5: >= 90%
    ]
    zones = [1, 2, 3, 4, 5]

    df["hr_zone"] = np.select(conditions, zones, default=np.nan)
    df.loc[hr.isna(), "hr_zone"] = np.nan

    zone_name_map = {1: _ZONE_NAMES[0], 2: _ZONE_NAMES[1], 3: _ZONE_NAMES[2],
                     4: _ZONE_NAMES[3], 5: _ZONE_NAMES[4]}
    df["hr_zone_name"] = df["hr_zone"].map(zone_name_map)

    return df


def _blend_run_type(df: pd.DataFrame) -> pd.DataFrame:
    """Refine keyword-based run_type using HR zones.

    5 final types: race, hard_effort, long, moderate, easy.
    - race keyword → always race
    - hard_effort keyword → stays hard_effort if Z4+ HR; downgrade if low HR
    - long keyword/distance → stays long (unless high HR + short distance)
    - moderate/easy → promote to hard_effort if high HR effort detected
    - moderate (default) → downgrade to easy if Z1-Z2 HR
    - No HR data → keep keyword classification
    """
    runs_mask = df["type"] == "Run"
    has_hr = df["hr_zone"].notna()
    mask = runs_mask & has_hr

    if not mask.any():
        return df

    zone = df.loc[mask, "hr_zone"]
    kw_type = df.loc[mask, "run_type"]
    dist = df.loc[mask, "distance_mi"].fillna(0)

    blended = kw_type.copy()

    # Compute Z4+Z5 fraction from per-second zone time columns (zone_1_s .. zone_5_s)
    z4 = df.loc[mask, "zone_4_s"].fillna(0) if "zone_4_s" in df.columns else pd.Series(0, index=df.loc[mask].index)
    z5 = df.loc[mask, "zone_5_s"].fillna(0) if "zone_5_s" in df.columns else pd.Series(0, index=df.loc[mask].index)
    total_zone = pd.Series(0.0, index=df.loc[mask].index)
    for zc in ["zone_1_s", "zone_2_s", "zone_3_s", "zone_4_s", "zone_5_s"]:
        if zc in df.columns:
            total_zone = total_zone + df.loc[mask, zc].fillna(0)
    z4_z5_frac = (z4 + z5) / total_zone.replace(0, np.nan)

    # hard_effort + low HR → mislabeled by keyword; downgrade
    hard_effort_mask = kw_type == "hard_effort"
    blended.loc[hard_effort_mask & (zone <= 2)] = "easy"
    blended.loc[hard_effort_mask & (zone == 3)] = "moderate"

    # Protect long runs: long distance at easy effort stays long
    is_long_easy = (dist >= 8) & (zone <= 3)

    # Promote moderate/easy to hard_effort if high HR effort
    promotable = (kw_type == "moderate") | (kw_type == "easy")
    high_effort = (zone >= 4) | (z4_z5_frac >= 0.40)
    blended.loc[promotable & high_effort & ~is_long_easy] = "hard_effort"

    # moderate (default) → downgrade to easy if low HR (only if not already promoted)
    still_mod = blended == "moderate"
    blended.loc[still_mod & (zone <= 2)] = "easy"

    df.loc[mask, "run_type"] = blended
    return df


# ---------------------------------------------------------------------------
# Full enrichment pipeline
# ---------------------------------------------------------------------------

_ZONE_CACHE_FILE = ".zone_times_cache.json"


def _load_zone_cache(export_dir) -> dict:
    """Load cached zone times from disk. Returns {filename: {zone_1_s: ..., ...}, ...}."""
    import json
    cache_path = export_dir / _ZONE_CACHE_FILE
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_zone_cache(export_dir, cache: dict, max_hr: int, zone_pct: list[int]) -> None:
    """Write zone times cache to disk, including zone config for invalidation."""
    import json
    cache_path = export_dir / _ZONE_CACHE_FILE
    payload = {"max_hr": max_hr, "zone_pct": zone_pct, "activities": cache}
    with open(cache_path, "w") as f:
        json.dump(payload, f)


def _compute_zone_times(df: pd.DataFrame, export_dir, max_hr: int, zone_pct: list[int]) -> pd.DataFrame:
    """Compute per-second time-in-zone from FIT HR streams.

    Adds zone_1_s .. zone_5_s columns (seconds spent in each zone per activity).
    Results are cached to disk; only new activities are parsed on subsequent runs.
    Cache is invalidated when max_hr or zone boundaries change.
    """
    from .routes import parse_hr_stream

    boundaries = [max_hr * p / 100 for p in zone_pct]

    for col in [f"zone_{z}_s" for z in range(1, 6)]:
        df[col] = np.nan

    if export_dir is None or "filename" not in df.columns:
        return df

    from pathlib import Path
    export_dir = Path(export_dir)

    # Load cache; invalidate if zone config changed
    raw_cache = _load_zone_cache(export_dir)
    if isinstance(raw_cache, dict) and raw_cache.get("max_hr") == max_hr and raw_cache.get("zone_pct") == zone_pct:
        cache = raw_cache.get("activities", {})
    else:
        cache = {}
        logger.info("Zone cache invalidated (zone config changed)")

    processed = 0
    cache_hits = 0

    for idx, row in df.iterrows():
        fn = row.get("filename")
        if not isinstance(fn, str) or not fn.strip():
            continue

        # Use cached result if available
        if fn in cache:
            cached = cache[fn]
            for z in range(1, 6):
                df.at[idx, f"zone_{z}_s"] = cached[f"zone_{z}_s"]
            cache_hits += 1
            continue

        fit_path = export_dir / fn
        points = parse_hr_stream(fit_path)
        if len(points) < 2:
            continue

        zone_secs = [0.0] * 5  # Z1-Z5
        for i in range(1, len(points)):
            ts_prev, _ = points[i - 1]
            ts_curr, hr = points[i]
            dt = (ts_curr - ts_prev).total_seconds()
            if dt <= 0 or dt > 300:  # skip gaps > 5 min (pauses)
                continue
            if hr < boundaries[0]:
                zone_secs[0] += dt
            elif hr < boundaries[1]:
                zone_secs[1] += dt
            elif hr < boundaries[2]:
                zone_secs[2] += dt
            elif hr < boundaries[3]:
                zone_secs[3] += dt
            else:
                zone_secs[4] += dt

        entry = {f"zone_{z}_s": zone_secs[z - 1] for z in range(1, 6)}
        cache[fn] = entry
        for z in range(1, 6):
            df.at[idx, f"zone_{z}_s"] = entry[f"zone_{z}_s"]
        processed += 1

    _save_zone_cache(export_dir, cache, max_hr, zone_pct)
    logger.info("Zone times: parsed %d activities, %d from cache", processed, cache_hits)
    return df


def enrich(df: pd.DataFrame, athlete_config: dict | None = None, export_dir=None) -> pd.DataFrame:
    """Run all enrichment steps on the activity DataFrame."""
    logger.info("Starting enrichment pipeline on %d activities", len(df))
    df = df.copy()

    # Kid detection (vectorized) — check name/description regex AND Strava tag
    combined_text = df["name"].fillna("").astype(str) + " " + df["description"].fillna("").astype(str)
    regex_match = combined_text.str.contains(_KID_RE, na=False)
    strava_tag = pd.Series(False, index=df.index)
    if "strava_with_kid" in df.columns:
        strava_tag = pd.to_numeric(df["strava_with_kid"], errors="coerce").fillna(0) == 1
    df["with_kid"] = regex_match | strava_tag
    logger.info("Kid detection: %d stroller runs found", df["with_kid"].sum())

    # Run type classification (vectorized with np.select)
    runs_mask = df["type"] == "Run"
    df["run_type"] = ""  # default

    if runs_mask.any():
        # Race detection uses NAME only (description catches false positives
        # like "first run since the race" or "training for the marathon")
        name_text = df["name"].fillna("").astype(str).str.lower()
        full_text = (df["name"].fillna("").astype(str) + " " + df["description"].fillna("").astype(str)).str.lower()
        dist = df["distance_mi"].fillna(0)
        pace = df["pace_min_per_mi"]

        conditions = [
            name_text.str.contains(r"race|10k|5k|marathon|trot|dash|frisco", na=False),
            full_text.str.contains(r"interval|tempo|fast|speed|800|fartlek|threshold|time.trial", na=False),
            full_text.str.contains(r"long", na=False) | (dist >= 8),
            full_text.str.contains(r"recovery|shake|shakeout|easy|ruck", na=False) | (dist <= 2.5),
            pace.notna() & (pace >= 12),
        ]
        choices = ["race", "hard_effort", "long", "easy", "easy"]

        df.loc[runs_mask, "run_type"] = np.select(
            [c[runs_mask] for c in conditions],
            choices,
            default="moderate",
        )
    logger.info("Run classification: %s", df[df["type"] == "Run"]["run_type"].value_counts().to_dict())

    # HR adjustment (vectorized)
    adj = pd.Series(0.0, index=df.index)
    temp = df["weather_temp_f"]
    # Heat
    heat_mask = temp.notna() & (temp > _TEMP_NEUTRAL_F)
    adj[heat_mask] = (temp[heat_mask] - _TEMP_NEUTRAL_F) * _HR_PER_DEGREE_F
    # Cold
    cold_mask = temp.notna() & (temp < _TEMP_NEUTRAL_F)
    adj[cold_mask] -= (_TEMP_NEUTRAL_F - temp[cold_mask]) * 0.25
    # Stroller
    adj[df["with_kid"]] += _STROLLER_HR_PENALTY

    df["hr_adjustment"] = adj
    df["adjusted_hr"] = df["avg_hr"] - adj
    # Keep NaN where avg_hr is NaN
    df.loc[df["avg_hr"].isna(), "adjusted_hr"] = np.nan
    df.loc[df["avg_hr"].isna(), "hr_adjustment"] = 0.0
    logger.info("HR adjustment: %d activities adjusted", (df["hr_adjustment"] > 0).sum())

    # HR zones (uses adjusted_hr)
    cfg = athlete_config or {}
    max_hr = cfg.get("max_hr", _DEFAULT_MAX_HR)
    zone_pct = cfg.get("hr_zones_pct", _DEFAULT_ZONE_PCT)
    df["estimated_max_hr"] = max_hr
    df = _compute_hr_zones(df, max_hr, zone_pct)
    has_zones = df["hr_zone"].notna().sum()
    logger.info("HR zones: %d activities zoned (max_hr=%d)", has_zones, max_hr)

    # Per-second zone times from FIT HR streams
    df = _compute_zone_times(df, export_dir, max_hr, zone_pct)

    # Blend keyword + HR zone for more accurate run type
    before = df[df["type"] == "Run"]["run_type"].value_counts().to_dict()
    df = _blend_run_type(df)
    after = df[df["type"] == "Run"]["run_type"].value_counts().to_dict()
    logger.info("Run classification (after HR blending): %s", after)
    changed = {k: after.get(k, 0) - before.get(k, 0) for k in set(list(before) + list(after)) if after.get(k, 0) != before.get(k, 0)}
    if changed:
        logger.info("  Reclassified: %s", changed)

    # Fatigue
    df = compute_fatigue(df)

    # Lifting program mapping
    df = map_lifting_program(df)

    logger.info("Enrichment complete")
    return df
