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

# Zone weights: TRIMP-style multipliers per minute in each zone.
# Calibrated so a 30-min easy run ≈ 30-50, a 60-min moderate run ≈ 80-120,
# a hard 10K race ≈ 150-200, a marathon ≈ 250-350.
_ZONE_WEIGHTS = {1: 1.0, 2: 1.5, 3: 2.5, 4: 4.0, 5: 6.0}


def compute_relative_effort_vectorized(df: pd.DataFrame) -> pd.Series:
    """Vectorized relative effort (TRIMP-style) for the full DataFrame.

    Score = sum(zone_minutes * zone_weight). Typical range: 20-300.
    """
    effort = pd.Series(0.0, index=df.index)
    has_data = pd.Series(False, index=df.index)
    for z in range(1, 6):
        col = f"zone_{z}_s"
        if col in df.columns:
            secs = df[col].fillna(0)
            mask = secs > 0
            has_data = has_data | mask
            effort += (secs / 60) * _ZONE_WEIGHTS[z]
    effort[~has_data] = np.nan
    return effort.round(0)


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

# ---------------------------------------------------------------------------
# Best Effort detection (Strava-style: fastest segment within any run)
# ---------------------------------------------------------------------------

_PR_DISTANCES_M = [
    ("1 Mile", 1609.34),
    ("5K", 5000.0),
    ("10K", 10000.0),
    ("Half Marathon", 21097.0),
    ("Marathon", 42195.0),
]

_BEST_EFFORT_CACHE_FILE = ".best_efforts_cache.json"


def _find_best_effort(distance_m: list[float], timestamps: list, target_m: float) -> float | None:
    """Sliding window: find fastest contiguous segment of target_m meters.

    Returns elapsed time in seconds, or None if the run is shorter than target_m.
    """
    if not distance_m or not timestamps or len(distance_m) < 2:
        return None
    total_dist = distance_m[-1] - distance_m[0]
    if total_dist < target_m * 0.95:  # run too short
        return None

    best_time = None
    j = 0
    for i in range(len(distance_m)):
        # Advance j until segment covers target_m
        while j < len(distance_m) - 1 and (distance_m[j] - distance_m[i]) < target_m:
            j += 1
        seg_dist = distance_m[j] - distance_m[i]
        if seg_dist < target_m * 0.98:  # not enough distance
            continue
        # Interpolate to get exact time for target_m
        dt = (timestamps[j] - timestamps[i]).total_seconds()
        if dt <= 0:
            continue
        # Adjust for overshoot
        if seg_dist > target_m and j > 0:
            overshoot = seg_dist - target_m
            speed = seg_dist / dt
            dt -= overshoot / speed if speed > 0 else 0
        if best_time is None or dt < best_time:
            best_time = dt
    return best_time


def compute_best_efforts(df: pd.DataFrame, export_dir) -> pd.DataFrame:
    """Scan FIT files for best efforts at standard distances.

    Returns a DataFrame with columns: distance_label, time_s, pace_min_mi,
    date, name, activity_idx, rank (1-3 per distance).
    Results are cached to disk.
    """
    import json
    from pathlib import Path
    from .routes import parse_distance_stream

    if export_dir is None:
        return pd.DataFrame()
    export_dir = Path(export_dir)

    runs = df[df["type"] == "Run"].copy()
    if runs.empty or "filename" not in runs.columns:
        return pd.DataFrame()

    # Load cache
    cache_path = export_dir / _BEST_EFFORT_CACHE_FILE
    cache = {}
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    # For each run, find best effort at each distance
    all_efforts = []
    for idx, row in runs.iterrows():
        fn = row.get("filename", "")
        if not isinstance(fn, str) or not fn.strip():
            continue
        # Only parse FIT.gz files (skip GPX, TCX, etc.)
        if not fn.lower().endswith(".fit.gz"):
            continue

        # Check cache
        if fn in cache:
            for eff in cache[fn]:
                eff["date"] = row["date"]
                eff["name"] = row.get("name", "")
                eff["activity_idx"] = idx
                all_efforts.append(eff)
            continue

        fit_path = export_dir / fn
        points = parse_distance_stream(fit_path)
        if len(points) < 10:
            cache[fn] = []
            continue

        timestamps = [p[0] for p in points]
        distance_m = [p[1] for p in points]

        file_efforts = []
        for label, target_m in _PR_DISTANCES_M:
            time_s = _find_best_effort(distance_m, timestamps, target_m)
            if time_s is not None and time_s > 0:
                # Convert to pace (min/mi)
                dist_mi = target_m / 1609.34
                pace = (time_s / 60) / dist_mi
                eff = {"distance_label": label, "time_s": round(time_s, 1),
                       "pace_min_mi": round(pace, 2)}
                file_efforts.append(eff)

        cache[fn] = [{"distance_label": e["distance_label"],
                       "time_s": e["time_s"], "pace_min_mi": e["pace_min_mi"]}
                      for e in file_efforts]

        for eff in file_efforts:
            eff["date"] = row["date"]
            eff["name"] = row.get("name", "")
            eff["activity_idx"] = idx
            all_efforts.append(eff)

    # Save cache
    try:
        with open(cache_path, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass

    if not all_efforts:
        return pd.DataFrame()

    edf = pd.DataFrame(all_efforts)

    # Rank within each distance (top 3)
    edf = edf.sort_values(["distance_label", "pace_min_mi"])
    edf["rank"] = edf.groupby("distance_label").cumcount() + 1

    return edf


def _format_effort_time(seconds: float) -> str:
    """Format seconds to H:MM:SS or M:SS."""
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}:{s:02d}"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


