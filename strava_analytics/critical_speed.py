"""Critical Speed model for running race time prediction.

The two-parameter hyperbolic model fits best efforts at multiple distances:
    d = D' + CS * t
    (equivalently: t = D' / (v - CS) where v = d/t)

Where:
  CS = Critical Speed (m/s) — highest sustainable steady-state speed
  D' = Distance capacity above CS (m) — finite anaerobic reserve

CS maps directly to ~30-60 min race pace and is the best predictor of
endurance performance for events from 2-25 minutes. For longer events
(marathon), we blend with the Tanda formula.

Also includes the Tanda formula for marathon-specific prediction:
    Pm (sec/km) = 17.1 + 140.0 * exp(-0.0053 * K) + 0.55 * P
    where K = avg weekly km, P = avg pace in sec/km

References:
  - Monod & Scherrer (1965): Original critical power concept
  - Hill (1993): Critical power model applied to running
  - Smyth & Muniz-Pumares (2020): CS from training log best efforts
  - Tanda (2011): Marathon prediction from training volume and pace
"""

import math
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Distance label → meters
_DIST_M = {
    "1 Mile": 1609.344,
    "5K": 5000.0,
    "10K": 10000.0,
    "Half Marathon": 21097.5,
    "Marathon": 42195.0,
}

# Standard prediction distances
_PREDICTION_DISTANCES = {
    "1 Mile": 1609.344,
    "5K": 5000.0,
    "10K": 10000.0,
    "Half Marathon": 21097.5,
    "Marathon": 42195.0,
}


# ---------------------------------------------------------------------------
# Critical Speed fitting
# ---------------------------------------------------------------------------

