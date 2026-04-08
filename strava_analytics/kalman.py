"""Kalman filter for smoothing 5K fitness and 1RM strength estimates.

Uses a 1D scalar Kalman filter where:
- State: true fitness level (5K time in minutes, or 1RM in lbs)
- Observations: noisy estimates from individual runs/sessions
- Ground truth: actual race results or tested maxes (low measurement noise)

The filter produces a smooth curve that adapts to new data and snaps to
ground truth measurements, with principled uncertainty (confidence bands).
"""

import math

import numpy as np
import pandas as pd

from strava_analytics.vo2max import daniels_vdot, vdot_to_race_time


# ---------------------------------------------------------------------------
# Core 1D Kalman filter
# ---------------------------------------------------------------------------

_GROUND_TRUTH_R = -1.0  # sentinel: override state entirely


def _kalman_1d(
    dates: list,
    observations: list[float],
    noise: list[float],
    q_per_day: float,
    initial_state: float | None = None,
    initial_covariance: float = 25.0,
) -> tuple[list[float], list[float], list[float]]:
    """Run a 1D Kalman filter on a time-ordered sequence.

    Args:
        dates: list of datetime objects (sorted chronologically)
        observations: measured values (z)
        noise: measurement noise variance (R) per observation.
               Use _GROUND_TRUTH_R (-1) to force the state to snap
               to the observation (race results, tested maxes).
        q_per_day: process noise variance per day (Q scaling)
        initial_state: starting estimate (defaults to first observation)
        initial_covariance: starting uncertainty (P0)

    Returns:
        (states, uppers, lowers) — smoothed values and ±2σ confidence band
    """
    n = len(observations)
    if n == 0:
        return [], [], []

    x = initial_state if initial_state is not None else observations[0]
    P = initial_covariance

    states = []
    uppers = []
    lowers = []

    for i in range(n):
        # Predict: state doesn't change, but uncertainty grows with time
        if i > 0:
            dt = (dates[i] - dates[i - 1]).total_seconds() / 86400.0
            dt = max(dt, 0.01)  # avoid zero
            Q = q_per_day * dt
            P = P + Q

        z = observations[i]
        R = noise[i]

        if R == _GROUND_TRUTH_R:
            # Ground truth: snap state to observation, collapse uncertainty
            x = z
            P = 0.5  # small residual uncertainty (measurement isn't infinitely precise)
        else:
            # Standard Kalman update
            K = P / (P + R)
            x = x + K * (z - x)
            P = (1 - K) * P

        sigma2 = 2 * math.sqrt(max(P, 0))
        states.append(round(x, 2))
        uppers.append(round(x + sigma2, 2))
        lowers.append(round(x - sigma2, 2))

    return states, uppers, lowers


# ---------------------------------------------------------------------------
# Race distance prediction filter
# ---------------------------------------------------------------------------

# Ground truth distance ranges (meters) for each target race
_RACE_RANGES = {
    5_000:  (4_500, 5_500),
    10_000: (9_000, 11_000),
    21_097: (19_000, 23_000),
    42_195: (38_000, 45_000),
}