def detect_prs(df: pd.DataFrame, efforts_df: pd.DataFrame | None = None) -> list[dict]:
    """Find best efforts across standard distances using FIT stream data.

    Pass pre-computed efforts_df from compute_best_efforts() to avoid
    re-parsing FIT files on every page load.
    Falls back to overall-pace matching when FIT data isn't available.
    Returns list of dicts with top-3 efforts per distance.
    """
    if efforts_df is None or efforts_df.empty:
        # Fallback: use overall pace for runs near the target distance
        return _detect_prs_fallback(df)

    now = df[df["type"] == "Run"]["date"].max()
    year_start = pd.Timestamp(now.year, 1, 1)
    prs = []

    for label, _ in _PR_DISTANCES_M:
        dist_efforts = efforts_df[efforts_df["distance_label"] == label].copy()
        if dist_efforts.empty:
            continue

        top3 = dist_efforts[dist_efforts["rank"] <= 3]

        # All-time best
        best = top3.iloc[0]
        best_time = _format_effort_time(best["time_s"])
        best_pace = format_pace(best["pace_min_mi"])

        # This year's best
        year_efforts = dist_efforts[dist_efforts["date"] >= year_start]
        year_best = None
        if not year_efforts.empty:
            yr = year_efforts.iloc[0]
            year_best = {
                "time": _format_effort_time(yr["time_s"]),
                "pace": format_pace(yr["pace_min_mi"]),
                "date": yr["date"].strftime("%b %d, %Y"),
                "name": yr.get("name", ""),
            }

        prs.append({
            "distance": label,
            "best_time": best_time,
            "best_pace": best_pace,
            "best_date": best["date"].strftime("%b %d, %Y"),
            "best_name": best.get("name", ""),
            "year_best": year_best,
            "top3": [
                {
                    "rank": int(r["rank"]),
                    "time": _format_effort_time(r["time_s"]),
                    "pace": format_pace(r["pace_min_mi"]),
                    "date": r["date"].strftime("%b %d, %Y"),
                    "name": r.get("name", ""),
                }
                for _, r in top3.iterrows()
            ],
        })

    return prs


def _detect_prs_fallback(df: pd.DataFrame) -> list[dict]:
    """Fallback PR detection using overall pace (no FIT data)."""
    runs = df[df["type"] == "Run"].copy()
    if runs.empty:
        return []

    now = runs["date"].max()
    year_start = pd.Timestamp(now.year, 1, 1)

    fallback_bands = [
        ("1 Mile", 0.95, 1.15),
        ("5K", 2.9, 3.3),
        ("10K", 5.9, 6.5),
        ("Half Marathon", 12.8, 13.5),
        ("Marathon", 25.8, 26.8),
    ]
    prs = []
    for label, lo, hi in fallback_bands:
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
                "time": "",
                "pace": format_pace(yr["pace_min_per_mi"]),
                "date": yr["date"].strftime("%b %d, %Y"),
                "name": yr.get("name", ""),
            }
        prs.append({
            "distance": label,
            "best_time": "",
            "best_pace": format_pace(best["pace_min_per_mi"]),
            "best_date": best["date"].strftime("%b %d, %Y"),
            "best_name": best.get("name", ""),
            "year_best": year_best,
            "top3": [],
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
