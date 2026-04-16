"""Hand-rolled schema migrations. No Alembic.

Each migration is a function `migration_NNN_*(engine)`. `run_migrations()`
reads the `schema_version` singleton and applies pending migrations in order.
"""

import logging
import os
import secrets
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import get_engine, get_session_factory, meron_dir
from .models import Base, InviteCode, SchemaVersion, User

logger = logging.getLogger(__name__)


def _current_version(session: Session) -> int:
    row = session.scalar(select(SchemaVersion).where(SchemaVersion.id == 1))
    return row.version if row else 0


def _set_version(session: Session, version: int) -> None:
    row = session.scalar(select(SchemaVersion).where(SchemaVersion.id == 1))
    if row is None:
        session.add(SchemaVersion(id=1, version=version))
    else:
        row.version = version


def migration_001_initial(engine) -> None:
    """Create all tables, seed single user, generate API keys."""
    Base.metadata.create_all(engine)

    # Seed user id=1 and sync_state rows for strava + apple_health
    factory = get_session_factory()
    with factory() as session:
        user = session.get(User, 1)
        if user is None:
            from ..config import default_tz_name
            session.add(User(
                id=1,
                display_name="You",
                timezone=default_tz_name(),
            ))
        # sync_state row w/ API keys
        from .models import SyncState
        if session.scalar(select(SyncState).where(
                SyncState.user_id == 1, SyncState.provider == "strava")) is None:
            session.add(SyncState(
                user_id=1,
                provider="strava",
                api_key_read=secrets.token_urlsafe(24),
                api_key_write=secrets.token_urlsafe(24),
            ))
        session.commit()


def migration_003_auth(engine) -> None:
    """Add username/password_hash/is_admin on users + create invite_codes."""
    # create_all is idempotent; it creates the new invite_codes table.
    Base.metadata.create_all(engine)

    # SQLite can't ALTER TABLE ADD COLUMN for columns defined in ORM that
    # already exist, and create_all won't add missing columns to an
    # existing table. Add them manually.
    with engine.begin() as conn:
        existing_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(users)"))
        }
        for col, ddl in [
            ("username", "VARCHAR(64)"),
            ("password_hash", "VARCHAR(256)"),
            ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
        # Unique index on username (nullable → multiple NULLs allowed in SQLite).
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_users_username ON users(username)"
        ))


def bootstrap_admin_from_env() -> None:
    """Seed or rotate the admin account from MERON_ADMIN_USERNAME/PASSWORD.

    Called after migrations on every boot so restarting the server with
    a new password env var rotates the credential. If the env vars are
    absent, the site stays in read-only demo mode until configured.
    """
    admin_user = os.environ.get("MERON_ADMIN_USERNAME", "").strip()
    admin_pw = os.environ.get("MERON_ADMIN_PASSWORD", "")
    if not admin_user or not admin_pw:
        logger.info(
            "MERON_ADMIN_USERNAME/PASSWORD not set — admin login disabled; "
            "site runs in read-only demo mode until you configure these."
        )
        return

    # Lazy import so this module doesn't drag in api.* at top-level.
    from ..api.passwords import hash_password
    factory = get_session_factory()
    with factory() as session:
        user = session.get(User, 1)
        if user is None:
            from ..config import default_tz_name
            user = User(id=1, display_name="Admin", timezone=default_tz_name())
            session.add(user)
        # Env is the source of truth for admin creds — always apply on boot.
        user.username = admin_user
        user.password_hash = hash_password(admin_pw)
        user.is_admin = 1
        session.commit()
        logger.info("Admin user %r seeded/refreshed from env", admin_user)


_MIGRATIONS = [
    (1, migration_001_initial),
    (3, migration_003_auth),
]


def run_migrations(engine=None) -> int:
    """Apply any pending migrations. Returns the new schema version."""
    engine = engine or get_engine()
    # Ensure MERON dir + fit subdir exist
    meron_dir().mkdir(parents=True, exist_ok=True)
    (meron_dir() / "fit").mkdir(parents=True, exist_ok=True)
    (meron_dir() / "uploads").mkdir(parents=True, exist_ok=True)

    # schema_version table must exist before we can query it. create_all is
    # idempotent and safe to call repeatedly — it only creates missing tables.
    Base.metadata.create_all(engine)

    factory = get_session_factory()
    with factory() as session:
        current = _current_version(session)
        for version, fn in _MIGRATIONS:
            if version <= current:
                continue
            logger.info("Applying migration %03d: %s", version, fn.__name__)
            fn(engine)
            # Re-open a fresh session to set version, since fn may have
            # committed its own transactions.
            with factory() as s2:
                _set_version(s2, version)
                s2.commit()
            current = version

    # Bootstrap / refresh admin credentials on every boot (not just when
    # migrations apply). Env-driven password rotations take effect on the
    # next server restart.
    bootstrap_admin_from_env()
    return current


def migration_002_backfill_bulk(export_dir: Path) -> dict:
    """One-shot: import an existing Strava export + athlete_config.json.

    Called explicitly via `strava migrate --from <export_dir>` or at first
    launch if `MERON_IMPORT_FROM` env var is set. Idempotent: re-running is
    a no-op (all inserts are UPSERTs).
    """
    import json
    from ..services.ingestion.strava_csv import ingest_bulk

    export_dir = Path(export_dir).expanduser()

    # Copy athlete_config.json into meron_dir() so UI can edit it
    src_cfg = export_dir / "athlete_config.json"
    dst_cfg = meron_dir() / "athlete_config.json"
    if src_cfg.exists() and not dst_cfg.exists():
        dst_cfg.write_text(src_cfg.read_text())

    # Copy route_index.json (built by route_matching) into meron_dir if present
    for fn in ["route_index.json", "hr_zones_cache.json", "best_efforts_cache.json"]:
        src = export_dir / fn
        dst = meron_dir() / fn
        if src.exists() and not dst.exists():
            dst.write_text(src.read_text())

    # Ingest activities + copy FIT files
    factory = get_session_factory()
    with factory() as session:
        report = ingest_bulk(export_dir, user_id=1, session=session)
        session.commit()
    return report
