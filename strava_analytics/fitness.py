"""Fitness & Freshness model (Banister impulse-response) and trend analysis.

Provides:
- Fitness/Freshness time series (CTL/ATL/TSB) — already computed in enrichment,
  this module adds higher-level aggregations.
- Relative Effort score per activity (HR zone-weighted intensity).
- Trend comparison (recent 90d vs prior 365d).
- Personal records detection across standard distances.
"""

import numpy as np
import pandas as pd

from .metrics import format_pace


# ---------------------------------------------------------------------------
# Relative Effort (Suffer Score)
# ---------------------------------------------------------------------------

# Zone weights: time in higher zones counts more. Based on Strava's model.
_ZONE_WEIGHTS = {1: 25, 2: 60, 3: 115, 4: 200, 5: 300}


def compute_relative_effort(row: pd.Series) -> float:
    """Compute a single Relative Effort score from per-second zone times.

    Returns a score roughly in 0-300 range for typical runs.
    Score = sum(zone_seconds * zone_weight) / 60.
    """
    total = 0.0
    has_zone_data = False
    for z in range(1, 6):
        col = f"zone_{z}_s"
        secs = row.get(col, 0)
        if pd.notna(secs) and secs > 0:
            has_zone_data = True
            total += secs * _ZONE_WEIGHTS[z]
    if not has_zone_data:
        return np.nan
    return round(total / 60, 1)


def compute_relative_effort_vectorized(df: pd.DataFrame) -> pd.Series:
    """Vectorized relative effort for the full DataFrame."""
    effort = pd.Series(0.0, index=df.index)
    has_data = pd.Series(False, index=df.index)
    for z in range(1, 6):
        col = f"zone_{z}_s"
        if col in df.columns:
            secs = df[col].fillna(0)
            mask = secs > 0
            has_data = has_data | mask
            effort += secs * _ZONE_WEIGHTS[z]
    effort = effort / 60
    effort[~has_data] = np.nan
    return effort.round(1)


# ---------------------------------------------------------------------------
# Trends: 90-day vs 365-day comparison
# ---------------------------------------------------------------------------

def compute_trends(df: pd.DataFrame) -> list[dict]:
    """Compare recent 90 days vs prior 365 days for key metrics.

    Returns a list of dicts with: metric, recent, baseline, direction, delta_pct.
    """
    runs = df[df["type"] == "Run"].copy()
    if runs.empty:
        return []

    now = runs["date"].max()
    cutoff_90 = now - pd.Timedelta(days=90)
    cutoff_365 = now - pd.Timedelta(days=365)

    recent = runs[runs["date"] >= cutoff_90]
    baseline = runs[(runs["date"] >= cutoff_365) & (runs["date"] < cutoff_90)]

    if recent.empty or baseline.empty:
        return []

    # Normalize to per-week
    recent_weeks = max((recent["date"].max() - recent["date"].min()).days / 7, 1)
    baseline_weeks = max((baseline["date"].max() - baseline["date"].min()).days / 7, 1)

    metrics = []

    def _add(name, recent_val, baseline_val, unit, lower_is_better=False, fmt=None):
        if pd.isna(recent_val) or pd.isna(baseline_val) or baseline_val == 0:
            return
        delta_pct = (recent_val - baseline_val) / abs(baseline_val) * 100
        if lower_is_better:
            direction = "improving" if delta_pct < 0 else "declining"
        else:
            direction = "improving" if delta_pct > 0 else "declining"
        metrics.append({
            "metric": name,
            "recent": fmt(recent_val) if fmt else f"{recent_val:.1f}",
            "baseline": fmt(baseline_val) if fmt else f"{baseline_val:.1f}",
            "unit": unit,
            "delta_pct": round(delta_pct, 1),
            "direction": direction,
        })

    # Weekly mileage
    _add("Weekly Miles",
         recent["distance_mi"].sum() / recent_weeks,
         baseline["distance_mi"].sum() / baseline_weeks,
         "mi/wk")

    # Average pace (lower is better)
    _add("Avg Pace",
         recent["pace_min_per_mi"].mean(),
         baseline["pace_min_per_mi"].mean(),
         "/mi", lower_is_better=True, fmt=format_pace)

    # Average HR (lower at same pace = better, but context-dependent)
    if recent["avg_hr"].notna().any() and baseline["avg_hr"].notna().any():
        _add("Avg HR",
             recent["avg_hr"].mean(),
             baseline["avg_hr"].mean(),
             "bpm", lower_is_better=True)

    # Runs per week
    _add("Runs/Week",
         len(recent) / recent_weeks,
         len(baseline) / baseline_weeks,
         "runs/wk")

    # Longest run
    _add("Longest Run",
         recent["distance_mi"].max(),
         baseline["distance_mi"].max(),
         "mi")

    return metrics


