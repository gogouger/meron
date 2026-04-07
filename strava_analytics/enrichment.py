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
        "program_day", "bench_weight", "bench_volume",
        "squat_weight", "squat_volume", "deadlift_weight", "deadlift_volume",
        "ohp_weight", "ohp_volume", "pullup_sets", "pullup_reps",
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
# Full enrichment pipeline
# ---------------------------------------------------------------------------

def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Run all enrichment steps on the activity DataFrame."""
    logger.info("Starting enrichment pipeline on %d activities", len(df))
    df = df.copy()

    # Kid detection (vectorized)
    combined_text = df["name"].fillna("").astype(str) + " " + df["description"].fillna("").astype(str)
    df["with_kid"] = combined_text.str.contains(_KID_RE, na=False)
    logger.info("Kid detection: %d stroller runs found", df["with_kid"].sum())

    # Run type classification (vectorized with np.select)
    runs_mask = df["type"] == "Run"
    df["run_type"] = ""  # default

    if runs_mask.any():
        text = (df["name"].fillna("").astype(str) + " " + df["description"].fillna("").astype(str)).str.lower()
        dist = df["distance_mi"].fillna(0)
        pace = df["pace_min_per_mi"]

        conditions = [
            text.str.contains(r"race|10k|5k|marathon|trot|dash|frisco", na=False),
            text.str.contains(r"interval|tempo|fast|speed|800", na=False),
            text.str.contains(r"ruck", na=False),
            text.str.contains(r"long", na=False) | (dist >= 8),
            text.str.contains(r"recovery|shake|shakeout|easy", na=False),
            dist <= 2.5,
            pace.notna() & (pace >= 12),
        ]
        choices = ["race", "workout", "ruck", "long", "easy", "short/easy", "easy"]

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

    # Fatigue
    df = compute_fatigue(df)

    # Lifting program mapping
    df = map_lifting_program(df)

    logger.info("Enrichment complete")
    return df
