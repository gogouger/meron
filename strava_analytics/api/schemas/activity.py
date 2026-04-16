"""Pydantic schemas for activity CRUD payloads.

Unknown fields are silently ignored (``extra="ignore"``) so older mobile
clients don't 400 when a new field lands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _parse_iso_local(value: datetime | str | None) -> datetime | None:
    """Accept ISO strings or datetimes; normalise to tz-naive in the user's tz."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"invalid ISO datetime: {value!r}") from e
    if dt.tzinfo is not None:
        from strava_analytics.config import default_tz
        dt = dt.astimezone(default_tz()).replace(tzinfo=None)
    return dt


class ActivityCreate(BaseModel):
    """Payload for ``POST /api/activities``."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(..., min_length=1, max_length=64)
    start_time: datetime

    name: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    gear: Optional[str] = Field(None, max_length=200)

    elapsed_time_s: Optional[float] = Field(None, ge=0)
    moving_time_s: Optional[float] = Field(None, ge=0)
    distance_m: Optional[float] = Field(None, ge=0)
    elevation_gain_m: Optional[float] = None
    max_hr: Optional[float] = Field(None, ge=0, le=300)
    avg_hr: Optional[float] = Field(None, ge=0, le=300)
    avg_watts: Optional[float] = Field(None, ge=0)
    calories: Optional[float] = Field(None, ge=0)
    weather_condition: Optional[str] = Field(None, max_length=100)
    weather_temp_c: Optional[float] = None

    @field_validator("start_time", mode="before")
    @classmethod
    def _parse_start(cls, v):
        return _parse_iso_local(v)

    def to_db_payload(self) -> dict:
        """Return a dict with only the fields actually provided."""
        return self.model_dump(exclude_none=True)


class ActivityPatch(BaseModel):
    """Payload for ``PATCH /api/activities/<id>`` — every field optional."""

    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(None, max_length=500)
    type: Optional[str] = Field(None, min_length=1, max_length=64)
    description: Optional[str] = None
    gear: Optional[str] = Field(None, max_length=200)
    filename: Optional[str] = Field(None, max_length=500)
    start_time: Optional[datetime] = None

    elapsed_time_s: Optional[float] = Field(None, ge=0)
    moving_time_s: Optional[float] = Field(None, ge=0)
    distance_m: Optional[float] = Field(None, ge=0)
    max_speed_ms: Optional[float] = Field(None, ge=0)
    avg_speed_ms: Optional[float] = Field(None, ge=0)
    elevation_gain_m: Optional[float] = None
    elevation_loss_m: Optional[float] = None
    elevation_low_m: Optional[float] = None
    elevation_high_m: Optional[float] = None
    max_hr: Optional[float] = Field(None, ge=0, le=300)
    avg_hr: Optional[float] = Field(None, ge=0, le=300)
    avg_watts: Optional[float] = Field(None, ge=0)
    calories: Optional[float] = Field(None, ge=0)
    relative_effort: Optional[float] = None
    grade_adj_distance_m: Optional[float] = None
    total_steps: Optional[float] = None
    training_load: Optional[float] = None
    intensity: Optional[float] = None
    weather_condition: Optional[str] = Field(None, max_length=100)
    weather_temp_c: Optional[float] = None
    competition: Optional[str] = Field(None, max_length=100)
    strava_with_kid: Optional[int] = None

    @field_validator("start_time", mode="before")
    @classmethod
    def _parse_start(cls, v):
        return _parse_iso_local(v)

    def to_db_patch(self) -> dict:
        return self.model_dump(exclude_none=True)
