"""Load and clean Strava export data."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# The activities.csv has duplicate column names. We use positional indices
# mapped to clean names for the columns we care about.
_COLUMN_MAP = {
    0: "activity_id",
    1: "date",
    2: "name",
    3: "type",
    4: "description",
    11: "gear",
    12: "filename",
    15: "elapsed_time_s",
    16: "moving_time_s",
    17: "distance_m",
    18: "max_speed_ms",
    19: "avg_speed_ms",
    20: "elevation_gain_m",
    21: "elevation_loss_m",
    22: "elevation_low_m",
    23: "elevation_high_m",
    30: "max_hr",
    31: "avg_hr",
    33: "avg_watts",
    34: "calories",
    37: "relative_effort",
    53: "grade_adj_distance_m",
    55: "weather_condition",
    56: "weather_temp_c",
    85: "total_steps",
    88: "training_load",
    89: "intensity",
    95: "competition",
    98: "strava_with_kid",
}

_NUMERIC_COLS = [
    "elapsed_time_s",
    "moving_time_s",
    "distance_m",
    "max_speed_ms",
    "avg_speed_ms",
    "elevation_gain_m",
    "elevation_loss_m",
    "elevation_low_m",
    "elevation_high_m",
    "max_hr",
    "avg_hr",
    "avg_watts",
    "calories",
    "relative_effort",
    "grade_adj_distance_m",
    "weather_temp_c",
    "total_steps",
    "training_load",
    "intensity",
]


def load_activities(export_dir: str | Path) -> pd.DataFrame:
    """Load activities.csv from a Strava export directory.

    Returns a cleaned DataFrame with proper types and derived columns.
    """
    export_dir = Path(export_dir)
    csv_path = export_dir / "activities.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No activities.csv found in {export_dir}")

    df = pd.read_csv(csv_path, header=0)

    # Rename by position to avoid duplicate-column issues
    rename = {}
    cols = list(df.columns)
    for pos, clean_name in _COLUMN_MAP.items():
        if pos < len(cols):
            rename[cols[pos]] = clean_name
    # Handle duplicate column names: pandas appends .1, .2, etc.
    # We need positional rename, so use iloc-based approach instead.
    raw = pd.read_csv(csv_path, header=None, skiprows=1)
    selected = raw[list(_COLUMN_MAP.keys())].copy()
    selected.columns = list(_COLUMN_MAP.values())

    # Parse dates (Strava exports in UTC; convert to the user's local tz)
    from .config import default_tz_name
    selected["date"] = pd.to_datetime(selected["date"], format="mixed", dayfirst=False)
    selected["date"] = (
        selected["date"]
        .dt.tz_localize("UTC")
        .dt.tz_convert(default_tz_name())
        .dt.tz_localize(None)  # drop tz info for pandas compat
    )

    # Coerce numerics
    for col in _NUMERIC_COLS:
        if col in selected.columns:
            selected[col] = pd.to_numeric(selected[col], errors="coerce")

    # Derived columns
    selected["weather_temp_f"] = selected["weather_temp_c"] * 9 / 5 + 32
    selected["distance_mi"] = selected["distance_m"] / 1609.344
    selected["distance_km"] = selected["distance_m"] / 1000.0
    selected["elevation_gain_ft"] = selected["elevation_gain_m"] * 3.28084
    selected["moving_time_min"] = selected["moving_time_s"] / 60.0
    selected["elapsed_time_min"] = selected["elapsed_time_s"] / 60.0

    # Pace (min/mile) for run/walk activities
    mask = selected["distance_mi"] > 0
    selected.loc[mask, "pace_min_per_mi"] = (
        selected.loc[mask, "moving_time_min"] / selected.loc[mask, "distance_mi"]
    )

    logger.info("Loaded %d activities from %s", len(selected), csv_path)

    # Sort by date ascending
    selected = selected.sort_values("date").reset_index(drop=True)

    # Week / month / year columns for grouping
    selected["year"] = selected["date"].dt.year
    selected["month"] = selected["date"].dt.to_period("M")
    selected["week"] = selected["date"].dt.to_period("W")
    selected["day_of_week"] = selected["date"].dt.day_name()

    logger.info("Columns: %s", list(selected.columns))
    return selected


def load_shoes(export_dir: str | Path) -> pd.DataFrame:
    path = Path(export_dir) / "shoes.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_profile(export_dir: str | Path) -> dict:
    path = Path(export_dir) / "profile.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if df.empty:
        return {}
    return df.iloc[0].to_dict()
