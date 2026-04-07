"""Race pace and 1RM prediction models grounded in sports science.

Race Pace References:
  - Riegel, P.S. (1981). Athletic Records and Human Endurance.
    American Scientist, 69(3), 285-290.
  - Daniels, J. (2014). Daniels' Running Formula, 3rd ed. Human Kinetics.
  - Cameron, J. (1999). A Mathematical Model for Marathon Performance.
  - Peronnet, F., Thibault, G., & Cousineau, D.L. (1991). A theoretical
    analysis of the effect of altitude on running performance.
    J Applied Physiology, 70(1), 399-404.
  - Minetti, A.E. et al. (2002). Energy cost of walking and running at
    extreme uphill and downhill slopes. J Applied Physiology, 93(3), 1039-1046.
  - Vickers, A.J. & Vertosick, E.A. (2016). An empirical study of race
    times in recreational endurance runners. BMC Sports Sci Med Rehabil, 8(1).

1RM References:
  - Epley, B. (1985). Poundage Chart. Boyd Epley Workout. Body Enterprises.
  - Brzycki, M. (1993). Strength Testing. JPHERD, 64(1), 88-90.
  - Lombardi, V.P. (1989). Beginning Weight Training. Wm. C. Brown.
  - Wathan, D. (1994). Load Assignment. In Essentials of S&C. NSCA.
  - Mayhew, J.L. et al. (1992). Relative Muscular Endurance Performance
    as a Predictor of Bench Press Strength. JASSR, 6(4), 200-206.
  - LeSuer, D.A. et al. (1997). The accuracy of prediction equations for
    estimating 1-RM performance. JSCR, 11(4), 211-213.
  - Zourdos, M.C. et al. (2016). Novel Resistance Training-Specific RPE
    Scale. JSCR, 30(1), 267-275.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .vo2max import daniels_vdot, vdot_to_race_time

logger = logging.getLogger(__name__)


# =========================================================================
# Race Pace Prediction
# =========================================================================

def predict_riegel(known_distance_m: float, known_time_s: float,
                   target_distance_m: float, exponent: float = 1.06) -> float:
    """Predict race time using the Riegel formula.

    T2 = T1 × (D2/D1)^exponent

    Args:
        known_distance_m: Known race distance in meters.
        known_time_s: Known race time in seconds.
        target_distance_m: Target distance in meters.
        exponent: Fatigue exponent (1.06 for elites, ~1.15-1.20 for recreational).

    Returns:
        Predicted time in seconds.
    """
    if known_distance_m <= 0 or known_time_s <= 0:
        return 0.0
    return known_time_s * (target_distance_m / known_distance_m) ** exponent


def _cameron_f(distance_m: float) -> float:
    """Cameron's distance scaling function.

    f(x) = 13.49681 - 0.000030363*x + 835.7114 / x^0.7905
    where x is distance in meters.
    """
    if distance_m <= 0:
        return 1.0
    return 13.49681 - 0.000030363 * distance_m + 835.7114 / (distance_m ** 0.7905)


def predict_cameron(known_distance_m: float, known_time_s: float,
                     target_distance_m: float) -> float:
    """Predict race time using the Cameron formula.

    T2 = T1 × (D2/D1) × (f(D1) / f(D2))

    Returns:
        Predicted time in seconds.
    """
    if known_distance_m <= 0 or known_time_s <= 0:
        return 0.0
    f1 = _cameron_f(known_distance_m)
    f2 = _cameron_f(target_distance_m)
    if f2 <= 0:
        return 0.0
    return known_time_s * (target_distance_m / known_distance_m) * (f1 / f2)


def predict_daniels(known_distance_m: float, known_time_s: float,
                     target_distance_m: float) -> float:
    """Predict race time using Daniels' VDOT model.

    Compute VDOT from known result, then invert to find time at target distance.

    Returns:
        Predicted time in seconds.
    """
    time_min = known_time_s / 60.0
    vdot = daniels_vdot(known_distance_m, time_min)
    if vdot <= 0:
        return 0.0
    predicted_min = vdot_to_race_time(vdot, target_distance_m)
    return predicted_min * 60.0


def compute_personal_exponent(race_results: list[tuple[float, float]]) -> float:
    """Compute personal Riegel fatigue exponent from multiple race results.

    Uses least-squares fit on log(T) = log(k) + exponent × log(D).

    Args:
        race_results: List of (distance_m, time_s) tuples.

    Returns:
        Personal fatigue exponent (typically 1.06-1.20 for recreational runners).
    """
    if len(race_results) < 2:
        return 1.06  # default

    log_d = np.array([math.log(d) for d, _ in race_results])
    log_t = np.array([math.log(t) for _, t in race_results])

    # Linear regression: log(T) = exponent * log(D) + log(k)
    n = len(race_results)
    sum_xy = np.sum(log_d * log_t)
    sum_x = np.sum(log_d)
    sum_y = np.sum(log_t)
    sum_x2 = np.sum(log_d ** 2)

    denom = n * sum_x2 - sum_x ** 2
    if abs(denom) < 1e-10:
        return 1.06
    exponent = (n * sum_xy - sum_x * sum_y) / denom

    # Clamp to reasonable range
    return max(1.01, min(1.25, exponent))


# ---------------------------------------------------------------------------
# Altitude adjustment
# ---------------------------------------------------------------------------

def altitude_adjustment_peronnet(altitude_m: float,
                                  acclimatized: bool = True) -> float:
    """Compute performance fraction at altitude relative to sea level.

    Peronnet, Thibault & Cousineau (1991):
      Non-acclimatized: y = 0.178x^3 - 1.43x^2 - 4.07x + 100
      Acclimatized:     y = -1.12x^2 - 1.90x + 99.9
    where x = altitude in km, y = aerobic power as % of sea level.

    Returns:
        Performance fraction (e.g. 0.97 means 3% slower than sea level).
    """
    x = altitude_m / 1000.0  # convert to km
    if x <= 0:
        return 1.0

    if acclimatized:
        pct = -1.12 * x ** 2 - 1.90 * x + 99.9
    else:
        pct = 0.178 * x ** 3 - 1.43 * x ** 2 - 4.07 * x + 100.0

    return max(0.5, min(1.0, pct / 100.0))


def altitude_time_adjustment(sea_level_time_s: float,
                              race_altitude_m: float,
                              training_altitude_m: float = 0,
                              acclimatized: bool = True) -> float:
    """Adjust a sea-level race time for race-day altitude.

    If athlete trains at altitude and races at similar/lower altitude,
    minimal adjustment is needed.

    Returns:
        Adjusted time in seconds.
    """
    race_factor = altitude_adjustment_peronnet(race_altitude_m, acclimatized)
    train_factor = altitude_adjustment_peronnet(training_altitude_m, acclimatized)

    # The athlete's known times are already at training altitude.
    # Adjust for the difference between race and training altitude.
    if train_factor <= 0:
        return sea_level_time_s
    relative_factor = race_factor / train_factor
    if relative_factor <= 0:
        return sea_level_time_s
    return sea_level_time_s / relative_factor


# ---------------------------------------------------------------------------
# Elevation gain adjustment
# ---------------------------------------------------------------------------

def elevation_gain_penalty_s(elevation_gain_ft: float,
                              distance_mi: float) -> float:
    """Estimate time penalty from elevation gain.

    Practical approximation adapted from Minetti et al. (2002):
      ~12 seconds per mile per 100ft of gain.

    Returns:
        Time penalty in seconds.
    """
    if distance_mi <= 0 or elevation_gain_ft <= 0:
        return 0.0
    return (elevation_gain_ft / 100.0) * 12.0


# ---------------------------------------------------------------------------
# Combined race prediction
# ---------------------------------------------------------------------------

@dataclass
class RacePrediction:
    """Prediction result for a single race."""
    race_name: str
    distance_m: float
    distance_label: str

    riegel_time_s: float
    riegel_personal_time_s: float
    cameron_time_s: float
    daniels_time_s: float

    altitude_adjustment_s: float
    elevation_penalty_s: float

    # Final predictions (with adjustments)
    predicted_low_s: float  # optimistic
    predicted_high_s: float  # conservative

    vdot: float
    personal_exponent: float


def predict_race(
    race_name: str,
    target_distance_m: float,
    distance_label: str,
    known_distance_m: float,
    known_time_s: float,
    personal_exponent: float = 1.06,
    race_altitude_m: float = 0,
    training_altitude_m: float = 0,
    elevation_gain_ft: float = 0,
    vdot: float = 0,
) -> RacePrediction:
    """Generate a full race prediction using all models."""
    distance_mi = target_distance_m / 1609.344

    riegel = predict_riegel(known_distance_m, known_time_s, target_distance_m)
    riegel_personal = predict_riegel(known_distance_m, known_time_s,
                                      target_distance_m, personal_exponent)
    cameron = predict_cameron(known_distance_m, known_time_s, target_distance_m)
    daniels = predict_daniels(known_distance_m, known_time_s, target_distance_m)

    # Altitude adjustment (applied to the average of models)
    avg_base = (riegel + cameron + daniels) / 3
    adjusted = altitude_time_adjustment(
        avg_base, race_altitude_m, training_altitude_m, acclimatized=True
    )
    alt_adj = adjusted - avg_base

    # Elevation penalty
    elev_penalty = elevation_gain_penalty_s(elevation_gain_ft, distance_mi)

    # Bounds: optimistic = fastest model + adjustments, conservative = slowest
    models = [riegel, cameron, daniels]
    predicted_low = min(models) + alt_adj + elev_penalty
    predicted_high = max(riegel_personal, max(models)) + alt_adj + elev_penalty

    predicted = (predicted_low + predicted_high) / 2
    logger.info("Race prediction for %s: %.1f min (ensemble)", race_name, predicted / 60.0)

    return RacePrediction(
        race_name=race_name,
        distance_m=target_distance_m,
        distance_label=distance_label,
        riegel_time_s=riegel,
        riegel_personal_time_s=riegel_personal,
        cameron_time_s=cameron,
        daniels_time_s=daniels,
        altitude_adjustment_s=alt_adj,
        elevation_penalty_s=elev_penalty,
        predicted_low_s=predicted_low,
        predicted_high_s=predicted_high,
        vdot=vdot,
        personal_exponent=personal_exponent,
    )


# =========================================================================
# 1RM Prediction
# =========================================================================

def estimate_1rm_epley(weight: float, reps: int) -> float:
    """Epley (1985): 1RM = w × (1 + r/30)"""
    if reps <= 0:
        return weight
    if reps == 1:
        return weight
    return weight * (1 + reps / 30.0)


def estimate_1rm_brzycki(weight: float, reps: int) -> float:
    """Brzycki (1993): 1RM = w × 36 / (37 - r)"""
    if reps <= 0 or reps >= 37:
        return weight
    if reps == 1:
        return weight
    return weight * 36.0 / (37.0 - reps)


def estimate_1rm_lombardi(weight: float, reps: int) -> float:
    """Lombardi (1989): 1RM = w × r^0.10"""
    if reps <= 0:
        return weight
    if reps == 1:
        return weight
    return weight * (reps ** 0.10)


def estimate_1rm_wathan(weight: float, reps: int) -> float:
    """Wathan (1994): 1RM = 100w / (48.8 + 53.8 × e^(-0.075r))"""
    if reps <= 0 or reps == 1:
        return weight
    return (100.0 * weight) / (48.8 + 53.8 * math.exp(-0.075 * reps))


def estimate_1rm_mayhew(weight: float, reps: int) -> float:
    """Mayhew et al. (1992): 1RM = 100w / (52.2 + 41.9 × e^(-0.055r))"""
    if reps <= 0 or reps == 1:
        return weight
    return (100.0 * weight) / (52.2 + 41.9 * math.exp(-0.055 * reps))


_1RM_METHODS = {
    "epley": estimate_1rm_epley,
    "brzycki": estimate_1rm_brzycki,
    "lombardi": estimate_1rm_lombardi,
    "wathan": estimate_1rm_wathan,
    "mayhew": estimate_1rm_mayhew,
}


def estimate_1rm(weight: float, reps: int, rir: int = 0,
                  method: str = "ensemble") -> float:
    """Estimate 1RM from a working set.

    Args:
        weight: Weight lifted.
        reps: Reps performed.
        rir: Reps in reserve (Zourdos et al., 2016). For programmed
             strength work (not to failure), typically 2.
        method: One of "epley", "brzycki", "lombardi", "wathan", "mayhew",
                or "ensemble" (average of all — LeSuer et al. 1997).

    Returns:
        Estimated 1RM.
    """
    effective_reps = reps + rir

    if method == "ensemble":
        estimates = [fn(weight, effective_reps) for fn in _1RM_METHODS.values()]
        return sum(estimates) / len(estimates)

    fn = _1RM_METHODS.get(method, estimate_1rm_epley)
    return fn(weight, effective_reps)


def estimate_1rm_all_methods(weight: float, reps: int,
                              rir: int = 0) -> dict[str, float]:
    """Return 1RM estimates from all methods plus ensemble."""
    effective_reps = reps + rir
    results = {name: fn(weight, effective_reps)
               for name, fn in _1RM_METHODS.items()}
    results["ensemble"] = sum(results.values()) / len(results)
    return results


# ---------------------------------------------------------------------------
# 1RM progression from lifting program data
# ---------------------------------------------------------------------------

def extract_1rm_progression(df: pd.DataFrame, lift: str = "bench") -> pd.DataFrame:
    """Extract estimated 1RM over time for a given lift from enriched data.

    Detects actual 1RM tests (1x1) and uses them as ground truth.
    Estimates from working sets are capped at the most recent tested 1RM.
    """
    weight_col = f"{lift}_weight"
    volume_col = f"{lift}_volume"

    if weight_col not in df.columns:
        return pd.DataFrame()

    lifts = df[df[weight_col].notna() & (df[weight_col] > 0)].copy()
    if lifts.empty:
        return pd.DataFrame()

    # First pass: find actual 1RM tests (1x1 = volume equals weight)
    tested_1rm = None
    tested_1rm_date = None
    rows = []

    for _, row in lifts.sort_values("date").iterrows():
        w = row[weight_col]
        vol = row.get(volume_col, 0) or 0
        is_test = vol > 0 and abs(vol - w) < 1  # 1x1 test

        if is_test:
            # Actual tested 1RM — use as ground truth
            tested_1rm = w
            tested_1rm_date = row["date"]
            estimates = {m: w for m in _1RM_METHODS}
            estimates["ensemble"] = w
            reps_per_set = 1
        else:
            # Working set — estimate 1RM
            if w > 0 and vol > 0:
                total_reps = vol / w
                reps_per_set = min(int(round(total_reps / 3)), 10)
                if reps_per_set < 1:
                    reps_per_set = 1
            else:
                reps_per_set = 1

            estimates = estimate_1rm_all_methods(w, reps_per_set, rir=2)

            # Cap at tested 1RM if this session is AFTER the test
            if tested_1rm and row["date"] >= tested_1rm_date:
                for k in estimates:
                    estimates[k] = min(estimates[k], tested_1rm)

        rows.append({
            "date": row["date"],
            "program_day": row.get("program_day"),
            "weight": w,
            "volume": vol,
            "reps_per_set": reps_per_set,
            "is_test": is_test,
            "estimated_1rm": estimates["ensemble"],
            **{f"1rm_{k}": v for k, v in estimates.items() if k != "ensemble"},
        })

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def fit_strength_curve(days: np.ndarray, estimated_1rms: np.ndarray,
                        model: str = "log") -> tuple:
    """Fit a progression curve to 1RM estimates over time.

    The logarithmic model reflects diminishing returns (Zatsiorsky &
    Kraemer, 2006, Science and Practice of Strength Training).

    Args:
        days: Array of day numbers (0-indexed from program start).
        estimated_1rms: Array of estimated 1RM values.
        model: "linear" or "log".

    Returns:
        (predict_fn, params) where predict_fn(day) returns predicted 1RM.
    """
    from scipy.optimize import curve_fit

    if len(days) < 2:
        avg = np.mean(estimated_1rms)
        return lambda d: avg, (avg,)

    if model == "log":
        def log_model(x, a, b):
            return a * np.log(x + 1) + b

        try:
            params, _ = curve_fit(log_model, days, estimated_1rms,
                                   p0=[20.0, estimated_1rms[0]])
            return lambda d: log_model(d, *params), params
        except (RuntimeError, ValueError):
            model = "linear"  # fallback

    # Linear model
    coeffs = np.polyfit(days, estimated_1rms, 1)
    poly = np.poly1d(coeffs)
    return lambda d: poly(d), tuple(coeffs)
