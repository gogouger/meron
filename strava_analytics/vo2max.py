"""VO2max and VDOT estimation from running performance and heart rate data.

References:
  - Daniels, J. (2014). Daniels' Running Formula, 3rd ed. Human Kinetics.
  - Uth, N. et al. (2004). Estimation of VO2max from the ratio between
    HRmax and HRrest. European J Applied Physiology, 91(1), 111-115.
  - Cooper, K.H. (1968). A means of assessing maximal oxygen intake.
    JAMA, 203(3), 201-204.
"""

import logging
import math

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Daniels VDOT model
# ---------------------------------------------------------------------------

def _vo2_cost(velocity_m_per_min: float) -> float:
    """Oxygen cost of running at a given velocity (ml/kg/min).

    Daniels & Gilbert (1979), updated in Daniels (2014).
    """
    v = velocity_m_per_min
    return -4.60 + 0.182258 * v + 0.000104 * v ** 2


def _vo2max_fraction(time_min: float) -> float:
    """Fraction of VO2max sustainable for a given race duration.

    Daniels & Gilbert (1979), updated in Daniels (2014).
    """
    t = time_min
    return (0.8 + 0.1894393 * math.exp(-0.012778 * t)
            + 0.2989558 * math.exp(-0.1932605 * t))


def daniels_vdot(distance_m: float, time_min: float) -> float:
    """Compute VDOT (pseudo-VO2max) from a race result.

    Args:
        distance_m: Race distance in meters.
        time_min: Finish time in minutes.

    Returns:
        VDOT in ml/kg/min.
    """
    if time_min <= 0 or distance_m <= 0:
        return 0.0
    velocity = distance_m / time_min  # m/min
    vo2 = _vo2_cost(velocity)
    fraction = _vo2max_fraction(time_min)
    if fraction <= 0:
        logger.debug("VDOT calculation: fraction <= 0 for dist=%s time=%s", distance_m, time_min)
        return 0.0
    return vo2 / fraction


# ---------------------------------------------------------------------------
# Intensity-corrected VDOT for training runs
# ---------------------------------------------------------------------------

# Approximate %VO2max sustained in each HR zone (Daniels / ACSM guidelines)
_ZONE_VO2_FRACTION = {1: 0.60, 2: 0.70, 3: 0.80, 4: 0.88, 5: 0.95}


def intensity_from_zones(zone_seconds: dict[int, float]) -> float:
    """Compute weighted-average %VO2max from per-zone time distribution.

    Args:
        zone_seconds: {1: seconds_in_z1, 2: seconds_in_z2, ...}

    Returns:
        Weighted intensity fraction (0.0–1.0).
    """
    total = sum(zone_seconds.values())
    if total <= 0:
        return 0.0
    weighted = sum(_ZONE_VO2_FRACTION.get(z, 0.70) * s
                   for z, s in zone_seconds.items())
    return weighted / total


def daniels_vdot_adjusted(distance_m: float, time_min: float,
                           intensity_fraction: float) -> float:
    """Compute VDOT corrected for sub-maximal effort using HR-derived intensity.

    Instead of assuming race effort (the standard Daniels fraction), uses
    the actual intensity fraction from HR zone data.

    Args:
        distance_m: Run distance in meters.
        time_min: Moving time in minutes.
        intensity_fraction: Fraction of VO2max sustained (from HR zones).

    Returns:
        Corrected VDOT in ml/kg/min.
    """
    if time_min <= 0 or distance_m <= 0 or intensity_fraction <= 0:
        return 0.0
    velocity = distance_m / time_min
    vo2 = _vo2_cost(velocity)
    return vo2 / intensity_fraction


def vdot_to_velocity(vdot: float, time_min: float) -> float:
    """Given a VDOT and race duration, find the sustainable velocity (m/min).

    Solves: VDOT * F(t) = VO2(v) for v using the quadratic formula.
    """
    target_vo2 = vdot * _vo2max_fraction(time_min)
    # VO2 = -4.60 + 0.182258*v + 0.000104*v^2
    # 0.000104*v^2 + 0.182258*v + (-4.60 - target_vo2) = 0
    a = 0.000104
    b = 0.182258
    c = -4.60 - target_vo2
    discriminant = b ** 2 - 4 * a * c
    if discriminant < 0:
        return 0.0
    return (-b + math.sqrt(discriminant)) / (2 * a)


def vdot_to_race_time(vdot: float, distance_m: float,
                       min_time: float = 3.0, max_time: float = 600.0,
                       tol: float = 0.01) -> float:
    """Predict race time (minutes) for a given VDOT and distance.

    Uses bisection to solve: daniels_vdot(distance_m, t) = vdot for t.
    """
    lo, hi = min_time, max_time
    for _ in range(100):
        mid = (lo + hi) / 2
        computed = daniels_vdot(distance_m, mid)
        if abs(computed - vdot) < tol:
            return mid
        if computed > vdot:
            lo = mid  # slower time → lower VDOT
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# Heart-rate-based VO2max
# ---------------------------------------------------------------------------

