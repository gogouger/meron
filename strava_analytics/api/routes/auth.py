"""Auth endpoints: login / logout / signup / me / pair-claim / invites.

Login & signup are invite-only for regular users. The admin is seeded
from ``MERON_ADMIN_USERNAME/PASSWORD`` during migration 003. Anyone
with a valid invite code + desired username/password can sign up.

Pair-claim lives here too since it's the other "bootstrap" endpoint.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from strava_analytics.db import session_scope
from strava_analytics.db.models import InviteCode, SyncState, User

from .. import pairing
from ..context import DEMO_USER_ID, current_is_admin, require_user_id  # noqa: F401
from ..errors import NotFound, Unauthorized, ValidationError, envelope
from ..passwords import hash_password, verify_password
from ..sessions import login_session, logout_session, session_user_id


logger = logging.getLogger(__name__)

bp = Blueprint("api_auth", __name__, url_prefix="/api/auth")


# ─── Login / logout / me ──────────────────────────────────────────────

@bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip().lower()
    password = body.get("password") or ""
    if not username or not password:
        raise ValidationError("username and password are required")

    with session_scope() as session:
        user = session.query(User).filter(User.username == username).first()
        if user is None or not verify_password(password, user.password_hash):
            raise Unauthorized("invalid username or password")
        uid = user.id
        username_out = user.username
        is_admin = bool(user.is_admin)

    login_session(uid)
    return jsonify({
        "user": {"id": uid, "username": username_out, "is_admin": is_admin}
    })


@bp.route("/logout", methods=["POST"])
def logout():
    logout_session()
    return jsonify({"ok": True})


@bp.route("/me")
def me():
    uid = session_user_id()
    if uid is None:
        return jsonify(envelope("unauthorized", "not logged in")), 401
    with session_scope() as session:
        user = session.get(User, uid)
        if user is None:
            logout_session()
            return jsonify(envelope("unauthorized", "user no longer exists")), 401
        return jsonify({
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "is_admin": bool(user.is_admin),
        })


# ─── Signup ───────────────────────────────────────────────────────────

@bp.route("/signup", methods=["POST"])
def signup():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip().lower()
    password = body.get("password") or ""
    invite = (body.get("invite_code") or "").strip().upper().replace("-", "")

    if not username or not password or not invite:
        raise ValidationError(
            "username, password, and invite_code are required"
        )
    if len(password) < 8:
        raise ValidationError("password must be at least 8 characters")
    if len(username) < 3 or len(username) > 64:
        raise ValidationError("username must be 3–64 characters")
    if not username.replace("_", "").replace("-", "").isalnum():
        raise ValidationError(
            "username must contain only letters, numbers, _ or -"
        )

    with session_scope() as session:
        code_row = session.query(InviteCode).filter(
            InviteCode.code == invite,
            InviteCode.consumed_by_user_id.is_(None),
        ).first()
        if code_row is None:
            raise NotFound("invite code not found or already used")
        if code_row.expires_at and code_row.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
            raise NotFound("invite code has expired")

        if session.query(User).filter(User.username == username).first():
            raise ValidationError("username is taken")

        user = User(
            username=username,
            display_name=username,
            password_hash=hash_password(password),
            is_admin=0,
        )
        session.add(user)
        session.flush()  # assign user.id

        # Give the new user their own API keys so mobile pairing works.
        session.add(SyncState(
            user_id=user.id,
            provider="strava",
            api_key_read=secrets.token_urlsafe(24),
            api_key_write=secrets.token_urlsafe(24),
        ))

        code_row.consumed_by_user_id = user.id
        code_row.consumed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()

        uid = user.id
        username_out = user.username

    login_session(uid)
    return jsonify({
        "user": {"id": uid, "username": username_out, "is_admin": False}
    }), 201


# ─── Pair-claim (public; mobile app bootstrap) ────────────────────────

@bp.route("/pair/claim", methods=["POST"])
def claim_pair():
    body = request.get_json(silent=True) or {}
    raw = (body.get("code") or "").strip().upper()
    code = raw.replace("-", "").replace(" ", "")
    if not code:
        raise ValidationError("code is required")

    record = pairing.claim(code)
    if record is None:
        raise NotFound("pair code not found or expired")

    return jsonify({
        "api_key": record.api_key,
        "api_base": record.api_base,
    })


# ─── Admin: invites ───────────────────────────────────────────────────

@bp.route("/invites", methods=["GET", "POST"])
def invites():
    uid = require_user_id()
    if not current_is_admin():
        raise Unauthorized("admin only")

    if request.method == "POST":
        code = _new_invite_code()
        with session_scope() as session:
            session.add(InviteCode(code=code, created_by_user_id=uid))
            session.commit()
        return jsonify({"code": code}), 201

    # GET — list outstanding (unconsumed) invites.
    with session_scope() as session:
        rows = session.query(InviteCode).filter(
            InviteCode.consumed_by_user_id.is_(None)
        ).all()
        return jsonify({
            "invites": [
                {
                    "code": r.code,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                }
                for r in rows
            ]
        })


@bp.route("/invites/<code>", methods=["DELETE"])
def revoke_invite(code: str):
    require_user_id()
    if not current_is_admin():
        raise Unauthorized("admin only")
    code = code.strip().upper().replace("-", "")
    with session_scope() as session:
        row = session.query(InviteCode).filter(InviteCode.code == code).first()
        if row is None or row.consumed_by_user_id is not None:
            raise NotFound("invite not found or already consumed")
        session.delete(row)
        session.commit()
    return jsonify({"ok": True})


def _new_invite_code() -> str:
    """8-char code from the same safe alphabet as pair codes."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))
