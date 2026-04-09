"""Strength progression model with concurrent training interference.

Fits a logarithmic curve to historical 1RM estimates:
    1RM(t) = a * ln(weeks + 1) + b

The log model captures diminishing returns — beginners gain fast,
advanced lifters plateau. This is well-established in the strength
training literature (Rhea et al. 2003).

Concurrent training interference is modeled based on:
  - Wilson et al. (2012): Running causes volume-dependent interference
  - Hickson (1985): Significant interference above ~20 mi/week
  - Robineau et al. (2016): Interference mitigated by 6+ hour separation

The interference factor scales the log-curve's growth rate (a) to
project 1RM gains during concurrent run + lift training.

References:
  - Rhea, M.R. et al. (2003). 1-2%/week 1RM gains for trained.
  - Wilson, J.M. et al. (2012). Concurrent Training Meta-Analysis.
  - Hickson, R.C. (1985). Interference of strength development.
  - Ogasawara, R. et al. (2013). No 1RM loss during 3-week detraining.
  - McMaster, D.T. et al. (2013). ~2%/week 1RM decay after 3 weeks.
"""

import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Interference model constants
# ---------------------------------------------------------------------------

# Wilson (2012) / Hickson (1985): interference is running-volume-dependent.
# Below ~15 mi/wk: negligible interference (strength gains unaffected).
# Above ~15 mi/wk: each additional mile reduces adaptation rate.
# At ~35 mi/wk: adaptation rate is halved.
_INTERFERENCE_THRESHOLD_MI = 15.0   # miles/week below which no interference
_INTERFERENCE_SLOPE = 0.025         # reduction per mile above threshold
_INTERFERENCE_FLOOR = 0.50          # minimum factor (never below 50%)

# Detraining constants (when projecting forward without lifting)
_DETRAINING_GRACE_WEEKS = 3        # Ogasawara (2013): no loss for 3 weeks
_DETRAINING_RATE_PER_WEEK = 0.02   # McMaster (2013): ~2%/week after grace


# ---------------------------------------------------------------------------
# Log-curve fitting
# ---------------------------------------------------------------------------

def fit_1rm_curve(progression_df: pd.DataFrame) -> dict:
    """Fit a logarithmic progression curve to historical 1RM estimates.

    Model: 1RM(w) = a * ln(w + 1) + b
    where w = weeks since first recorded lift.

    Ground truth (tested 1x1 maxes) are given 3x weight in the fit.

    Args:
        progression_df: DataFrame with date, estimated_1rm, is_test columns.

    Returns:
        {a, b, r_squared, current_1rm, current_date, n_points, has_tests}
    """
    if progression_df is None or progression_df.empty:
        return _empty_fit()

    df = progression_df.sort_values("date").copy()
    if len(df) < 2:
        val = float(df.iloc[0]["estimated_1rm"])
        return {"a": 0, "b": val, "r_squared": 0, "current_1rm": val,
                "current_date": df.iloc[0]["date"], "n_points": 1, "has_tests": False}

    # Convert dates to weeks since first session
    first_date = df["date"].min()
    df["weeks"] = (df["date"] - first_date).dt.total_seconds() / (7 * 86400)

    x = np.log(df["weeks"].values + 1)
    y = df["estimated_1rm"].values

    # Weight tested maxes 3x (they're ground truth)
    weights = np.ones(len(df))
    if "is_test" in df.columns:
        weights[df["is_test"].values == True] = 3.0

    # Weighted least squares: y = a * ln(w+1) + b
    W = np.diag(weights)
    A = np.vstack([x, np.ones(len(x))]).T
    AW = W @ A
    bW = W @ y
    result = np.linalg.lstsq(AW, bW, rcond=None)
    a, b = result[0]

    # R-squared (unweighted for interpretability)
    y_pred = a * x + b
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # Current 1RM = value at the latest week
    current_week = df["weeks"].max()
    current_1rm = a * math.log(current_week + 1) + b

    # If we have a recent tested max (within 4 weeks), prefer it
    has_tests = False
    if "is_test" in df.columns:
        tests = df[df["is_test"] == True]
        if not tests.empty:
            has_tests = True
            latest_test = tests.iloc[-1]
            weeks_since_test = current_week - latest_test["weeks"]
            if weeks_since_test <= 4:
                current_1rm = float(latest_test["estimated_1rm"])

    return {
        "a": round(a, 2),
        "b": round(b, 2),
        "r_squared": round(r_squared, 4),
        "current_1rm": round(current_1rm, 1),
        "current_date": df["date"].max(),
        "n_points": len(df),
        "has_tests": has_tests,
        "total_weeks": round(current_week, 1),
    }


