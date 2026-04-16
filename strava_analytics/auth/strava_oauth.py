"""Strava OAuth helpers.

Tokens are Fernet-encrypted at rest. Encryption key lives at
`~/.meron/fernet.key` (auto-generated on first use, 0o600 perms).
Strava client credentials come from env vars only.
"""

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import meron_dir
from ..db.models import SyncState

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

DEFAULT_SCOPES = "read,activity:read_all,profile:read_all"


def _fernet() -> Fernet:
    key_path = meron_dir() / "fernet.key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes())


def _encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except Exception:
        return None


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: datetime
    athlete_id: Optional[int] = None
    scopes: Optional[str] = None


def is_configured() -> bool:
    return bool(os.environ.get("STRAVA_CLIENT_ID") and
                os.environ.get("STRAVA_CLIENT_SECRET"))


def redirect_uri() -> str:
    return os.environ.get(
        "STRAVA_REDIRECT_URI",
        "http://localhost:8050/oauth/strava/callback",
    )


def build_authorize_url(state: str, scope: str = DEFAULT_SCOPES) -> str:
    client_id = os.environ.get("STRAVA_CLIENT_ID", "")
    from urllib.parse import urlencode
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "approval_prompt": "auto",
        "scope": scope,
        "state": state,
    }
    return f"{STRAVA_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> TokenBundle:
    """Exchange an auth code for tokens."""
    try:
        from stravalib import Client
    except ImportError as e:
        raise RuntimeError("stravalib not installed") from e

    client = Client()
    resp = client.exchange_code_for_token(
        client_id=int(os.environ["STRAVA_CLIENT_ID"]),
        client_secret=os.environ["STRAVA_CLIENT_SECRET"],
        code=code,
    )
    # resp is a dict: {access_token, refresh_token, expires_at, athlete?}
    return _bundle_from_response(resp)


def _bundle_from_response(resp: dict) -> TokenBundle:
    expires_at_raw = resp.get("expires_at")
    if isinstance(expires_at_raw, (int, float)):
        expires_at = datetime.fromtimestamp(expires_at_raw, tz=timezone.utc)
    elif isinstance(expires_at_raw, datetime):
        expires_at = expires_at_raw
    else:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=5)

    athlete = resp.get("athlete") or {}
    athlete_id = None
    if isinstance(athlete, dict):
        athlete_id = athlete.get("id")
    else:
        athlete_id = getattr(athlete, "id", None)

    return TokenBundle(
        access_token=resp["access_token"],
        refresh_token=resp["refresh_token"],
        expires_at=expires_at,
        athlete_id=athlete_id,
        scopes=resp.get("scope") if isinstance(resp, dict) else None,
    )


def save_tokens(session: Session, user_id: int, bundle: TokenBundle) -> None:
    row = session.scalar(
        select(SyncState).where(
            SyncState.user_id == user_id,
            SyncState.provider == "strava",
        )
    )
    if row is None:
        row = SyncState(user_id=user_id, provider="strava")
        session.add(row)
    row.access_token = _encrypt(bundle.access_token)
    row.refresh_token = _encrypt(bundle.refresh_token)
    row.token_expires_at = bundle.expires_at
    if bundle.scopes:
        row.scopes = bundle.scopes

    # Also set athlete_id on users.strava_athlete_id if present
    if bundle.athlete_id:
        from ..db.models import User
        user = session.get(User, user_id)
        if user:
            user.strava_athlete_id = bundle.athlete_id


def load_tokens(session: Session, user_id: int) -> Optional[SyncState]:
    return session.scalar(
        select(SyncState).where(
            SyncState.user_id == user_id,
            SyncState.provider == "strava",
        )
    )


def refresh_if_needed(user_id: int, session: Session) -> str:
    """Return a valid access token, refreshing if expired/near-expired."""
    row = load_tokens(session, user_id)
    if row is None or not row.refresh_token:
        raise RuntimeError("Strava not connected")

    now = datetime.now(timezone.utc)
    expires = row.token_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    access = _decrypt(row.access_token)
    if access and expires and expires > now + timedelta(minutes=5):
        return access

    # Refresh
    try:
        from stravalib import Client
    except ImportError as e:
        raise RuntimeError("stravalib not installed") from e

    refresh = _decrypt(row.refresh_token)
    client = Client()
    resp = client.refresh_access_token(
        client_id=int(os.environ["STRAVA_CLIENT_ID"]),
        client_secret=os.environ["STRAVA_CLIENT_SECRET"],
        refresh_token=refresh,
    )
    bundle = _bundle_from_response(resp)
    save_tokens(session, user_id, bundle)
    return bundle.access_token


def disconnect(session: Session, user_id: int) -> None:
    row = load_tokens(session, user_id)
    if row:
        row.access_token = None
        row.refresh_token = None
        row.token_expires_at = None
        row.scopes = None


def generate_state_token() -> str:
    return secrets.token_urlsafe(24)
