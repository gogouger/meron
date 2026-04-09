"""Kalman filter for smoothing 5K fitness and 1RM strength estimates.

Uses a 1D scalar Kalman filter where:
- State: true fitness level (5K time in minutes, or 1RM in lbs)
- Observations: noisy estimates from individual runs/sessions
- Ground truth: actual race results or tested maxes (low measurement noise)

The filter produces a smooth curve that adapts to new data and snaps to
ground truth measurements, with principled uncertainty (confidence bands).

Detraining model:
  When CTL (chronic training load) drops below the Hickson threshold (70% of
  peak), the filter applies a drift term and increases process noise. This is
  grounded in:
  - Hickson et al. (1985): intensity maintained at 1/3 volume → no VO2max loss
  - Mujika & Padilla (2000): ~2.5%/week VO2max decay with complete cessation
  - McMaster et al. (2013): ~2%/week 1RM decay after 3-week grace period
  - Ogasawara et al. (2013): no 1RM loss during 3-week detraining periods
"""

import math
from datetime import date as date_type, timedelta

import numpy as np
import pandas as pd

from strava_analytics.vo2max import (
    daniels_vdot, daniels_vdot_adjusted, intensity_from_zones, vdot_to_race_time,
)


# ---------------------------------------------------------------------------
# Core 1D Kalman filter
# ---------------------------------------------------------------------------

_GROUND_TRUTH_R = -1.0  # sentinel: override state entirely

# Detraining constants (derived from literature)
# Detraining threshold is relative to a BASELINE (90-day avg CTL), not peak.
# Using peak causes drift on 88%+ of history for athletes whose peak was a spike.
_DETRAINING_THRESHOLD = 0.85  # CTL ratio vs baseline below which drift applies
_Q_DETRAINING_MULT = 2.0     # process noise multiplier during detraining
_MAX_DRIFT_PCT = 0.15         # cap: state can't drift more than 15% from anchor

# Race time drift: 2.5%/week VO2max loss → for a 25-min 5K, ~5.4 sec/day
# at full detraining. Scaled by deficit so partial detraining is proportional.
_DRIFT_RATE_RACE = 0.06      # min/day per 0.1 deficit below threshold

# 1RM drift: 2%/week after 3-week grace (McMaster 2013).
_DRIFT_RATE_1RM = 0.2        # lbs/day per 0.1 deficit below threshold
_1RM_GRACE_DAYS = 21         # Ogasawara (2013): no loss for 3 weeks


