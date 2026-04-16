"""Backfill lift descriptions from the static program.

Walks :data:`strava_analytics.lifting_program.PROGRAM` forward from an
anchor date, mapping each program lift day in order to the next
Weight Training activity on disk that has no description. The
resulting exercise list is written to the activity's description
field (via ``manual_overrides`` so it survives Strava re-sync).

Downstream, ``enrichment.map_lifting_program`` parses these
descriptions to populate per-activity bench/squat/deadlift/ohp
weights, which drive the strength-progression plots.

The backfill is **idempotent**: activities that already have a
description (real user text or a prior backfill write) are skipped,
never overwritten.

Future direction noted by the user: a follow-up will support adding
descriptions manually from the UI or syncing structured lift data
from Strava. This module is the first step — it gives today's DB a
self-describing baseline without touching anything that's real.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Activity
from ..lifting_program import PROGRAM, PROGRAM_ANCHOR_DATE, format_program_day_description


logger = logging.getLogger(__name__)


def _anchor_datetime(anchor: date | str | None) -> datetime:
    if anchor is None:
        anchor = PROGRAM_ANCHOR_DATE
    if isinstance(anchor, str):
        anchor = date.fromisoformat(anchor)
    return datetime.combine(anchor, datetime.min.time())


def backfill_lift_descriptions(
    session: Session,
    *,
    user_id: int,
    anchor_date: date | str | None = None,
) -> dict:
    """Map program lift days onto bare Weight Training activities in order.

    Returns a dict with counts useful for the CLI and auto-boot paths:

    - ``matched``: number of activities that received a backfilled description
    - ``skipped_has_desc``: activities already described (not touched)
    - ``program_exhausted``: True if we ran out of program days before
      running out of activities
    - ``activities_considered``: total Weight Training activities in range
    """
    anchor = _anchor_datetime(anchor_date)
    program_lift_days = [d for d in PROGRAM if d[1] == "lift"]

    rows = session.scalars(
        select(Activity)
        .where(
            Activity.user_id == user_id,
            Activity.type == "Weight Training",
            Activity.deleted_at.is_(None),
            Activity.start_time >= anchor,
        )
        .order_by(Activity.start_time)
    ).all()

    matched = 0
    skipped_has_desc = 0
    program_idx = 0

    for act in rows:
        existing = (act.description or "").strip()
        overrides = act.manual_overrides or {}
        override_desc = (overrides.get("description") or "").strip()
        if existing or override_desc:
            # Never overwrite real user data. Consume a program slot
            # anyway — user presumably wrote it describing the same day
            # that the program expected.
            skipped_has_desc += 1
            program_idx += 1
            continue

        if program_idx >= len(program_lift_days):
            # Program ran out before activities did; remaining bare
            # lifts stay bare until the future UI / Strava-sync path
            # writes real descriptions.
            break

        day_num, _kind, exercises = program_lift_days[program_idx]
        desc = format_program_day_description(exercises)

        # Write via manual_overrides — JSON-column mutation requires a
        # fresh dict so SQLAlchemy picks up the change on flush.
        new_overrides = dict(overrides)
        new_overrides["description"] = desc
        new_overrides["_program_day"] = day_num  # cheap breadcrumb
        act.manual_overrides = new_overrides
        act.updated_at = datetime.now(timezone.utc)
        matched += 1
        program_idx += 1

    session.commit()

    report = {
        "matched": matched,
        "skipped_has_desc": skipped_has_desc,
        "program_exhausted": program_idx >= len(program_lift_days),
        "activities_considered": len(rows),
        "anchor_date": anchor.date().isoformat(),
    }
    logger.info("backfill_lift_descriptions: %s", report)
    return report
