"""Read-only metric endpoints.

Thin wrappers around ``web/api_data.py``. These are the endpoints the
mobile app, ChatGPT GPT Action, and MCP server all consume.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from strava_analytics.web import data
from strava_analytics.web.api_data import (
    get_athlete_summary,
    get_current_1rms,
    get_detailed_lifts,
    get_detailed_runs,
    get_fitness_summary,
    get_lifetime_stats,
    get_personal_records,
    get_recent_activities,
    get_weekly_mileage,
)


bp = Blueprint("api_metrics", __name__, url_prefix="/api")


def _df():
    return data.get_df()


@bp.route("/fitness")
def fitness():
    return jsonify(get_fitness_summary(_df()))


@bp.route("/fitness/timeseries")
def fitness_timeseries():
    """Daily CTL/ATL/TSB timeseries for charting."""
    from strava_analytics.web.plan_data import get_fitness_timeseries

    days = request.args.get("days", 90, type=int)
    ts = get_fitness_timeseries(_df(), days=days)
    if ts.empty:
        return jsonify([])
    return jsonify([
        {
            "date": d.strftime("%Y-%m-%d"),
            "ctl": round(float(c), 2) if c == c else None,
            "atl": round(float(a), 2) if a == a else None,
            "tsb": round(float(t), 2) if t == t else None,
        }
        for d, c, a, t in zip(ts["date"], ts["ctl"], ts["atl"], ts["tsb"])
    ])


@bp.route("/stats")
def stats():
    return jsonify(get_lifetime_stats(_df()))


@bp.route("/mileage")
def mileage():
    weeks = request.args.get("weeks", 8, type=int)
    return jsonify(get_weekly_mileage(_df(), weeks=weeks))


@bp.route("/records")
def records():
    return jsonify(get_personal_records(_df()))


@bp.route("/strength")
def strength():
    return jsonify(get_current_1rms(_df()))


@bp.route("/runs")
def runs():
    limit = request.args.get("limit", 30, type=int)
    return jsonify(get_detailed_runs(_df(), limit=limit))


@bp.route("/lifts")
def lifts():
    limit = request.args.get("limit", 20, type=int)
    return jsonify(get_detailed_lifts(_df(), limit=limit))


@bp.route("/summary")
def summary():
    return jsonify(get_athlete_summary(_df()))
