"""Flask routes for Strava OAuth."""

import logging
from itsdangerous import BadSignature, URLSafeTimedSerializer

from flask import Blueprint, Flask, redirect, request, current_app

from ..auth import strava_oauth
from ..db import session_scope


logger = logging.getLogger(__name__)

bp = Blueprint("oauth", __name__, url_prefix="/oauth")


def _serializer(app: Flask) -> URLSafeTimedSerializer:
    secret = app.config.get("SECRET_KEY") or app.secret_key or "dev-secret-do-not-use"
    return URLSafeTimedSerializer(secret, salt="strava-oauth-state")


@bp.route("/strava/start")
def strava_start():
    if not strava_oauth.is_configured():
        return (
            "Strava OAuth not configured. Set STRAVA_CLIENT_ID and "
            "STRAVA_CLIENT_SECRET environment variables.",
            503,
        )
    state = strava_oauth.generate_state_token()
    signed = _serializer(current_app).dumps({"s": state})
    url = strava_oauth.build_authorize_url(state)
    resp = redirect(url)
    resp.set_cookie(
        "strava_oauth_state", signed,
        max_age=600, httponly=True, samesite="Lax",
    )
    return resp


@bp.route("/strava/callback")
def strava_callback():
    code = request.args.get("code")
    state = request.args.get("state", "")
    signed = request.cookies.get("strava_oauth_state", "")

    if not code:
        return f"Missing code. Error: {request.args.get('error')}", 400

    try:
        payload = _serializer(current_app).loads(signed, max_age=600)
        if payload.get("s") != state:
            return "State mismatch", 400
    except BadSignature:
        return "Invalid state signature", 400

    try:
        bundle = strava_oauth.exchange_code(code)
    except Exception as e:
        logger.exception("Token exchange failed")
        return f"Token exchange failed: {e}", 500

    with session_scope() as session:
        strava_oauth.save_tokens(session, user_id=1, bundle=bundle)

    resp = redirect("/settings#strava-connected")
    resp.delete_cookie("strava_oauth_state")
    return resp


@bp.route("/strava/disconnect", methods=["POST"])
def strava_disconnect():
    with session_scope() as session:
        strava_oauth.disconnect(session, user_id=1)
    return {"ok": True}


def register_oauth(server: Flask) -> None:
    """Register the OAuth blueprint on the Flask server."""
    # Ensure SECRET_KEY exists for signed-cookie state
    if not server.secret_key and not server.config.get("SECRET_KEY"):
        import os, secrets as _s
        server.secret_key = os.environ.get("MERON_SECRET_KEY") or _s.token_urlsafe(32)
    server.register_blueprint(bp)
