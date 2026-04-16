"""Flask REST API endpoints.

GET endpoints (`api_key_read` auth) — used by the ChatGPT GPT Action and MCP.
Write endpoints (`api_key_write` auth) — CRUD on activities + sync triggers.
"""

import logging
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

from strava_analytics.db import meron_dir, session_scope
from strava_analytics.db.models import Activity, SyncState
from strava_analytics.db.repository import (
    create_manual_activity,
    patch_activity,
    soft_delete_activity,
)
from strava_analytics.services.enrichment_service import invalidate_cache
from strava_analytics.services.ingestion.strava_csv import ingest_bulk
from strava_analytics.services.sync import run_strava_sync
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


logger = logging.getLogger(__name__)


# Fields an API consumer may set on a manual activity create.
_MANUAL_CREATE_FIELDS = {
    "name", "type", "description", "gear", "start_time",
    "elapsed_time_s", "moving_time_s", "distance_m",
    "elevation_gain_m", "max_hr", "avg_hr", "avg_watts", "calories",
    "weather_condition", "weather_temp_c",
}

# Fields the PATCH endpoint will accept (for both manual and override layers).
_PATCH_FIELDS = _MANUAL_CREATE_FIELDS | {
    "filename", "max_speed_ms", "avg_speed_ms",
    "elevation_loss_m", "elevation_low_m", "elevation_high_m",
    "relative_effort", "grade_adj_distance_m",
    "total_steps", "training_load", "intensity",
    "competition", "strava_with_kid",
}


def _api_keys() -> tuple[str, str]:
    """Return (read_key, write_key). Empty strings when no row exists yet."""
    with session_scope() as session:
        row = session.query(SyncState).filter(
            SyncState.user_id == 1,
            SyncState.provider == "strava",
        ).first()
        if row is None:
            return "", ""
        return row.api_key_read or "", row.api_key_write or ""


