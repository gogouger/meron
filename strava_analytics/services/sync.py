"""High-level sync orchestration across providers."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .enrichment_service import invalidate_cache
from .ingestion.strava_api import sync_incremental as strava_api_sync

logger = logging.getLogger(__name__)


def run_strava_sync(
    user_id: int,
    session: Session,
    since: Optional[datetime] = None,
) -> dict:
    """Run the Strava API sync and invalidate the enrichment cache."""
    report = strava_api_sync(user_id, session, since=since)
    invalidate_cache(user_id)
    return report