def kalman_race(runs: pd.DataFrame, target_m: int = 5_000) -> pd.DataFrame:
    """Smooth race time estimates for a target distance using a Kalman filter.

    For each qualifying run, computes VDOT and converts to equivalent time
    at `target_m`. Actual races matching the target distance snap to ground
    truth. Races at other distances provide moderate signal. Training runs
    are high-noise observations.

    Args:
        runs: DataFrame of runs (enriched, with run_type)
        target_m: target race distance in meters (5000, 10000, 21097, 42195)

    Returns:
        DataFrame with: date, est_time_min, kalman_min, kalman_upper,
        kalman_lower, run_type, name, distance_mi, date_str, R
    """
    df = runs.copy()
    df = df[(df["distance_mi"] >= 3.0) &
            (df["pace_min_per_mi"] >= 6) & (df["pace_min_per_mi"] <= 14)]

    empty_cols = ["date", "est_time_min", "kalman_min", "kalman_upper",
                  "kalman_lower", "R", "run_type", "name", "distance_mi", "date_str"]
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    gt_lo, gt_hi = _RACE_RANGES.get(target_m, (target_m * 0.9, target_m * 1.1))

    rows = []
    for _, r in df.sort_values("date").iterrows():
        dist_m = r.get("distance_m", 0)
        time_s = r.get("moving_time_s", 0)
        time_min = time_s / 60.0
        run_type = r.get("run_type", "")

        if dist_m < 4800 or time_min < 15:
            continue

        vdot = daniels_vdot(dist_m, time_min)
        est_time = vdot_to_race_time(vdot, target_m)

        # Is this an actual race at the target distance?
        is_target_race = run_type == "race" and gt_lo <= dist_m <= gt_hi
        is_other_race = run_type == "race" and not is_target_race

        hr_zone = r.get("hr_zone") if "hr_zone" in r.index else None
        has_hr = hr_zone is not None and not (isinstance(hr_zone, float) and math.isnan(hr_zone))
        hz = int(hr_zone) if has_hr else None

        if is_target_race:
            R = _GROUND_TRUTH_R
            # Use actual scaled time, not VDOT estimate
            est_time = time_min * (target_m / dist_m)
        elif is_other_race:
            R = 2.0     # Race effort at different distance — good VDOT signal
        elif run_type == "workout":
            # Interval/tempo — quality depends on whether HR confirms intensity
            if has_hr and hz >= 4:
                R = 15.0    # Hard interval/tempo confirmed by HR — strong signal
            elif has_hr and hz == 3:
                R = 35.0    # Moderate-effort workout
            else:
                R = 120.0   # Low/no HR — likely mislabeled, treat as easy
        elif run_type == "long":
            if has_hr and hz >= 3:
                R = 40.0    # Honest long effort with some intensity
            else:
                R = 60.0    # Easy long run
        elif run_type == "moderate":
            if has_hr and hz >= 4:
                R = 30.0    # Tempo-like moderate run
            elif has_hr and hz <= 2:
                R = 130.0   # Very easy moderate — weak signal
            else:
                R = 80.0    # Default moderate
        else:
            R = 150.0   # Easy — essentially noise

        rows.append({
            "date": r["date"],
            "est_time_min": round(est_time, 2),
            "R": R,
            "run_type": run_type,
            "name": r.get("name", ""),
            "distance_mi": r.get("distance_mi", 0),
            "date_str": r["date"].strftime("%Y-%m-%d"),
        })

    if not rows:
        return pd.DataFrame(columns=empty_cols)

    obs_df = pd.DataFrame(rows)

    states, uppers, lowers = _kalman_1d(
        obs_df["date"].tolist(),
        obs_df["est_time_min"].tolist(),
        obs_df["R"].tolist(),
        q_per_day=0.002,
        initial_covariance=25.0,
    )

    obs_df["kalman_min"] = states
    obs_df["kalman_upper"] = uppers
    obs_df["kalman_lower"] = lowers

    return obs_df


# ---------------------------------------------------------------------------
# 1RM strength filter
# ---------------------------------------------------------------------------

def kalman_1rm(progression_df: pd.DataFrame) -> pd.DataFrame:
    """Smooth 1RM estimates using a Kalman filter.

    Actual 1x1 tests (is_test == True) are treated as ground truth.
    Formula-based estimates from working sets have high measurement noise.

    Returns DataFrame with: date, kalman_1rm, kalman_upper, kalman_lower,
    plus the original estimated_1rm.
    """
    if progression_df.empty:
        return pd.DataFrame(columns=["date", "kalman_1rm", "kalman_upper",
                                      "kalman_lower", "estimated_1rm"])

    df = progression_df.sort_values("date").copy()

    dates = df["date"].tolist()
    observations = df["estimated_1rm"].tolist()

    # Measurement noise: tested maxes snap, formula estimates are noisy
    noise = []
    for _, r in df.iterrows():
        if r.get("is_test", False):
            noise.append(_GROUND_TRUTH_R)  # Ground truth — snap to value
        else:
            noise.append(80.0)  # Formula estimate — high noise

    states, uppers, lowers = _kalman_1d(
        dates, observations, noise,
        q_per_day=0.3,  # ~2 lbs drift per week
        initial_covariance=400.0,  # ±40 lbs initial uncertainty
    )

    df["kalman_1rm"] = states
    df["kalman_upper"] = uppers
    df["kalman_lower"] = lowers

    return df