def _empty_fit() -> dict:
    return {"a": 0, "b": 0, "r_squared": 0, "current_1rm": 0,
            "current_date": None, "n_points": 0, "has_tests": False,
            "total_weeks": 0}


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def project_1rm(
    params: dict,
    weeks_ahead: float,
    interference_factor: float = 1.0,
    is_lifting: bool = True,
) -> float:
    """Project 1RM forward from current state.

    During active lifting (is_lifting=True):
        projected = current + a * interference * (ln(w_future+1) - ln(w_now+1))

    During detraining (is_lifting=False):
        - 3-week grace period (Ogasawara 2013)
        - Then -2%/week (McMaster 2013)

    Args:
        params: output from fit_1rm_curve()
        weeks_ahead: how many weeks to project
        interference_factor: 0.5-1.0, from compute_interference()
        is_lifting: whether the athlete is actively lifting

    Returns:
        Projected 1RM in lbs.
    """
    current = params.get("current_1rm", 0)
    if current <= 0 or weeks_ahead <= 0:
        return current

    if is_lifting:
        a = params.get("a", 0)
        total_weeks = params.get("total_weeks", 0)
        # Growth = a * (ln(w_future + 1) - ln(w_now + 1)) * interference
        w_now = total_weeks
        w_future = total_weeks + weeks_ahead
        growth = a * (math.log(w_future + 1) - math.log(w_now + 1))
        growth *= interference_factor
        return round(current + growth, 1)
    else:
        # Detraining model
        if weeks_ahead <= _DETRAINING_GRACE_WEEKS:
            return current  # no loss during grace period
        detraining_weeks = weeks_ahead - _DETRAINING_GRACE_WEEKS
        decay = (1 - _DETRAINING_RATE_PER_WEEK) ** detraining_weeks
        return round(current * decay, 1)


# ---------------------------------------------------------------------------
# Interference model
# ---------------------------------------------------------------------------

def compute_interference(weekly_run_miles: float) -> float:
    """Compute the concurrent training interference factor.

    Based on Wilson et al. (2012) meta-analysis and Hickson (1985):
    - Below 15 mi/wk: no significant interference (factor = 1.0)
    - Above 15 mi/wk: linear reduction in strength adaptation rate
    - Floor at 0.50 (even heavy running doesn't eliminate all gains)

    Args:
        weekly_run_miles: average weekly running volume in miles.

    Returns:
        Factor between 0.5 and 1.0 to multiply strength gains by.
    """
    excess = max(0, weekly_run_miles - _INTERFERENCE_THRESHOLD_MI)
    factor = 1.0 - _INTERFERENCE_SLOPE * excess
    return max(_INTERFERENCE_FLOOR, min(1.0, factor))


# ---------------------------------------------------------------------------
# Convenience: fit all lifts
# ---------------------------------------------------------------------------

def fit_all_lifts(
    df: pd.DataFrame,
    lifts: list[str] | None = None,
) -> dict[str, dict]:
    """Fit log-curves for all lifts from the enriched DataFrame.

    Args:
        df: Enriched activity DataFrame with lift columns.
        lifts: list of lift names (default: bench, squat, deadlift, ohp).

    Returns:
        {lift_name: fit_params_dict}
    """
    from strava_analytics.predictions import extract_1rm_progression

    if lifts is None:
        lifts = ["bench", "squat", "deadlift", "ohp"]

    results = {}
    for lift in lifts:
        prog = extract_1rm_progression(df, lift)
        if not prog.empty:
            results[lift] = fit_1rm_curve(prog)
        else:
            results[lift] = _empty_fit()

    return results
