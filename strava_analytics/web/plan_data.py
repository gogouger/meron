"""Data service functions for the training plan page.

Provides pre-computed data for charts and metrics on the /plan page.
All functions accept the enriched DataFrame and return chart-ready data.
"""

from datetime import date, timedelta
import math

import numpy as np
import pandas as pd

from strava_analytics.predictions import estimate_1rm, extract_1rm_progression
from strava_analytics.training_plan import generate_training_plan, plan_to_flat_list


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