def _kalman_1d(
    dates: list,
    observations: list[float],
    noise: list[float],
    q_per_day: float,
    initial_state: float | None = None,
    initial_covariance: float = 25.0,
    ctl_series: dict | None = None,
    ctl_baseline: float | None = None,
    higher_is_better: bool = False,
    grace_days: int = 0,
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
        ctl_series: {date → CTL value} for detraining drift. Optional.
        ctl_baseline: 90-day rolling avg CTL for ratio calculation. Optional.
                      Using baseline (not peak) prevents drift when athlete is
                      simply at their normal training level.
        higher_is_better: True for 1RM (drift down = worse),
                          False for race times (drift up = worse).
        grace_days: days below threshold before drift begins (e.g. 21 for 1RM).

    Returns:
        (states, uppers, lowers) — smoothed values and ±2σ confidence band
    """
    n = len(observations)
    if n == 0:
        return [], [], []

    x = initial_state if initial_state is not None else observations[0]
    P = initial_covariance

    # Detraining tracking
    use_ctl = (ctl_series is not None and ctl_baseline is not None
               and ctl_baseline > 0)
    days_below_threshold = 0
    drift_rate = _DRIFT_RATE_1RM if higher_is_better else _DRIFT_RATE_RACE
    anchor = x  # drift cap reference point (updated on ground truth)

    states = []
    uppers = []
    lowers = []

    for i in range(n):
        # Predict: state doesn't change, but uncertainty grows with time
        if i > 0:
            dt = (dates[i] - dates[i - 1]).total_seconds() / 86400.0
            dt = max(dt, 0.01)  # avoid zero
            Q = q_per_day * dt

            # CTL-informed detraining drift
            if use_ctl:
                d = dates[i]
                d_key = d.date() if hasattr(d, "date") and callable(d.date) else d
                ctl_now = ctl_series.get(d_key, 0)
                ctl_ratio = ctl_now / ctl_baseline

                deficit = max(0.0, _DETRAINING_THRESHOLD - ctl_ratio)
                if deficit > 0:
                    days_below_threshold += dt
                    # Adaptive Q: increase process noise during detraining
                    Q *= (1.0 + _Q_DETRAINING_MULT * deficit)

                    # Drift: only after grace period, capped at 15% from anchor
                    if days_below_threshold > grace_days:
                        drift = drift_rate * deficit * 10.0 * dt
                        if higher_is_better:
                            cap = anchor * (1 - _MAX_DRIFT_PCT)
                            x = max(x - drift, cap)
                        else:
                            cap = anchor * (1 + _MAX_DRIFT_PCT)
                            x = min(x + drift, cap)
                else:
                    days_below_threshold = 0  # reset grace counter

            P = P + Q

        z = observations[i]
        R = noise[i]

        if R == _GROUND_TRUTH_R:
            # Ground truth: snap state to observation, collapse uncertainty
            x = z
            P = 0.5
            days_below_threshold = 0
            anchor = x  # update drift cap reference
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


def _ctl_baseline_90d(ctl_series: dict) -> float:
    """Compute the 90-day rolling average CTL as a stable baseline.

    Using baseline instead of peak prevents false detraining detection
    when an athlete's peak CTL was a brief spike above their normal level.
    """
    if not ctl_series:
        return 0.0
    sorted_dates = sorted(ctl_series.keys())
    if not sorted_dates:
        return 0.0
    latest = sorted_dates[-1]
    cutoff = latest - timedelta(days=90)
    recent = [v for d, v in ctl_series.items() if d >= cutoff]
    return sum(recent) / len(recent) if recent else 0.0


def kalman_race(
    runs: pd.DataFrame,
    target_m: int = 5_000,
    ctl_series: dict | None = None,
    ctl_peak: float | None = None,
) -> pd.DataFrame:
    """Smooth race time estimates for a target distance using a Kalman filter.

    For each qualifying run, computes VDOT and converts to equivalent time
    at `target_m`. Actual races matching the target distance snap to ground
    truth. Races at other distances provide moderate signal. Training runs
    are high-noise observations.

    Args:
        runs: DataFrame of runs (enriched, with run_type)
        target_m: target race distance in meters (5000, 10000, 21097, 42195)
        ctl_series: {date → CTL} for detraining drift. Optional.
        ctl_peak: ignored (kept for backward compat). Baseline computed internally.

    Returns:
        DataFrame with: date, est_time_min, kalman_min, kalman_upper,
        kalman_lower, run_type, name, distance_mi, date_str, R
    """
    df = runs.copy()
    df = df[(df["distance_mi"] >= 2.0) &
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

        if dist_m < 3200 or time_min < 10:
            continue

        # Is this an actual race at the target distance?
        is_target_race = run_type == "race" and gt_lo <= dist_m <= gt_hi
        is_other_race = run_type == "race" and not is_target_race

        hr_zone = r.get("hr_zone") if "hr_zone" in r.index else None
        has_hr = hr_zone is not None and not (isinstance(hr_zone, float) and math.isnan(hr_zone))
        hz = int(hr_zone) if has_hr else None

        # Compute intensity-corrected VDOT when HR zone data is available
        zone_secs = {z: (r.get(f"zone_{z}_s", 0) or 0) for z in range(1, 6)}
        total_zone_s = sum(zone_secs.values())

        if total_zone_s > 0 and run_type != "race":
            intensity = intensity_from_zones(zone_secs)
            vdot = daniels_vdot_adjusted(dist_m, time_min, intensity)
        elif has_hr and run_type != "race":
            # Fallback: use single hr_zone midpoint fraction
            zone_frac = {1: 0.60, 2: 0.70, 3: 0.80, 4: 0.88, 5: 0.95}
            vdot = daniels_vdot_adjusted(dist_m, time_min,
                                          zone_frac.get(hz, 0.75))
        else:
            vdot = daniels_vdot(dist_m, time_min)

        est_time = vdot_to_race_time(vdot, target_m)

        if is_target_race:
            R = _GROUND_TRUTH_R
            # Use actual scaled time, not VDOT estimate
            est_time = time_min * (target_m / dist_m)
        elif is_other_race:
            R = 2.0     # Race effort at different distance — good VDOT signal
        elif run_type == "hard_effort":
            if has_hr and hz >= 4:
                R = 8.0     # Hard effort confirmed by HR — strong signal
            elif has_hr and hz == 3:
                R = 15.0    # Moderate-effort hard_effort
            else:
                R = 35.0    # Low/no HR — still useful but more uncertain
        elif run_type == "long":
            if has_hr and hz >= 3:
                R = 25.0    # Honest long effort with some intensity
            else:
                R = 40.0    # Easy long run
        elif run_type == "moderate":
            if has_hr and hz >= 4:
                R = 20.0    # Tempo-like moderate run
            elif has_hr and hz == 3:
                R = 35.0    # Solid moderate effort
            elif has_hr and hz == 2:
                R = 60.0    # Light moderate — still useful
            else:
                R = 100.0   # Z1 moderate — weakest but included
        elif run_type == "easy":
            if has_hr and hz >= 3:
                R = 40.0    # Misclassified easy — real effort
            elif has_hr and hz == 2:
                R = 80.0    # Z2 aerobic base — useful signal
            else:
                R = 120.0   # True recovery — weak but included
        else:
            R = 100.0   # Unknown type — include with moderate noise

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

    baseline = _ctl_baseline_90d(ctl_series) if ctl_series else None

    states, uppers, lowers = _kalman_1d(
        obs_df["date"].tolist(),
        obs_df["est_time_min"].tolist(),
        obs_df["R"].tolist(),
        q_per_day=0.002,
        initial_covariance=25.0,
        ctl_series=ctl_series,
        ctl_baseline=baseline,
        higher_is_better=False,  # lower race time = better
    )

    obs_df["kalman_min"] = states
    obs_df["kalman_upper"] = uppers
    obs_df["kalman_lower"] = lowers

    return obs_df


# ---------------------------------------------------------------------------
# 1RM strength filter
# ---------------------------------------------------------------------------

def kalman_1rm(
    progression_df: pd.DataFrame,
    ctl_series: dict | None = None,
    ctl_peak: float | None = None,
) -> pd.DataFrame:
    """Smooth 1RM estimates using a Kalman filter.

    Actual 1x1 tests (is_test == True) are treated as ground truth.
    Formula-based estimates from working sets have high measurement noise.

    Args:
        progression_df: DataFrame with date, estimated_1rm, is_test columns.
        ctl_series: {date → CTL} for detraining drift. Optional.
        ctl_peak: peak CTL for ratio calculation. Optional.

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
            noise.append(25.0)  # Formula estimate

    baseline = _ctl_baseline_90d(ctl_series) if ctl_series else None

    states, uppers, lowers = _kalman_1d(
        dates, observations, noise,
        q_per_day=1.5,  # ~10 lbs drift per week — tracks progressive overload
        initial_covariance=200.0,
        ctl_series=ctl_series,
        ctl_baseline=baseline,
        higher_is_better=True,   # higher 1RM = better
        grace_days=_1RM_GRACE_DAYS,  # Ogasawara (2013): 3-week grace period
    )

    df["kalman_1rm"] = states
    df["kalman_upper"] = uppers
    df["kalman_lower"] = lowers

    return df
