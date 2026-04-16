"""User-profile endpoint.

Returns the authenticated user's identity + Strava connection status so
the mobile client can render the profile screen and gate OAuth prompts.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from strava_analytics.db import session_scope
from strava_analytics.db.models import SyncState, User

from ..context import current_user_id
from ..errors import NotFound


bp = Blueprint("api_user", __name__, url_prefix="/api")


@bp.route("/user")
def user_profile():
    uid = current_user_id()
    with session_scope() as session:
        user = session.get(User, uid)
        if user is None:
            raise NotFound(f"user {uid} not found")
        sync_state = session.query(SyncState).filter(
            SyncState.user_id == uid,
            SyncState.provider == "strava",
        ).first()
        strava_connected = bool(
            sync_state and sync_state.access_token and sync_state.refresh_token
        )
        return jsonify({
            "id": user.id,
            "display_name": user.display_name,
            "timezone": user.timezone,
            "strava_athlete_id": user.strava_athlete_id,
            "strava_connected": strava_connected,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        })
