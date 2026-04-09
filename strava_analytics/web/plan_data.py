"""Data service functions for the training plan page.

Provides pre-computed data for charts and metrics on the /plan page.
All functions accept the enriched DataFrame and return chart-ready data.

Includes Banister fitness-fatigue model fitting and plan outcome projections:
  p(t) = p0 + k1 × CTL(t) - k2 × ATL(t)
  Banister et al. (1975), with defaults from literature when insufficient data.
"""

from datetime import date, timedelta
import logging
import math

import numpy as np
import pandas as pd

from strava_analytics.critical_speed import (
    fit_critical_speed, predict_time_cs, predict_race_times, tanda_marathon,
)
from strava_analytics.predictions import estimate_1rm, extract_1rm_progression
from strava_analytics.strength_model import (
    fit_all_lifts, project_1rm, compute_interference,
)
from strava_analytics.training_plan import generate_training_plan, plan_to_flat_list

logger = logging.getLogger(__name__)


def get_fitness_timeseries(df: pd.DataFrame, days: int = 90) -> pd.DataFrame:
    """Daily CTL/ATL/TSB time series for the last N days.

    Returns DataFrame with columns: date, ctl, atl, tsb.
    """
    if df.empty or "chronic_load_28d" not in df.columns:
        return pd.DataFrame(columns=["date", "ctl", "atl", "tsb"])

    now = df["date"].max()
    cutoff = now - pd.Timedelta(days=days)
    recent = df[df["date"] >= cutoff].copy()

    # Aggregate to daily (take max per day for load values)
    daily = recent.groupby(recent["date"].dt.date).agg(
        ctl=("chronic_load_28d", "last"),
        atl=("acute_load_7d", "last"),
        tsb=("freshness", "last"),
    ).reset_index()
    daily.columns = ["date", "ctl", "atl", "tsb"]
    daily["date"] = pd.to_datetime(daily["date"])
    return daily.sort_values("date")


def get_current_fitness(df: pd.DataFrame) -> dict:
    """Current fitness snapshot: CTL, ATL, TSB, freshness label."""
    if df.empty or "chronic_load_28d" not in df.columns:
        return {"ctl": 0, "atl": 0, "tsb": 0, "label": "Unknown"}

    latest = df.sort_values("date").iloc[-1]
    ctl = latest.get("chronic_load_28d", 0) or 0
    atl = latest.get("acute_load_7d", 0) or 0
    tsb = latest.get("freshness", 0) or 0
    label = latest.get("fatigue_level", "Unknown")

    return {
        "ctl": round(float(ctl), 1),
        "atl": round(float(atl), 1),
        "tsb": round(float(tsb), 1),
        "label": str(label),
    }


def get_mileage_progression(df: pd.DataFrame,
                             plan_weeks: list) -> pd.DataFrame:
    """Actual weekly miles vs planned target per week.

    Returns DataFrame with: week_num, planned_miles, actual_miles, start_date.
    """
    rows = []
    runs = df[df["type"] == "Run"].copy() if not df.empty else pd.DataFrame()

    for week in plan_weeks:
        start = pd.Timestamp(week.start_date)
        end = start + pd.Timedelta(days=6, hours=23, minutes=59)

        actual = 0.0
        if not runs.empty:
            week_runs = runs[(runs["date"] >= start) & (runs["date"] <= end)]
            actual = week_runs["distance_mi"].sum()

        rows.append({
            "week_num": week.week_num,
            "phase": week.phase,
            "planned_miles": round(week.target_miles, 1),
            "actual_miles": round(actual, 1),
            "start_date": week.start_date,
        })

    return pd.DataFrame(rows)


