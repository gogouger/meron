"""Sync-trigger endpoints (Strava API pull, bulk upload, Apple Health stub)."""

from __future__ import annotations

import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from strava_analytics.db import meron_dir, session_scope
from strava_analytics.services.ingestion.strava_csv import ingest_bulk
from strava_analytics.services.sync import run_strava_sync
from strava_analytics.web import data

from ..context import require_user_id


bp = Blueprint("api_sync", __name__, url_prefix="/api/sync")


@bp.route("/strava", methods=["POST"])
def sync_strava():
    uid = require_user_id()
    with session_scope() as session:
        report = run_strava_sync(user_id=uid, session=session)
    data.reload()
    return jsonify(report)


@bp.route("/upload", methods=["POST"])
def sync_upload():
    uid = require_user_id()
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": {"code": "bad_request",
                                  "message": "no file uploaded"}}), 400
    report = _handle_upload(f, uid)
    data.reload()
    return jsonify(report)


@bp.route("/apple-health", methods=["POST"])
def sync_apple_health():
    return jsonify({
        "error": {"code": "not_implemented",
                  "message": "Apple Health ingest not yet implemented"}
    }), 501


def _handle_upload(file_storage, uid: int) -> dict:
    """Unzip / copy the uploaded payload into ~/.meron/uploads/ and ingest."""
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
        target = None
        for candidate in [dest, *dest.iterdir()]:
            if (candidate / "activities.csv").exists():
                target = candidate
                break
        if target is None:
            return {"inserted": 0, "updated": 0, "skipped": 0,
                    "errors": ["activities.csv not found inside zip"]}
    elif filename.endswith(".csv"):
        if tmp_path.name != "activities.csv":
            shutil.copy2(tmp_path, dest / "activities.csv")
        target = dest
    else:
        return {"inserted": 0, "updated": 0, "skipped": 0,
                "errors": [f"unsupported file extension: {filename}"]}

    with session_scope() as session:
        report = ingest_bulk(target, user_id=uid, session=session)
    return report
