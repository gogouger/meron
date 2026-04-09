"""Flask REST API endpoints for ChatGPT GPT Actions integration.

Registers /api/* routes on the Dash app's underlying Flask server.
All endpoints return JSON. Optional API key auth via X-API-Key header.
"""

from pathlib import Path

from flask import Flask, jsonify, request, send_file

from strava_analytics.web import data
from strava_analytics.web.api_data import (
    get_fitness_summary,
    get_lifetime_stats,
    get_recent_activities,
    get_weekly_mileage,
    get_current_1rms,
    get_personal_records,
    get_detailed_runs,
    get_detailed_lifts,
    get_athlete_summary,
)


def register_api(server: Flask) -> None:
    """Register all /api/* routes on the Flask server."""

    @server.before_request
    def _check_api_key():
        if not request.path.startswith("/api/"):
            return None
        config = data.get_athlete_config()
        expected = config.get("api_key", "")
        if expected and request.headers.get("X-API-Key") != expected:
            return jsonify({"error": "Unauthorized"}), 401
        return None

    def _df():
        return data.get_df()

    @server.route("/api/fitness")
    def api_fitness():
        return jsonify(get_fitness_summary(_df()))

    @server.route("/api/stats")
    def api_stats():
        return jsonify(get_lifetime_stats(_df()))

    @server.route("/api/activities")
    def api_activities():
        days = request.args.get("days", 14, type=int)
        limit = request.args.get("limit", 20, type=int)
        return jsonify(get_recent_activities(_df(), days=days, limit=limit))

    @server.route("/api/mileage")
    def api_mileage():
        weeks = request.args.get("weeks", 8, type=int)
        return jsonify(get_weekly_mileage(_df(), weeks=weeks))

    @server.route("/api/records")
    def api_records():
        return jsonify(get_personal_records(_df()))

    @server.route("/api/strength")
    def api_strength():
        return jsonify(get_current_1rms(_df()))

    @server.route("/api/runs")
    def api_runs():
        limit = request.args.get("limit", 30, type=int)
        return jsonify(get_detailed_runs(_df(), limit=limit))

    @server.route("/api/lifts")
    def api_lifts():
        limit = request.args.get("limit", 20, type=int)
        return jsonify(get_detailed_lifts(_df(), limit=limit))

    @server.route("/api/summary")
    def api_summary():
        return jsonify(get_athlete_summary(_df()))

    @server.route("/api/openapi.yaml")
    def api_openapi():
        yaml_path = Path(__file__).parent / "openapi.yaml"
        return send_file(yaml_path, mimetype="text/yaml")
