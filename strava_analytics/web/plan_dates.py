"""Single source of truth for the rolling-window dates that anchor every
prediction chart on Meron.

Previously the training-plan page (and its mobile-side API mirror) pinned
to hard-coded race dates in 2026. Once the races happened the projection
horizon was in the past and the chart line just stopped where the plan
ended. This module replaces those constants with a window that always
runs forward 90 days from `date.today()`.

The fitness-freshness chart, race-time projections, and the training-plan
generator all read from `rolling_window()` so they advance together every
day — no cron, no user config, no stale anchors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


# Three months. Used as the projection horizon for the fitness chart and
# as the second notional race date so generate_training_plan still has a
# valid "race2" to taper toward.
HORIZON_DAYS = 90

# generate_training_plan is structured as an 8-week build → peak → taper
# cycle ending at race1_date. With no real race on the calendar we treat
# week 8 as a perpetual "peak" target that slides forward each day.
PLAN_WEEKS = 8


@dataclass(frozen=True)
class RollingWindow:
    start: date         # today — first day of the rolling plan
    plan_end: date      # today + 8 weeks — notional "peak" target
    horizon: date       # today + 90 days — far edge of the fitness projection

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "plan_end": self.plan_end.isoformat(),
            "horizon": self.horizon.isoformat(),
        }


def rolling_window(today: date | None = None) -> RollingWindow:
    """Return the dates that anchor every projection chart.

    `today` is optional — pass it to make tests deterministic; defaults to
    the calendar today so every render slides forward by one day.
    """
    t = today or date.today()
    return RollingWindow(
        start=t,
        plan_end=t + timedelta(weeks=PLAN_WEEKS),
        horizon=t + timedelta(days=HORIZON_DAYS),
    )
