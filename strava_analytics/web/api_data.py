"""Structured data functions for the REST API and MCP server.

Each function accepts the enriched DataFrame and returns JSON-serializable
dicts/lists suitable for API responses and ChatGPT tool calls.
"""

from datetime import date, timedelta

import pandas as pd

from strava_analytics.web import data
from strava_analytics.metrics import format_pace
from strava_analytics.fitness import detect_prs
from strava_analytics.web.plan_data import get_current_fitness


def get_fitness_summary(df: pd.DataFrame) -> dict:
    """Current fitness snapshot: CTL, ATL, TSB, form status."""
    fitness = get_current_fitness(df)
    fitness["date"] = date.today().isoformat()
    return fitness


def get_lifetime_stats(df: pd.DataFrame) -> dict:
    """Lifetime activity counts, mileage, and date range."""
    runs = df[df["type"] == "Run"]
    lifts = df[df["type"] == "Weight Training"]
    return {
        "total_activities": len(df),
        "total_runs": len(runs),
        "total_lifts": len(lifts),
        "total_miles": round(float(df["distance_mi"].sum()), 1),
        "date_from": df["date"].min().strftime("%Y-%m-%d") if not df.empty else None,
        "date_to": df["date"].max().strftime("%Y-%m-%d") if not df.empty else None,
    }


def get_recent_activities(df: pd.DataFrame, days: int = 14,
                          limit: int = 20) -> list[dict]:
    """Recent activities with key metrics."""
    if df.empty:
        return []
    now = df["date"].max()
    recent = df[df["date"] >= now - pd.Timedelta(days=days)].sort_values(
        "date", ascending=False
    )
    results = []
    for _, row in recent.head(limit).iterrows():
        act = {
            "date": row["date"].strftime("%Y-%m-%d"),
            "type": row.get("type", ""),
            "name": row.get("name", ""),
        }
        for field, key in [("distance_mi", "distance_mi"),
                           ("pace_min_per_mi", "pace"),
                           ("avg_hr", "avg_hr"),
                           ("moving_time_s", "duration_s"),
                           ("elevation_gain_ft", "elevation_ft"),
                           ("run_type", "run_type")]:
            val = row.get(field)
            if val is not None and not pd.isna(val) and val != 0:
                if key == "pace":
                    act[key] = format_pace(val)
                    act["pace_decimal"] = round(float(val), 2)
                else:
                    act[key] = round(float(val), 1) if isinstance(val, float) else val
        results.append(act)
    return results


def get_weekly_mileage(df: pd.DataFrame, weeks: int = 8) -> list[dict]:
    """Weekly running mileage for the last N weeks."""
    runs = df[df["type"] == "Run"]
    if runs.empty:
        return []
    now = runs["date"].max()
    results = []
    for i in range(weeks):
        start = now - pd.Timedelta(weeks=i + 1)
        end = now - pd.Timedelta(weeks=i)
        week_runs = runs[(runs["date"] > start) & (runs["date"] <= end)]
        results.append({
            "week_of": start.strftime("%Y-%m-%d"),
            "miles": round(float(week_runs["distance_mi"].sum()), 1),
        })
    return results


def get_current_1rms(df: pd.DataFrame) -> dict:
    """Current estimated 1RM for each lift."""
    result = {}
    for lift in ["bench", "squat", "deadlift", "ohp"]:
        col = f"{lift}_weight"
        if col in df.columns:
            vals = df[df[col].notna() & (df[col] > 0)][col]
            if not vals.empty:
                result[lift] = round(float(vals.iloc[-1]), 0)
    return result


def get_personal_records(df: pd.DataFrame) -> list[dict]:
    """Personal records across standard distances."""
    efforts_df = data.get_best_efforts()
    prs = detect_prs(df, efforts_df)
    # Ensure all values are JSON-serializable
    clean = []
    for pr in prs:
        clean.append({k: str(v) if not isinstance(v, (int, float, str, bool, type(None))) else v
                      for k, v in pr.items()})
    return clean


def get_detailed_runs(df: pd.DataFrame, limit: int = 30) -> list[dict]:
    """Detailed run history."""
    runs = df[df["type"] == "Run"].sort_values("date", ascending=False)
    if runs.empty:
        return []
    results = []
    for _, row in runs.head(limit).iterrows():
        run = {
            "date": row["date"].strftime("%Y-%m-%d"),
            "name": row.get("name", ""),
            "distance_mi": round(float(row.get("distance_mi", 0) or 0), 2),
        }
        pace = row.get("pace_min_per_mi")
        if pace and not pd.isna(pace) and pace > 0:
            run["pace"] = format_pace(pace)
            run["pace_decimal"] = round(float(pace), 2)
        for field, key in [("avg_hr", "avg_hr"), ("max_hr", "max_hr"),
                           ("elevation_gain_ft", "elevation_ft"),
                           ("moving_time_s", "duration_s"),
                           ("run_type", "run_type"),
                           ("calories", "calories")]:
            val = row.get(field)
            if val is not None and not pd.isna(val) and val != 0:
                run[key] = round(float(val), 1) if isinstance(val, float) else val
        results.append(run)
    return results


def get_detailed_lifts(df: pd.DataFrame, limit: int = 20) -> list[dict]:
    """Detailed lift session history."""
    lifts = df[df["type"] == "Weight Training"].sort_values("date", ascending=False)
    if lifts.empty:
        return []
    results = []
    for _, row in lifts.head(limit).iterrows():
        session = {
            "date": row["date"].strftime("%Y-%m-%d"),
            "name": row.get("name", "Weight Training"),
        }
        for lift in ["bench", "squat", "deadlift", "ohp"]:
            w = row.get(f"{lift}_weight")
            if w and not pd.isna(w) and w > 0:
                session[f"{lift}_lbs"] = round(float(w), 0)
        dur = row.get("moving_time_s")
        if dur and not pd.isna(dur) and dur > 0:
            session["duration_s"] = round(float(dur), 0)
        results.append(session)
    return results


def get_athlete_summary(df: pd.DataFrame) -> dict:
    """Combined overview of all athlete data."""
    return {
        "fitness": get_fitness_summary(df),
        "stats": get_lifetime_stats(df),
        "recent_activities": get_recent_activities(df),
        "weekly_mileage": get_weekly_mileage(df),
        "strength": get_current_1rms(df),
        "personal_records": get_personal_records(df),
    }