def vo2max_from_hr(max_hr: float, resting_hr: float) -> float:
    """Estimate VO2max from max and resting heart rate.

    Uth et al. (2004): VO2max ≈ 15.3 × (HRmax / HRrest)
    """
    if resting_hr <= 0:
        return 0.0
    return 15.3 * (max_hr / resting_hr)


# ---------------------------------------------------------------------------
# Extract best efforts from Strava data
# ---------------------------------------------------------------------------

# Standard race distances in meters
STANDARD_DISTANCES = {
    "1 mile": 1609.344,
    "5K": 5000.0,
    "10K": 10000.0,
    "Half Marathon": 21097.5,
    "Marathon": 42195.0,
}


def extract_race_efforts(df: pd.DataFrame) -> list[dict]:
    """Find the best race-type efforts from the enriched DataFrame.

    Returns a list of dicts with keys: distance_m, time_min, time_s,
    pace_min_per_mi, name, date, vdot, elevation_gain_ft, elevation_mid_ft.
    """
    runs = df[(df["type"] == "Run")].copy()
    if "run_type" in runs.columns:
        races = runs[runs["run_type"].isin(["race", "hard_effort"])]
        if races.empty:
            races = runs
    else:
        races = runs

    efforts = []
    for _, row in races.iterrows():
        dist_m = row.get("distance_m", 0)
        time_s = row.get("moving_time_s", 0)
        if dist_m <= 0 or time_s <= 0:
            continue

        # Gate workout-type efforts: require Z3+ HR to confirm intensity.
        # If no HR data available, include it (can't know).
        if row.get("run_type") == "workout":
            hr_zone = row.get("hr_zone")
            if hr_zone is not None and not (isinstance(hr_zone, float) and pd.isna(hr_zone)):
                if int(hr_zone) < 3:
                    continue  # Low-HR workout is not a quality effort signal

        time_min = time_s / 60.0
        vdot = daniels_vdot(dist_m, time_min)

        elev_gain_ft = row.get("elevation_gain_ft", 0) or 0
        elev_high_m = row.get("elevation_high_m", 0) or 0
        elev_low_m = row.get("elevation_low_m", 0) or 0
        elev_mid_ft = ((elev_high_m + elev_low_m) / 2) * 3.28084 if (elev_high_m + elev_low_m) > 0 else 0

        efforts.append({
            "distance_m": dist_m,
            "time_min": time_min,
            "time_s": time_s,
            "pace_min_per_mi": row.get("pace_min_per_mi", 0),
            "name": row.get("name", ""),
            "date": row.get("date"),
            "vdot": vdot,
            "elevation_gain_ft": elev_gain_ft,
            "elevation_mid_ft": elev_mid_ft,
        })

    efforts.sort(key=lambda x: x["vdot"], reverse=True)
    return efforts


def compute_training_elevation(df: pd.DataFrame) -> dict:
    """Extract actual training elevation stats from run data."""
    runs = df[df["type"] == "Run"]
    if runs.empty:
        return {"mid_ft": 5800, "avg_gain_per_mi": 55}

    elev_high = runs["elevation_high_m"].dropna()
    elev_low = runs["elevation_low_m"].dropna()

    if elev_high.empty or elev_low.empty:
        return {"mid_ft": 5800, "avg_gain_per_mi": 55}

    mid_m = (elev_high.mean() + elev_low.mean()) / 2
    mid_ft = mid_m * 3.28084

    runs_with_gain = runs[runs["elevation_gain_ft"] > 0]
    if not runs_with_gain.empty and runs_with_gain["distance_mi"].sum() > 0:
        avg_gain_per_mi = runs_with_gain["elevation_gain_ft"].sum() / runs_with_gain["distance_mi"].sum()
    else:
        avg_gain_per_mi = 0

    return {"mid_ft": mid_ft, "avg_gain_per_mi": avg_gain_per_mi}


def compute_athlete_vdot(df: pd.DataFrame, n_best: int = 5,
                          recent_weight: float = 2.0) -> float:
    """Compute a weighted-average VDOT from the athlete's best efforts.

    More recent efforts receive higher weight.

    Args:
        df: Enriched activity DataFrame.
        n_best: Number of top efforts to consider.
        recent_weight: Weight multiplier for recency (applied linearly).

    Returns:
        Weighted average VDOT.
    """
    efforts = extract_race_efforts(df)
    if not efforts:
        return 0.0

    top = efforts[:n_best]
    if not top:
        return 0.0

    # Sort by date ascending for recency weighting
    top.sort(key=lambda x: x["date"] if x["date"] is not None else pd.Timestamp.min)

    total_weight = 0.0
    weighted_vdot = 0.0
    for i, effort in enumerate(top):
        # Linear recency weight: oldest=1.0, newest=recent_weight
        w = 1.0 + (recent_weight - 1.0) * i / max(len(top) - 1, 1)
        weighted_vdot += effort["vdot"] * w
        total_weight += w

    return weighted_vdot / total_weight if total_weight > 0 else 0.0