def get_1rm_trends(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """1RM progression for each lift. Returns dict of lift→DataFrame."""
    results = {}
    for lift in ["bench", "squat", "deadlift", "ohp"]:
        prog = extract_1rm_progression(df, lift)
        if not prog.empty:
            results[lift] = prog
    return results


def get_projected_fitness(df: pd.DataFrame,
                           plan_weeks: list,
                           tau_ctl: float = 42.0,
                           tau_atl: float = 7.0) -> pd.DataFrame:
    """Project CTL/ATL/TSB forward through remaining plan weeks.

    Uses exponential decay model with estimated daily training stress
    from the plan.

    Returns DataFrame with: date, ctl, atl, tsb, projected (bool).
    """
    if df.empty or "chronic_load_28d" not in df.columns:
        return pd.DataFrame()

    # Get current CTL/ATL as starting point
    latest = df.sort_values("date").iloc[-1]
    current_ctl = float(latest.get("chronic_load_28d", 0) or 0)
    current_atl = float(latest.get("acute_load_7d", 0) or 0)
    today = latest["date"].date() if hasattr(latest["date"], "date") else latest["date"]

    # Build historical series (last 60 days)
    historical = get_fitness_timeseries(df, days=60)
    historical["projected"] = False

    # Estimate daily stress from plan workouts
    flat = plan_to_flat_list(plan_weeks)
    stress_by_date = {}
    for row in flat:
        d = row["date"]
        if hasattr(d, "date"):
            d = d.date() if callable(d.date) else d
        intensity_map = {"easy": 30, "moderate": 60, "hard": 90, "race": 120}
        stress = intensity_map.get(row.get("intensity", "easy"), 40)
        if row.get("type") in ("rest", "mobility"):
            stress = 5
        stress_by_date[d] = stress_by_date.get(d, 0) + stress

    # Project forward from today
    ctl = current_ctl
    atl = current_atl
    projected_rows = []

    last_plan_date = max(stress_by_date.keys()) if stress_by_date else today
    projection_end = last_plan_date + timedelta(days=3)

    d = today + timedelta(days=1)
    while d <= projection_end:
        daily_stress = stress_by_date.get(d, 0)
        ctl = ctl + (daily_stress - ctl) / tau_ctl
        atl = atl + (daily_stress - atl) / tau_atl
        tsb = ctl - atl

        projected_rows.append({
            "date": pd.Timestamp(d),
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(tsb, 1),
            "projected": True,
        })
        d += timedelta(days=1)

    projected = pd.DataFrame(projected_rows)
    if historical.empty:
        return projected
    return pd.concat([historical, projected], ignore_index=True).sort_values("date")


def get_race_readiness(df: pd.DataFrame,
                        plan_weeks: list,
                        race_dates: list[date]) -> list[dict]:
    """Projected fitness/fatigue/form at each race date.

    Returns list of dicts with: race_date, ctl, atl, tsb, readiness_label.
    """
    projected = get_projected_fitness(df, plan_weeks)
    if projected.empty:
        return []

    results = []
    for rd in race_dates:
        rd_ts = pd.Timestamp(rd)
        # Find closest projected date
        closest = projected.iloc[(projected["date"] - rd_ts).abs().argsort()[:1]]
        if closest.empty:
            continue
        row = closest.iloc[0]
        tsb = float(row["tsb"])

        if tsb > 10:
            label = "Peak Form"
        elif tsb > 0:
            label = "Good Form"
        elif tsb > -10:
            label = "Neutral"
        else:
            label = "Fatigued"

        results.append({
            "race_date": rd,
            "ctl": round(float(row["ctl"]), 1),
            "atl": round(float(row["atl"]), 1),
            "tsb": round(tsb, 1),
            "readiness_label": label,
        })

    return results


def get_compliance(df: pd.DataFrame, plan_rows: list[dict]) -> dict:
    """Match past plan dates to actual logged activities.

    Returns: {
        total_planned: int,
        total_completed: int,
        pct: float,
        by_date: [{date, planned_type, planned_title, completed: bool, actual_type}]
    }
    """
    today = date.today()
    past_plan = [r for r in plan_rows if r["date"] <= today]
    if not past_plan:
        return {"total_planned": 0, "total_completed": 0, "pct": 0, "by_date": []}

    type_map = {
        "lift": "Weight Training",
        "run": "Run",
        "rest": None,
        "mobility": None,
        "obstacle": "Weight Training",
    }

    by_date = []
    completed = 0
    for row in past_plan:
        planned_type = row["type"]
        if planned_type in ("rest", "mobility"):
            completed += 1
            by_date.append({
                "date": row["date"],
                "planned_type": planned_type,
                "planned_title": row["title"],
                "completed": True,
                "actual_type": planned_type,
            })
            continue

        expected = type_map.get(planned_type)
        d = row["date"]
        d_ts = pd.Timestamp(d)
        day_activities = df[df["date"].dt.date == (d if isinstance(d, date) else d.date())]
        found = False
        actual_type = ""
        if expected and not day_activities.empty:
            matches = day_activities[day_activities["type"] == expected]
            if not matches.empty:
                found = True
                actual_type = expected

        if found:
            completed += 1

        by_date.append({
            "date": d,
            "planned_type": planned_type,
            "planned_title": row["title"],
            "completed": found,
            "actual_type": actual_type,
        })

    total = len(past_plan)
    return {
        "total_planned": total,
        "total_completed": completed,
        "pct": round(completed / total * 100, 1) if total > 0 else 0,
        "by_date": by_date,
    }


# ---------------------------------------------------------------------------
# Banister performance model fitting
# ---------------------------------------------------------------------------
#
# p(t) = p0 + k1 * CTL(t) - k2 * ATL(t)
#
# Default k1, k2 from literature (Banister 1975, Busso 2003):
#   k1 = 1.0, k2 = 2.0, tau1 = 42, tau2 = 7
# When we have >= 3 race results with CTL/ATL data, fit k1/k2 via least squares.

def fit_banister_params(df: pd.DataFrame) -> dict:
    """Legacy — kept for backward compatibility but no longer used for projections."""
    """Fit Banister performance model parameters from race history.

    Returns: {p0, k1, k2, n_races, fitted: bool}
    """
    if df.empty or "chronic_load_28d" not in df.columns:
        return {"p0": 0, "k1": _DEFAULT_K1, "k2": _DEFAULT_K2,
                "n_races": 0, "fitted": False}

    races = df[(df["type"] == "Run") &
               (df.get("run_type", pd.Series("", index=df.index)) == "race")].copy()
    if "run_type" not in races.columns or races.empty:
        races = df[(df["type"] == "Run") &
                   (df["distance_mi"] >= 3.0)].copy()

    if races.empty:
        return {"p0": 0, "k1": _DEFAULT_K1, "k2": _DEFAULT_K2,
                "n_races": 0, "fitted": False}

    # Extract race performance as 5K-equivalent time (VDOT → time)
    perf_data = []
    for _, r in races.iterrows():
        dist_m = r.get("distance_m", 0)
        time_s = r.get("moving_time_s", 0)
        ctl = r.get("chronic_load_28d")
        atl = r.get("acute_load_7d")
        if dist_m > 0 and time_s > 0 and pd.notna(ctl) and pd.notna(atl):
            vdot = daniels_vdot(dist_m, time_s / 60.0)
            equiv_5k_min = vdot_to_race_time(vdot, 5000)
            perf_data.append({"time_min": equiv_5k_min, "ctl": ctl, "atl": atl})

    n = len(perf_data)
    if n < 5:
        # Not enough data to fit reliably — use defaults
        p0 = perf_data[0]["time_min"] if perf_data else 0
        return {"p0": p0, "k1": _DEFAULT_K1, "k2": _DEFAULT_K2,
                "n_races": n, "fitted": False,
                "ctl_mean": 1.0, "atl_mean": 1.0}

    # Normalize CTL/ATL to 0-1 range so fitted k1/k2 are in units of minutes
    ctl_mean = np.mean([d["ctl"] for d in perf_data]) or 1.0
    atl_mean = np.mean([d["atl"] for d in perf_data]) or 1.0

    # Least squares: time_min = p0 - k1 * (CTL/ctl_mean) + k2 * (ATL/atl_mean)
    from numpy.linalg import lstsq
    A = np.array([[-d["ctl"] / ctl_mean, d["atl"] / atl_mean, 1.0]
                  for d in perf_data])
    b = np.array([d["time_min"] for d in perf_data])
    result, _, _, _ = lstsq(A, b, rcond=None)
    k1_fit, k2_fit, p0_fit = result

    # Sanity check: k1, k2 should be positive (fitness helps, fatigue hurts)
    k1_fit = max(0.1, k1_fit)
    k2_fit = max(0.1, k2_fit)

    return {"p0": round(p0_fit, 2), "k1": round(k1_fit, 4), "k2": round(k2_fit, 4),
            "n_races": n, "fitted": True,
            "ctl_mean": round(ctl_mean, 2), "atl_mean": round(atl_mean, 2)}


# ---------------------------------------------------------------------------
# Plan outcome projections
# ---------------------------------------------------------------------------

# Banister TRIMP estimates for planned workout intensities
# (normalized so 1h@LT ≈ 100, matching our enrichment.py convention)
_PLAN_STRESS_MAP = {
    "easy": 30,
    "moderate": 60,
    "hard": 90,
    "race": 120,
}


def project_race_outcomes(
    df: pd.DataFrame,
    plan_weeks: list,
    best_efforts_df: pd.DataFrame | None = None,
) -> dict:
    """Project race time outcomes through the training plan.

    Uses Critical Speed model for current predictions, then applies
    evidence-based taper improvement (Mujika 2003: 2-3%).

    Returns: {distance_label: {current_min, projected_min, delta_pct, method}}
    """
    if best_efforts_df is None or best_efforts_df.empty:
        return {}

    # Current predictions from CS model
    runs = df[df["type"] == "Run"] if not df.empty else pd.DataFrame()
    recent_8w = runs[runs["date"] >= runs["date"].max() - pd.Timedelta(weeks=8)] if not runs.empty else pd.DataFrame()
    weekly_km = recent_8w["distance_mi"].sum() / 8 * 1.60934 if not recent_8w.empty else 0
    avg_pace_spk = recent_8w["pace_min_per_mi"].mean() * 60 / 1.60934 if not recent_8w.empty else 0

    cs_preds = predict_race_times(best_efforts_df, weekly_km=weekly_km,
                                   avg_pace_sec_per_km=avg_pace_spk)

    # Taper improvement: Mujika & Padilla (2003): 2-3% from proper taper
    # Count taper + race weeks in the plan
    taper_weeks = sum(1 for w in plan_weeks if w.phase in ("taper", "race"))
    taper_bonus_pct = min(3.0, taper_weeks * 1.0) if taper_weeks > 0 else 0

    # Build phase mileage increase → modest fitness gain
    build_weeks = sum(1 for w in plan_weeks if w.phase.startswith("build"))
    build_bonus_pct = min(2.0, build_weeks * 0.3)

    improvement_pct = taper_bonus_pct + build_bonus_pct

    results = {}
    for label, pred in cs_preds.items():
        if label.startswith("_"):
            continue
        if pred["time_s"] <= 0:
            continue
        current_min = pred["time_s"] / 60.0
        projected_min = current_min * (1 - improvement_pct / 100)

        results[label] = {
            "current_min": round(current_min, 2),
            "projected_min": round(projected_min, 2),
            "delta_pct": round(-improvement_pct, 1),
            "method": f"Critical Speed + {taper_bonus_pct:.0f}% taper + {build_bonus_pct:.1f}% build",
        }

    return results


def project_1rm_outcomes(
    df: pd.DataFrame,
    plan_weeks: list,
    current_1rms: dict,
) -> dict:
    """Project 1RM outcomes using log-curve fit with interference.

    Uses the strength_model log-curve for progression rate, discounted
    by concurrent training interference from planned running volume.
    """
    if not current_1rms:
        return {}

    # Fit log-curves from historical data
    lift_fits = fit_all_lifts(df)

    # Compute interference from planned running
    build_weeks = [w for w in plan_weeks if w.phase.startswith("build")]
    avg_planned_miles = (sum(w.target_miles for w in build_weeks) / len(build_weeks)
                         if build_weeks else 17.0)
    interference = compute_interference(avg_planned_miles)

    # Count build weeks (where active lifting happens)
    n_build = sum(1 for w in plan_weeks if w.phase.startswith("build"))

    results = {}
    for lift, current in current_1rms.items():
        fit = lift_fits.get(lift)
        if fit and fit["n_points"] >= 3:
            projected = project_1rm(fit, weeks_ahead=n_build,
                                     interference_factor=interference)
            cur_r = round(fit["current_1rm"])
            proj_r = round(projected)
            delta_pct = (proj_r - cur_r) / cur_r * 100 if cur_r > 0 else 0
            results[lift] = {
                "current": cur_r,
                "projected": proj_r,
                "delta_pct": round(delta_pct, 1),
            }
        else:
            # Fallback: simple +2%/week during build, with interference
            projected = current * (1 + 0.02 * interference) ** n_build
            cur_r = round(current)
            proj_r = round(projected)
            delta_pct = (proj_r - cur_r) / cur_r * 100 if cur_r > 0 else 0
            results[lift] = {
                "current": cur_r,
                "projected": proj_r,
                "delta_pct": round(delta_pct, 1),
            }

    return results


def get_plan_projections(
    df: pd.DataFrame,
    plan_weeks: list,
    current_1rms: dict,
    best_efforts_df: pd.DataFrame | None = None,
) -> dict:
    """Combined race and strength projections for the plan page.

    Uses Critical Speed model for race predictions and log-curve with
    interference for strength predictions.
    """
    return {
        "race_projections": project_race_outcomes(df, plan_weeks, best_efforts_df),
        "strength_projections": project_1rm_outcomes(df, plan_weeks, current_1rms),
    }