def _parse_datetime(value):
    """Accept ISO strings or datetimes. Return a tz-naive datetime (local)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            # Convert to US/Mountain local (matches loader behavior)
            import zoneinfo
            dt = dt.astimezone(zoneinfo.ZoneInfo("US/Mountain")).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def register_api(server: Flask) -> None:
    """Register all /api/* routes on the Flask server."""

    @server.before_request
    def _check_api_key():
        if not request.path.startswith("/api/"):
            return None
        # openapi.yaml is public (needed by ChatGPT without a key)
        if request.path == "/api/openapi.yaml":
            return None
        read_key, write_key = _api_keys()
        provided = request.headers.get("X-API-Key", "")
        method = request.method
        # Back-compat: the old athlete_config.json "api_key" is accepted too
        legacy = data.get_athlete_config().get("api_key", "")
        if method in ("GET", "HEAD"):
            allowed = {read_key, write_key, legacy} - {""}
            if allowed and provided not in allowed:
                return jsonify({"error": "Unauthorized"}), 401
        else:
            allowed = {write_key, legacy} - {""}
            if not allowed or provided not in allowed:
                return jsonify({"error": "Unauthorized (write access required)"}), 401
        return None

    def _df():
        return data.get_df()

    # ─── Read endpoints (unchanged) ────────────────────────────────

    @server.route("/api/fitness")
    def api_fitness():
        return jsonify(get_fitness_summary(_df()))

    @server.route("/api/stats")
    def api_stats():
        return jsonify(get_lifetime_stats(_df()))

    @server.route("/api/activities", methods=["GET", "POST"])
    def api_activities():
        if request.method == "GET":
            days = request.args.get("days", 14, type=int)
            limit = request.args.get("limit", 20, type=int)
            return jsonify(get_recent_activities(_df(), days=days, limit=limit))
        # POST — create a manual activity
        return _create_manual_activity()

    @server.route("/api/activities/<int:activity_id>", methods=["PATCH", "DELETE"])
    def api_activity(activity_id: int):
        if request.method == "PATCH":
            return _patch_activity(activity_id)
        return _delete_activity(activity_id)

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

    # ─── Write endpoints (new) ─────────────────────────────────────

    @server.route("/api/sync/strava", methods=["POST"])
    def api_sync_strava():
        with session_scope() as session:
            report = run_strava_sync(user_id=1, session=session)
        data.reload()
        return jsonify(report)

    @server.route("/api/sync/upload", methods=["POST"])
    def api_sync_upload():
        f = request.files.get("file")
        if f is None:
            return jsonify({"error": "no file uploaded"}), 400
        report = _handle_upload(f)
        data.reload()
        return jsonify(report)

    @server.route("/api/sync/apple-health", methods=["POST"])
    def api_sync_apple_health():
        return jsonify({
            "error": "Apple Health ingest not yet implemented",
        }), 501


# ─── Write helpers ──────────────────────────────────────────────────────

def _create_manual_activity() -> Response:
    body = request.get_json(silent=True) or {}
    payload = {}
    for k in _MANUAL_CREATE_FIELDS:
        if k in body:
            if k == "start_time":
                payload[k] = _parse_datetime(body[k])
            else:
                payload[k] = body[k]
    # Minimum required
    if not payload.get("type") or not payload.get("start_time"):
        return jsonify({"error": "type and start_time are required"}), 400

    with session_scope() as session:
        act = create_manual_activity(session, user_id=1, payload=payload)
        new_id = act.id
    invalidate_cache()
    return jsonify({"id": new_id}), 201


def _patch_activity(activity_id: int) -> Response:
    body = request.get_json(silent=True) or {}
    patch = {}
    for k, v in body.items():
        if k not in _PATCH_FIELDS:
            continue
        if k == "start_time":
            patch[k] = _parse_datetime(v)
        else:
            patch[k] = v
    if not patch:
        return jsonify({"error": "no editable fields provided"}), 400
    with session_scope() as session:
        row = patch_activity(session, activity_id=activity_id, patch=patch)
        if row is None:
            return jsonify({"error": "not found"}), 404
    invalidate_cache()
    return jsonify({"id": activity_id, "updated": list(patch.keys())})


def _delete_activity(activity_id: int) -> Response:
    with session_scope() as session:
        ok = soft_delete_activity(session, activity_id=activity_id)
    if not ok:
        return jsonify({"error": "not found"}), 404
    invalidate_cache()
    return jsonify({"id": activity_id, "deleted": True})


def _handle_upload(file_storage) -> dict:
    """Handle a browser upload: csv or zip containing an activities.csv."""
    upload_root = meron_dir() / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = upload_root / ts
    dest.mkdir()

    filename = (file_storage.filename or "upload").lower()
    tmp_path = dest / (Path(filename).name or "upload.bin")
    file_storage.save(str(tmp_path))

    if filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(tmp_path) as zf:
                zf.extractall(dest)
        except zipfile.BadZipFile:
            return {"inserted": 0, "updated": 0, "skipped": 0,
                    "errors": ["bad zip file"]}
        # Find an inner dir containing activities.csv
        target = None
        for candidate in [dest, *dest.iterdir()]:
            if (candidate / "activities.csv").exists():
                target = candidate
                break
        if target is None:
            return {"inserted": 0, "updated": 0, "skipped": 0,
                    "errors": ["activities.csv not found inside zip"]}
    elif filename.endswith(".csv"):
        # Accept a bare activities.csv — write it into the dest dir under the
        # expected name
        if tmp_path.name != "activities.csv":
            shutil.copy2(tmp_path, dest / "activities.csv")
        target = dest
    else:
        return {"inserted": 0, "updated": 0, "skipped": 0,
                "errors": [f"unsupported file extension: {filename}"]}

    with session_scope() as session:
        report = ingest_bulk(target, user_id=1, session=session)
    return report
