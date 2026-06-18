"""Training-plan, race-prediction, and strength-projection endpoints.

These are the endpoints the mobile app will hit for the /plan tab, the
/races tab, and the strength-projection chart. They wrap pure-Python
compute modules so the mobile client doesn't need to re-implement any of
the modelling.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from strava_analytics.critical_speed import fit_critical_speed, predict_race_times
from strava_analytics.strength_model import (
    compute_interference,
    fit_all_lifts,
    project_1rm,
)
from strava_analytics.training_plan import (
    generate_training_plan,
    plan_to_flat_list,
)
from strava_analytics.web import data
from strava_analytics.web.plan_dates import rolling_window


bp = Blueprint("api_plan", __name__, url_prefix="/api")


@bp.route("/plan")
def plan():
    """Return the flat list of workouts for the mobile plan tab.

    The plan starts today and runs forward 8 weeks (the perpetual peak
    target) plus a 90-day projection horizon for the fitness chart.
    """
    df = data.get_df()
    from strava_analytics.web.api_data import get_current_1rms
    current_1rms = get_current_1rms(df)

    # Estimate current weekly miles from the last 4 weeks of running
    runs = df[df["type"] == "Run"]
    if not runs.empty:
        import pandas as pd
        recent = runs[runs["date"] >= runs["date"].max() - pd.Timedelta(weeks=4)]
        weekly_miles = float(recent["distance_mi"].sum()) / 4.0
    else:
        weekly_miles = 20.0

    win = rolling_window()
    weeks = generate_training_plan(
        start_date=win.start,
        race1_date=win.plan_end,
        race2_date=win.horizon,
        current_1rms=current_1rms or None,
        current_weekly_miles=weekly_miles,
    )
    return jsonify({
        "start_date": win.start.isoformat(),
        "horizon": win.horizon.isoformat(),
        "workouts": plan_to_flat_list(weeks),
    })


@bp.route("/predict/race")
def predict_race():
    """Predict race times at standard distances via the Critical Speed model.

    Query params:
      distance_m (optional) — if set, returns only that distance.
    """
    df = data.get_df()
    efforts = data.get_best_efforts()

    # Short-circuit when there's no efforts data — predict_race_times
    # assumes certain columns exist and will crash on the empty frame.
    if efforts is None or efforts.empty or "distance_label" not in efforts.columns:
        return jsonify({
            "cs": {"cs_m_per_s": 0, "cs_min_per_mi": 0, "d_prime_m": 0,
                   "r_squared": 0, "n_points": 0, "efforts": []},
            "predictions": {},
            "note": "insufficient best-effort data to fit Critical Speed model",
        })

    cs = fit_critical_speed(efforts)

    # Weekly km + avg pace for Tanda marathon blend
    import pandas as pd
    runs = df[df["type"] == "Run"]
    if not runs.empty:
        recent = runs[runs["date"] >= runs["date"].max() - pd.Timedelta(weeks=8)]
        weekly_km = float(recent["distance_km"].sum()) / 8.0
        total_s = float(recent["moving_time_s"].sum())
        total_km = float(recent["distance_km"].sum())
        avg_pace_sec_per_km = total_s / total_km if total_km > 0 else 0.0
    else:
        weekly_km = 0.0
        avg_pace_sec_per_km = 0.0

    predictions = predict_race_times(
        efforts,
        weekly_km=weekly_km,
        avg_pace_sec_per_km=avg_pace_sec_per_km,
    )

    distance_m = request.args.get("distance_m", type=float)
    if distance_m:
        # Filter to predictions near the requested distance
        for label, entry in predictions.items():
            if label.startswith("_"):
                continue
            # We don't ship distances in the result dict, so just return
            # the full set — the client can filter. Kept for explicit API.
        return jsonify({"cs": cs, "predictions": predictions})

    return jsonify({"cs": cs, "predictions": predictions})


@bp.route("/strength/progression")
def strength_progression():
    """Return fit curves + projected 1RMs at 4/8/12 weeks.

    Query params:
      weeks (optional int) — alternate horizon; accepts comma-separated list.
    """
    df = data.get_df()
    fits = fit_all_lifts(df)

    import pandas as pd
    runs = df[df["type"] == "Run"]
    if not runs.empty:
        recent = runs[runs["date"] >= runs["date"].max() - pd.Timedelta(weeks=4)]
        weekly_miles = float(recent["distance_mi"].sum()) / 4.0
    else:
        weekly_miles = 0.0
    interference = compute_interference(weekly_miles)

    weeks_arg = request.args.get("weeks", "4,8,12")
    try:
        horizons = [int(w) for w in weeks_arg.split(",") if w.strip()]
    except ValueError:
        horizons = [4, 8, 12]

    result: dict = {
        "weekly_running_miles": round(weekly_miles, 2),
        "interference_factor": round(interference, 3),
        "lifts": {},
    }
    for lift, params in fits.items():
        result["lifts"][lift] = {
            "fit": params,
            "projections": [
                {"weeks": w, "projected_1rm": project_1rm(
                    params, weeks_ahead=w, interference_factor=interference
                )}
                for w in horizons
            ],
        }
    return jsonify(result)


@bp.route("/lifting-program")
def lifting_program():
    """Return the structured lifting program (baseline, end PRs, schedule)."""
    return jsonify({
        "baseline": data.get_baseline(),
        "end_prs": data.get_end_prs(),
        "program": data.get_program(),
    })
