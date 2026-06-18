"""SQLAlchemy ORM models for MERON.

Canonical storage for activities + sync state. Enriched columns are NOT
persisted; they are recomputed in-process by `enrichment_service`.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def _default_user_tz() -> str:
    # Late import to avoid a circular dep: models.py is loaded very early.
    from ..config import default_tz_name
    return default_tz_name()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default=_default_user_tz)
    strava_athlete_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # ── Auth fields (added in migration 003) ──────────────────────────
    # Unique case-insensitive-via-application. Nullable so existing rows
    # (pre-auth) can sit without credentials; null-username means the
    # account can't log in (only the demo read path uses it).
    username: Mapped[str | None] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Integer, default=0)


class InviteCode(Base):
    """Single-use signup invitation. Admin-generated."""
    __tablename__ = "invite_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    consumed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Activity(Base):
    """Canonical activity row. Raw columns match loader.py:12-42.

    Soft-deleted via `deleted_at`. All reads filter `WHERE deleted_at IS NULL`.
    Manual edits are layered via `manual_overrides` JSON (Strava re-sync never
    touches fields present there). `source='manual'` rows mutate raw columns
    directly (no override layer).
    """
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_id",
                         name="uq_activity_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # Provenance identity
    source: Mapped[str] = mapped_column(String(32), index=True)  # strava|manual|apple_health
    source_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # Raw fields mirroring loader._COLUMN_MAP
    start_time: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    name: Mapped[str | None] = mapped_column(String(500))
    type: Mapped[str | None] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    gear: Mapped[str | None] = mapped_column(String(200))
    filename: Mapped[str | None] = mapped_column(String(500))
    elapsed_time_s: Mapped[float | None] = mapped_column(Float)
    moving_time_s: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    max_speed_ms: Mapped[float | None] = mapped_column(Float)
    avg_speed_ms: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float)
    elevation_low_m: Mapped[float | None] = mapped_column(Float)
    elevation_high_m: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    avg_watts: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    relative_effort: Mapped[float | None] = mapped_column(Float)  # Strava's field
    grade_adj_distance_m: Mapped[float | None] = mapped_column(Float)
    weather_condition: Mapped[str | None] = mapped_column(String(100))
    weather_temp_c: Mapped[float | None] = mapped_column(Float)
    total_steps: Mapped[float | None] = mapped_column(Float)
    training_load: Mapped[float | None] = mapped_column(Float)
    intensity: Mapped[float | None] = mapped_column(Float)
    competition: Mapped[str | None] = mapped_column(String(100))
    strava_with_kid: Mapped[int | None] = mapped_column(Integer)

    # Provenance + overrides + soft delete
    provenance: Mapped[dict | None] = mapped_column(JSON)
    manual_overrides: Mapped[dict | None] = mapped_column(JSON)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Per-second activity streams pulled from the Strava API (heartrate,
    # distance, latlng, etc.). gzip+base64 of a Strava streams dict, see
    # streams.py. Only populated for source='strava' rows synced via the API
    # — CSV-import rows still get their telemetry from the .fit.gz files on
    # disk under DATA_DIR/fit/. Both code paths converge through routes.py
    # helpers that prefer the blob and fall back to file parsing.
    streams_blob: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    hr_zones: Mapped["ActivityHrZones | None"] = relationship(
        back_populates="activity", uselist=False, cascade="all, delete-orphan"
    )


class ActivityHrZones(Base):
    """Per-second zone times parsed from FIT streams.

    Replaces the on-disk `hr_zones_cache.json`. Cache key (max_hr + zone_pct)
    lets us invalidate when the user changes their HR zone settings.
    """
    __tablename__ = "activity_hr_zones"
    activity_id: Mapped[int] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    zone_1_s: Mapped[float] = mapped_column(Float, default=0.0)
    zone_2_s: Mapped[float] = mapped_column(Float, default=0.0)
    zone_3_s: Mapped[float] = mapped_column(Float, default=0.0)
    zone_4_s: Mapped[float] = mapped_column(Float, default=0.0)
    zone_5_s: Mapped[float] = mapped_column(Float, default=0.0)
    cache_key: Mapped[str] = mapped_column(String(64))

    activity: Mapped[Activity] = relationship(back_populates="hr_zones")


class SyncState(Base):
    """OAuth tokens + last-sync cursor per user per provider."""
    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_sync_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # strava, apple_health
    access_token: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    refresh_token: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_activity_id_synced: Mapped[str | None] = mapped_column(String(64))
    scopes: Mapped[str | None] = mapped_column(String(500))
    last_rate_limit_hit: Mapped[datetime | None] = mapped_column(DateTime)
    api_key_read: Mapped[str | None] = mapped_column(String(128))
    api_key_write: Mapped[str | None] = mapped_column(String(128))


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# Raw activity column names that back a DataFrame row. Used by the repository
# to reconstruct the loader.py output shape.
RAW_ACTIVITY_COLUMNS = [
    "start_time",  # → renamed to "date" in DataFrame
    "name", "type", "description", "gear", "filename",
    "elapsed_time_s", "moving_time_s", "distance_m",
    "max_speed_ms", "avg_speed_ms",
    "elevation_gain_m", "elevation_loss_m",
    "elevation_low_m", "elevation_high_m",
    "max_hr", "avg_hr", "avg_watts", "calories",
    "relative_effort", "grade_adj_distance_m",
    "weather_condition", "weather_temp_c",
    "total_steps", "training_load", "intensity",
    "competition", "strava_with_kid",
    "streams_blob",  # gzip+base64 streams from the Strava API path
]