def fit_critical_speed(
    efforts_df: pd.DataFrame,
    min_distances: int = 3,
) -> dict:
    """Fit the Critical Speed model from best effort data.

    Uses the linear form: d = D' + CS * t
    Fit via ordinary least squares on (time_s, distance_m) pairs.

    Args:
        efforts_df: DataFrame with distance_label, time_s, rank columns.
        min_distances: minimum number of distinct distances required.

    Returns:
        {cs_m_per_s, cs_min_per_mi, d_prime_m, r_squared, n_points,
         efforts: [{distance, time_s, predicted_s}]}
    """
    if efforts_df is None or efforts_df.empty:
        return _empty_cs_result()

    # Use rank-1 (best) effort per distance
    best = efforts_df[efforts_df["rank"] == 1].copy()
    if best.empty:
        best = efforts_df.groupby("distance_label").first().reset_index()

    points = []
    for _, row in best.iterrows():
        label = row.get("distance_label", "")
        dist_m = _DIST_M.get(label)
        time_s = row.get("time_s", 0)
        if dist_m and time_s > 0:
            points.append({"label": label, "dist_m": dist_m, "time_s": time_s})

    if len(points) < min_distances:
        logger.warning("CS fit: only %d distances (need %d)", len(points), min_distances)
        return _empty_cs_result()

    # Linear regression: d = D' + CS * t  →  d = b + m * t
    t = np.array([p["time_s"] for p in points])
    d = np.array([p["dist_m"] for p in points])

    # Fit: d = CS * t + D'
    A = np.vstack([t, np.ones(len(t))]).T
    result = np.linalg.lstsq(A, d, rcond=None)
    cs_m_per_s, d_prime_m = result[0]

    # Sanity check
    if cs_m_per_s <= 0:
        logger.warning("CS fit: negative CS (%.2f m/s), model failed", cs_m_per_s)
        return _empty_cs_result()

    # R-squared
    d_pred = cs_m_per_s * t + d_prime_m
    ss_res = np.sum((d - d_pred) ** 2)
    ss_tot = np.sum((d - np.mean(d)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # Convert CS to min/mi pace
    cs_min_per_mi = (1609.344 / cs_m_per_s) / 60.0 if cs_m_per_s > 0 else 0

    # Build efforts with predictions
    efforts = []
    for p in points:
        pred_s = predict_time_cs(cs_m_per_s, d_prime_m, p["dist_m"])
        efforts.append({
            "distance": p["label"],
            "distance_m": p["dist_m"],
            "actual_s": p["time_s"],
            "predicted_s": pred_s,
            "error_pct": (pred_s - p["time_s"]) / p["time_s"] * 100,
        })

    return {
        "cs_m_per_s": round(cs_m_per_s, 4),
        "cs_min_per_mi": round(cs_min_per_mi, 2),
        "d_prime_m": round(d_prime_m, 1),
        "r_squared": round(r_squared, 4),
        "n_points": len(points),
        "efforts": efforts,
    }


def _empty_cs_result() -> dict:
    return {
        "cs_m_per_s": 0, "cs_min_per_mi": 0, "d_prime_m": 0,
        "r_squared": 0, "n_points": 0, "efforts": [],
    }


def predict_time_cs(cs_m_per_s: float, d_prime_m: float, distance_m: float) -> float:
    """Predict race time (seconds) from CS model parameters.

    Uses: t = (d - D') / CS
    """
    if cs_m_per_s <= 0:
        return 0.0
    time_s = (distance_m - d_prime_m) / cs_m_per_s
    return max(time_s, 0)


def cs_to_vdot(cs_m_per_s: float) -> float:
    """Convert Critical Speed to equivalent VDOT.

    CS represents ~30-60 min race pace. We use 30 min as the reference
    duration to convert CS velocity to VDOT via Daniels' formulas.
    """
    if cs_m_per_s <= 0:
        return 0.0
    v_m_per_min = cs_m_per_s * 60.0
    # Daniels VO2 cost: VO2 = -4.60 + 0.182258*v + 0.000104*v²
    vo2 = -4.60 + 0.182258 * v_m_per_min + 0.000104 * v_m_per_min ** 2
    # At ~30 min race duration, VO2max fraction ≈ 0.94 (Daniels formula)
    fraction = 0.94
    return vo2 / fraction if fraction > 0 else 0.0


def predict_race_times(
    efforts_df: pd.DataFrame,
    weekly_km: float = 0,
    avg_pace_sec_per_km: float = 0,
) -> dict:
    """Predict race times at all standard distances.

    Uses CS model for 1mi-half marathon, blends with Tanda for marathon.

    Returns: {distance_label: {time_s, pace_min_per_mi, method, confidence}}
    """
    cs = fit_critical_speed(efforts_df)
    results = {}

    # For 1 Mile: use best effort directly (CS model unreliable below ~3K)
    # For 5K-Half: CS model (its sweet spot)
    # For Marathon: blend CS with Tanda (CS overestimates marathon)
    best_mile = efforts_df[efforts_df["distance_label"] == "1 Mile"]
    mile_time_s = float(best_mile.iloc[0]["time_s"]) if not best_mile.empty else 0

    for label, dist_m in _PREDICTION_DISTANCES.items():
        if cs["cs_m_per_s"] <= 0:
            results[label] = {
                "time_s": 0, "pace_min_per_mi": 0,
                "method": "insufficient data", "confidence": "none",
            }
            continue

        if label == "1 Mile" and mile_time_s > 0:
            # Use actual best effort for 1 Mile (CS breaks down here)
            time_s = mile_time_s
            method = "Best effort"
        elif label == "Marathon" and weekly_km > 0 and avg_pace_sec_per_km > 0:
            # Blend CS + Tanda for marathon
            cs_time = predict_time_cs(cs["cs_m_per_s"], cs["d_prime_m"], dist_m)
            tanda_s = tanda_marathon(weekly_km, avg_pace_sec_per_km)
            time_s = 0.4 * cs_time + 0.6 * tanda_s if tanda_s > 0 else cs_time
            method = "CS + Tanda blend" if tanda_s > 0 else "Critical Speed"
        else:
            time_s = predict_time_cs(cs["cs_m_per_s"], cs["d_prime_m"], dist_m)
            method = "Critical Speed"

        pace = (time_s / 60) / (dist_m / 1609.344) if time_s > 0 else 0
        confidence = "high" if cs["r_squared"] > 0.95 else "moderate"

        results[label] = {
            "time_s": round(time_s, 1),
            "pace_min_per_mi": round(pace, 2),
            "method": method,
            "confidence": confidence,
        }

    results["_cs_params"] = cs
    return results


# ---------------------------------------------------------------------------
# Tanda marathon formula
# ---------------------------------------------------------------------------

def tanda_marathon(avg_weekly_km: float, avg_pace_sec_per_km: float) -> float:
    """Predict marathon pace (sec/km) using the Tanda formula.

    Tanda (2011): Pm = 17.1 + 140.0 * exp(-0.0053 * K) + 0.55 * P
    Where K = avg weekly km (over 8 weeks), P = avg pace in sec/km.

    Returns: total marathon time in seconds.
    """
    if avg_weekly_km <= 0 or avg_pace_sec_per_km <= 0:
        return 0.0
    pace_per_km = (17.1
                   + 140.0 * math.exp(-0.0053 * avg_weekly_km)
                   + 0.55 * avg_pace_sec_per_km)
    return pace_per_km * 42.195