# ---------------------------------------------------------------------------
# Personal Records by distance
# ---------------------------------------------------------------------------

_PR_DISTANCES = [
    ("1 Mile", 0.9, 1.1),
    ("5K", 2.9, 3.3),
    ("10K", 5.9, 6.5),
    ("Half Marathon", 12.8, 13.5),
    ("Marathon", 25.8, 26.8),
]


def detect_prs(df: pd.DataFrame) -> list[dict]:
    """Find best pace for standard race distances.

    Returns list of {distance, best_pace, best_date, best_name, year_pace, year_date}.
    """
    runs = df[df["type"] == "Run"].copy()
    if runs.empty:
        return []

    now = runs["date"].max()
    year_start = pd.Timestamp(now.year, 1, 1)
    prs = []

    for label, lo, hi in _PR_DISTANCES:
        band = runs[(runs["distance_mi"] >= lo) & (runs["distance_mi"] <= hi)]
        if band.empty:
            continue

        best_idx = band["pace_min_per_mi"].idxmin()
        best = band.loc[best_idx]

        year_band = band[band["date"] >= year_start]
        year_best = None
        if not year_band.empty:
            yr_idx = year_band["pace_min_per_mi"].idxmin()
            yr = year_band.loc[yr_idx]
            year_best = {
                "pace": format_pace(yr["pace_min_per_mi"]),
                "date": yr["date"].strftime("%b %d, %Y"),
                "name": yr.get("name", ""),
            }

        prs.append({
            "distance": label,
            "best_pace": format_pace(best["pace_min_per_mi"]),
            "best_date": best["date"].strftime("%b %d, %Y"),
            "best_name": best.get("name", ""),
            "year_best": year_best,
        })

    return prs


# ---------------------------------------------------------------------------
# Year in Review
# ---------------------------------------------------------------------------

def year_summary(df: pd.DataFrame, year: int | None = None) -> dict:
    """Annual stats summary for a given year (defaults to most recent)."""
    if df.empty:
        return {}

    if year is None:
        year = df["date"].max().year

    ydf = df[df["date"].dt.year == year]
    if ydf.empty:
        return {}

    runs = ydf[ydf["type"] == "Run"]
    lifts = ydf[ydf["type"] == "Weight Training"]

    summary = {
        "year": year,
        "total_activities": len(ydf),
        "total_miles": round(ydf["distance_mi"].sum(), 1),
        "total_hours": round(ydf["moving_time_s"].sum() / 3600, 1),
        "total_elevation_ft": round(ydf["elevation_gain_ft"].sum()),
        "total_calories": round(ydf["calories"].sum()),
        "total_runs": len(runs),
        "total_lifts": len(lifts),
        "active_days": ydf["date"].dt.date.nunique(),
    }

    if not runs.empty:
        summary["run_miles"] = round(runs["distance_mi"].sum(), 1)
        summary["avg_pace"] = format_pace(runs["pace_min_per_mi"].mean())
        summary["best_pace"] = format_pace(runs["pace_min_per_mi"].min())
        summary["longest_run"] = round(runs["distance_mi"].max(), 1)
        summary["avg_run_distance"] = round(runs["distance_mi"].mean(), 1)

    # Monthly breakdown
    monthly = []
    for m in range(1, 13):
        mdf = ydf[ydf["date"].dt.month == m]
        if mdf.empty:
            monthly.append({"month": m, "activities": 0, "miles": 0})
        else:
            monthly.append({
                "month": m,
                "activities": len(mdf),
                "miles": round(mdf["distance_mi"].sum(), 1),
            })
    summary["monthly"] = monthly

    return summary


# ---------------------------------------------------------------------------
# Weekly training load (intensity-weighted)
# ---------------------------------------------------------------------------

def weekly_training_load(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly training load (sum of training_stress) with trend line."""
    if "training_stress" not in df.columns:
        return pd.DataFrame()

    weekly = df.groupby("week").agg(
        load=("training_stress", "sum"),
        activities=("training_stress", "count"),
    ).reset_index()
    weekly["trend"] = weekly["load"].rolling(4, min_periods=1).mean()
    return weekly
