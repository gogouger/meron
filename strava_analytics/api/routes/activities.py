"""Activity CRUD endpoints.

GET list and individual detail are read-only.
POST / PATCH / DELETE mutate and invalidate the enrichment cache.
"""

from __future__ import annotations

import pandas as pd
from flask import Blueprint, jsonify, request

from strava_analytics.db import session_scope
from strava_analytics.db.models import Activity
from strava_analytics.db.repository import (
    create_manual_activity,
    patch_activity,
    soft_delete_activity,
)
from strava_analytics.services.enrichment_service import invalidate_cache
from strava_analytics.web import data
from strava_analytics.web.api_data import get_activity_feed, get_recent_activities

from ..context import current_user_id, require_user_id
from ..errors import NotFound, ValidationError
from ..schemas import ActivityCreate, ActivityPatch


bp = Blueprint("api_activities", __name__, url_prefix="/api")


@bp.route("/activities", methods=["GET", "POST"])
def activities_collection():
    if request.method == "GET":
        days = request.args.get("days", 14, type=int)
        limit = request.args.get("limit", 20, type=int)
        return jsonify(get_recent_activities(data.get_df(), days=days, limit=limit))

    # POST — create a manual activity
    uid = require_user_id()
    payload = ActivityCreate.model_validate(request.get_json(silent=True) or {})
    with session_scope() as session:
        act = create_manual_activity(
            session,
            user_id=uid,
            payload=payload.to_db_payload(),
        )
        new_id = act.id
    invalidate_cache()
    return jsonify({"id": new_id}), 201


@bp.route("/activities/feed")
def activities_feed():
    """Cursor-paginated feed for the mobile infinite scroll.

    Returns ``{items, next_cursor}``. Pass ``?cursor=<value>`` from the
    previous response to fetch the next page. Omit it for the first page.
    """
    cursor = request.args.get("cursor") or None
    limit = request.args.get("limit", 20, type=int)
    # Cap the limit so a malicious client can't ask for the whole DB.
    limit = max(1, min(limit, 100))
    return jsonify(get_activity_feed(data.get_df(), cursor=cursor, limit=limit))


@bp.route("/activities/<int:activity_id>", methods=["GET", "PATCH", "DELETE"])
def activity_detail(activity_id: int):
    if request.method == "GET":
        return _get_activity(activity_id)
    if request.method == "PATCH":
        return _patch_activity(activity_id)
    return _delete_activity(activity_id)


# ──────────────────────────────────────────────────────────────────────


def _get_activity(activity_id: int):
    """Return a single activity's full enriched record."""
    with session_scope() as session:
        act = session.get(Activity, activity_id)
        if act is None or act.deleted_at is not None:
            raise NotFound(f"activity {activity_id} not found")
        if act.user_id != current_user_id():
            raise NotFound(f"activity {activity_id} not found")

    df = data.get_df()
    # Repository exposes the DB row id on the DataFrame as `_id`.
    if "_id" in df.columns:
        matches = df[df["_id"] == activity_id]
    else:
        matches = df.iloc[0:0]

    if matches.empty:
        # Row exists but isn't in the enriched frame (e.g. malformed).
        raise NotFound(f"activity {activity_id} not enriched")

    return jsonify(_row_to_dict(matches.iloc[0]))


def _row_to_dict(row: pd.Series) -> dict:
    """Serialize a DataFrame row to JSON-safe primitives."""
    out: dict = {}
    for key, val in row.items():
        if key.startswith("_") and key != "_id":
            continue
        if pd.isna(val):
            continue
        if isinstance(val, pd.Timestamp):
            out[key] = val.isoformat()
        elif isinstance(val, (pd.Period,)):
            out[key] = str(val)
        elif isinstance(val, (int, float, str, bool)):
            out[key] = val
        else:
            out[key] = str(val)
    # Normalize the date back to a plain date string for convenience.
    if "date" in out:
        out["date"] = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
    return out


def _patch_activity(activity_id: int):
    uid = require_user_id()
    body = request.get_json(silent=True) or {}
    patch = ActivityPatch.model_validate(body).to_db_patch()
    if not patch:
        raise ValidationError("no editable fields provided")
    with session_scope() as session:
        # Guard against cross-user edits.
        act = session.get(Activity, activity_id)
        if act is None or act.deleted_at is not None or act.user_id != uid:
            raise NotFound(f"activity {activity_id} not found")
        row = patch_activity(session, activity_id=activity_id, patch=patch)
        if row is None:
            raise NotFound(f"activity {activity_id} not found")
    invalidate_cache()
    return jsonify({"id": activity_id, "updated": list(patch.keys())})


def _delete_activity(activity_id: int):
    uid = require_user_id()
    with session_scope() as session:
        act = session.get(Activity, activity_id)
        if act is None or act.deleted_at is not None or act.user_id != uid:
            raise NotFound(f"activity {activity_id} not found")
        ok = soft_delete_activity(session, activity_id=activity_id)
    if not ok:
        raise NotFound(f"activity {activity_id} not found")
    invalidate_cache()
    return jsonify({"id": activity_id, "deleted": True})
