"""Compute summaries and metrics from Strava activity data."""

import pandas as pd


def format_pace(pace_min: float) -> str:
    """Convert decimal minutes to MM:SS string."""
    if pd.isna(pace_min) or pace_min <= 0:
        return "--"
    minutes = int(pace_min)
    seconds = int((pace_min - minutes) * 60)
    return f"{minutes}:{seconds:02d}"


def format_duration(minutes: float) -> str:
    """Convert minutes to human-readable HH:MM or MM:SS."""
    if pd.isna(minutes):
        return "--"
    if minutes >= 60:
        h = int(minutes // 60)
        m = int(minutes % 60)
        return f"{h}h {m:02d}m"
    m = int(minutes)
    s = int((minutes - m) * 60)
    return f"{m}m {s:02d}s"


def overall_summary(df: pd.DataFrame) -> dict:
    """High-level summary across all activities."""
    date_range_days = (df["date"].max() - df["date"].min()).days
    return {
        "total_activities": len(df),
        "date_range": f"{df['date'].min():%b %d, %Y} - {df['date'].max():%b %d, %Y}",
        "active_days": df["date"].dt.date.nunique(),
        "span_days": date_range_days,
        "total_distance_mi": df["distance_mi"].sum(),
        "total_moving_time_hr": df["moving_time_s"].sum() / 3600,
        "total_calories": df["calories"].sum(),
        "total_elevation_ft": df["elevation_gain_ft"].sum(),
        "activity_types": df["type"].value_counts().to_dict(),
    }


def type_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-activity-type summary table."""
    rows = []
    for atype, group in df.groupby("type"):
        row = {
            "type": atype,
            "count": len(group),
            "total_mi": group["distance_mi"].sum(),
            "total_time_hr": group["moving_time_s"].sum() / 3600,
            "avg_mi": group["distance_mi"].mean(),
            "avg_time_min": group["moving_time_min"].mean(),
            "avg_hr": group["avg_hr"].mean(),
            "total_calories": group["calories"].sum(),
            "total_elev_ft": group["elevation_gain_ft"].sum(),
        }
        if atype in ("Run", "Walk", "Hike"):
            row["avg_pace"] = format_pace(group["pace_min_per_mi"].mean())
            row["best_pace"] = format_pace(group["pace_min_per_mi"].min())
        else:
            row["avg_pace"] = "--"
            row["best_pace"] = "--"
        rows.append(row)
    return pd.DataFrame(rows).sort_values("count", ascending=False)


def monthly_summary(df: pd.DataFrame, activity_type: str | None = None) -> pd.DataFrame:
    """Monthly rollup. Optionally filtered to one activity type."""
    if activity_type:
        df = df[df["type"] == activity_type]
    grouped = df.groupby("month").agg(
        activities=("activity_id", "count"),
        distance_mi=("distance_mi", "sum"),
        moving_time_hr=("moving_time_s", lambda x: x.sum() / 3600),
        calories=("calories", "sum"),
        elevation_ft=("elevation_gain_ft", "sum"),
        avg_hr=("avg_hr", "mean"),
        avg_pace=("pace_min_per_mi", "mean"),
    )
    grouped["avg_pace_fmt"] = grouped["avg_pace"].apply(format_pace)
    return grouped


def weekly_summary(df: pd.DataFrame, activity_type: str | None = None) -> pd.DataFrame:
    """Weekly rollup."""
    if activity_type:
        df = df[df["type"] == activity_type]
    grouped = df.groupby("week").agg(
        activities=("activity_id", "count"),
        distance_mi=("distance_mi", "sum"),
        moving_time_hr=("moving_time_s", lambda x: x.sum() / 3600),
        calories=("calories", "sum"),
        avg_hr=("avg_hr", "mean"),
        avg_pace=("pace_min_per_mi", "mean"),
    )
    grouped["avg_pace_fmt"] = grouped["avg_pace"].apply(format_pace)
    return grouped


def running_metrics(df: pd.DataFrame) -> dict:
    """Detailed running-specific metrics."""
    runs = df[df["type"] == "Run"].copy()
    if runs.empty:
        return {}

    longest = runs.loc[runs["distance_mi"].idxmax()]
    fastest = runs.loc[runs["pace_min_per_mi"].idxmin()]

    # Streak: max consecutive days with a run
    run_dates = sorted(runs["date"].dt.date.unique())
    max_streak = curr_streak = 1
    for i in range(1, len(run_dates)):
        if (run_dates[i] - run_dates[i - 1]).days == 1:
            curr_streak += 1
            max_streak = max(max_streak, curr_streak)
        else:
            curr_streak = 1

    return {
        "total_runs": len(runs),
        "total_miles": runs["distance_mi"].sum(),
        "avg_distance_mi": runs["distance_mi"].mean(),
        "avg_pace": format_pace(runs["pace_min_per_mi"].mean()),
        "best_pace": format_pace(runs["pace_min_per_mi"].min()),
        "avg_hr": runs["avg_hr"].mean(),
        "max_hr_ever": runs["max_hr"].max(),
        "longest_run_mi": longest["distance_mi"],
        "longest_run_date": longest["date"],
        "longest_run_name": longest["name"],
        "fastest_run_pace": format_pace(fastest["pace_min_per_mi"]),
        "fastest_run_date": fastest["date"],
        "fastest_run_name": fastest["name"],
        "fastest_run_mi": fastest["distance_mi"],
        "max_run_streak_days": max_streak,
        "total_elevation_ft": runs["elevation_gain_ft"].sum(),
        "avg_elevation_ft": runs["elevation_gain_ft"].mean(),
    }


def day_of_week_distribution(df: pd.DataFrame, activity_type: str | None = None) -> pd.DataFrame:
    """Activity count and avg distance by day of week."""
    if activity_type:
        df = df[df["type"] == activity_type]
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    grouped = df.groupby("day_of_week").agg(
        count=("activity_id", "count"),
        avg_distance_mi=("distance_mi", "mean"),
        avg_pace=("pace_min_per_mi", "mean"),
    )
    grouped = grouped.reindex(day_order)
    grouped["avg_pace_fmt"] = grouped["avg_pace"].apply(format_pace)
    return grouped


def hr_zone_distribution(df: pd.DataFrame, max_hr: float | None = None) -> pd.DataFrame:
    """Approximate HR zone time distribution (based on avg HR per activity).

    Uses standard 5-zone model based on percentage of max HR.
    Defaults to the athlete's actual measured max HR from the data.
    """
    if max_hr is None:
        measured = df["max_hr"].max() if "max_hr" in df.columns else None
        max_hr = measured if pd.notna(measured) and measured > 0 else 190.0
    zones = [
        ("Z1 Recovery", 0.50, 0.60),
        ("Z2 Easy", 0.60, 0.70),
        ("Z3 Aerobic", 0.70, 0.80),
        ("Z4 Threshold", 0.80, 0.90),
        ("Z5 Max", 0.90, 1.00),
    ]
    has_hr = df[df["avg_hr"].notna()].copy()
    results = []
    for name, low_pct, high_pct in zones:
        low = max_hr * low_pct
        high = max_hr * high_pct
        in_zone = has_hr[(has_hr["avg_hr"] >= low) & (has_hr["avg_hr"] < high)]
        results.append({
            "zone": name,
            "hr_range": f"{low:.0f}-{high:.0f}",
            "activities": len(in_zone),
            "pct_activities": len(in_zone) / len(has_hr) * 100 if len(has_hr) else 0,
            "total_time_hr": in_zone["moving_time_s"].sum() / 3600,
        })
    return pd.DataFrame(results)


def recent_activities(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Most recent n activities."""
    recent = df.nlargest(n, "date")[
        ["date", "type", "name", "distance_mi", "moving_time_min", "pace_min_per_mi", "avg_hr", "calories"]
    ].copy()
    recent["pace"] = recent["pace_min_per_mi"].apply(format_pace)
    recent["time"] = recent["moving_time_min"].apply(format_duration)
    recent["date_str"] = recent["date"].dt.strftime("%b %d, %Y")
    return recent


def personal_records(df: pd.DataFrame) -> dict:
    """Find PRs across different metrics."""
    runs = df[df["type"] == "Run"]
    records = {}
    if not runs.empty:
        # Longest run
        idx = runs["distance_mi"].idxmax()
        records["longest_run"] = {
            "value": f"{runs.loc[idx, 'distance_mi']:.2f} mi",
            "date": runs.loc[idx, "date"],
            "name": runs.loc[idx, "name"],
        }
        # Fastest pace
        idx = runs["pace_min_per_mi"].idxmin()
        records["fastest_pace"] = {
            "value": format_pace(runs.loc[idx, "pace_min_per_mi"]) + " /mi",
            "date": runs.loc[idx, "date"],
            "name": runs.loc[idx, "name"],
        }
        # Highest elevation run
        idx = runs["elevation_gain_ft"].idxmax()
        records["most_elevation_run"] = {
            "value": f"{runs.loc[idx, 'elevation_gain_ft']:.0f} ft",
            "date": runs.loc[idx, "date"],
            "name": runs.loc[idx, "name"],
        }
        # Most calories
        idx = runs["calories"].idxmax()
        records["most_calories_run"] = {
            "value": f"{runs.loc[idx, 'calories']:.0f} cal",
            "date": runs.loc[idx, "date"],
            "name": runs.loc[idx, "name"],
        }
    # Across all types
    if not df.empty:
        idx = df["calories"].idxmax()
        records["most_calories_any"] = {
            "value": f"{df.loc[idx, 'calories']:.0f} cal",
            "date": df.loc[idx, "date"],
            "name": df.loc[idx, "name"],
            "type": df.loc[idx, "type"],
        }
    return records
