"""Periodized training plan generator for concurrent strength + endurance.

Calibrated to athlete's actual training structure:
  - 5 runs/week (Mon, Wed, Fri short + Thu/Sat moderate/long)
  - 2-3 lifts/week (fits between run days)
  - Current weekly mileage ~17 mi/wk

CTL-target-driven progression:
  Instead of hardcoded +6%/week mileage increases, the plan derives weekly
  training load from a target CTL at race day, then back-calculates the
  mileage needed to reach it. Weekly mileage increase is capped at 10%
  (injury prevention guideline).

References:
  - Banister, E.W. (1975). Modeling elite athletic performance.
  - Wilson, J.M. et al. (2012). Concurrent Training: A Meta-Analysis.
    JSCR, 26(8), 2293-2307.
  - Robineau, J. et al. (2016). Specific Training Effects of Concurrent
    Aerobic and Strength Exercises. JSCR, 30(3), 672-683.
  - Mujika, I. & Padilla, S. (2003). Scientific Bases for Precompetition
    Tapering Strategies. MSSE, 35(7), 1182-1187.
  - Ronnested, B.R. et al. (2011). Optimizing strength training for
    running and cycling endurance performance. Scand J Med Sci Sports.
  - Issurin, V.B. (2010). New Horizons for the Methodology and Physiology
    of Training Periodization. Sports Medicine, 40(3), 189-206.
  - Rhea, M.R. et al. (2003). Meta-analysis of 1RM gains: 1-2%/week
    for trained individuals.
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class Workout:
    """A single workout session."""
    day: date
    session_type: str  # "lift", "run", "rest", "obstacle", "mobility"
    title: str
    details: list[str] = field(default_factory=list)
    intensity: str = ""  # "easy", "moderate", "hard", "race"
    duration_min: int = 0
    notes: str = ""


@dataclass
class TrainingWeek:
    """A full training week."""
    week_num: int
    phase: str
    phase_label: str
    start_date: date
    workouts: list[Workout] = field(default_factory=list)
    target_miles: float = 0.0
    lift_sessions: int = 0
    run_sessions: int = 0


SPARTAN_OBSTACLE_PREP = {
    "grip_endurance": {
        "exercises": ["Dead hang (target 90s+)", "Farmer carry 200ft @90lb",
                       "Towel pull-ups 3x5"],
        "frequency": "2x/week",
    },
    "upper_pull": {
        "exercises": ["Weighted pull-ups 5x5", "Rope climb practice",
                       "Traverse wall drills"],
        "frequency": "2x/week",
    },
    "carries": {
        "exercises": ["Sandbag carry 60-80lb x 200m",
                       "Bucket carry simulation", "Farmer carry 3x100ft"],
        "frequency": "1-2x/week",
    },
    "burpees": {
        "exercises": ["Burpee sets: 3x30 (penalty practice)",
                       "Target: 30 in under 3:00"],
        "frequency": "1x/week",
    },
    "lower_power": {
        "exercises": ["Box jumps 4x5", "Broad jumps 3x5",
                       "Wall jumps 3x3"],
        "frequency": "1x/week",
    },
    "spear_throw": {
        "exercises": ["Medicine ball overhead throw 3x5",
                       "Javelin technique drills"],
        "frequency": "1x/week (in Build 2)",
    },
}


def calculate_training_weights(current_1rm: float, phase: str,
                                week_in_phase: int = 1) -> dict:
    configs = {
        "build1": {"pct": 0.78 + 0.02 * (week_in_phase - 1), "sets": 4, "reps": 5},
        "build2": {"pct": 0.82, "sets": 3, "reps": 4},
        "taper": {"pct": 0.80, "sets": 2, "reps": 3},
        "race": {"pct": 0.60, "sets": 2, "reps": 5},
    }
    cfg = configs.get(phase, configs["build1"])
    pct = min(cfg["pct"], 0.90)
    working_weight = round(current_1rm * pct / 5) * 5
    return {"pct_1rm": pct, "working_weight": working_weight,
            "sets": cfg["sets"], "reps": cfg["reps"]}


# ---------------------------------------------------------------------------
# Weekly templates matching athlete's actual structure
# ---------------------------------------------------------------------------

def _build1_week(week_num: int, start: date, current_1rms: dict,
                  target_miles: float) -> TrainingWeek:
    """Build 1: maintain current structure, build mileage 5-10%."""
    tw = TrainingWeek(
        week_num=week_num, phase="build1",
        phase_label="Build 1 — Maintain Strength + Build Miles",
        start_date=start, target_miles=target_miles,
        lift_sessions=3, run_sessions=5,
    )

    bench = calculate_training_weights(current_1rms.get("bench", 225), "build1", week_num)
    squat = calculate_training_weights(current_1rms.get("squat", 305), "build1", week_num)
    deadlift = calculate_training_weights(current_1rms.get("deadlift", 405), "build1", week_num)
    ohp = calculate_training_weights(current_1rms.get("ohp", 110), "build1", week_num)

    short = round(target_miles * 0.12, 1)  # ~2-3 mi
    moderate = round(target_miles * 0.22, 1)  # ~4-5 mi
    long_run = round(target_miles * 0.35, 1)  # ~7-9 mi
    tempo = round(target_miles * 0.18, 1)  # ~3-4 mi

    tw.workouts = [
        Workout(start, "run", f"Easy Run — {short} mi",
                [f"{short} mi easy"], "easy", 25),
        Workout(start + timedelta(1), "lift", "Upper Body",
                [f"Bench Press {bench['sets']}x{bench['reps']} @{bench['working_weight']}lb",
                 f"OHP 3x5 @{ohp['working_weight']}lb",
                 "Weighted Pull-ups 5x5",
                 "DB Row 3x8",
                 "Dead Hang 2x max"],
                "hard", 55),
        Workout(start + timedelta(2), "run", f"Moderate Run — {moderate} mi",
                [f"{moderate} mi at moderate effort"], "moderate", 45),
        Workout(start + timedelta(3), "lift", "Lower Body + Carries",
                [f"Squat {squat['sets']}x{squat['reps']} @{squat['working_weight']}lb",
                 f"Deadlift 3x2 @{deadlift['working_weight']}lb",
                 "Hip Thrust 3x8 @185lb",
                 "Farmer Carry 3x100ft @90lb",
                 "Tib Raises 3x15"],
                "hard", 55),
        Workout(start + timedelta(3), "run", f"Easy Run — {short} mi",
                [f"{short} mi easy (PM, after lifting)"], "easy", 25,
                "Separate from lift by 6+ hours (Robineau 2016)"),
        Workout(start + timedelta(4), "run", f"Tempo Run — {tempo} mi",
                [f"1 mi warmup, {max(1, tempo - 2):.1f} mi at tempo, 1 mi cooldown"],
                "hard", 35),
        Workout(start + timedelta(5), "run", f"Long Run — {long_run} mi",
                [f"{long_run} mi at easy-to-moderate pace",
                 "Include rolling hills"], "moderate", 80),
        Workout(start + timedelta(6), "lift", "Upper Body (Light) + Grip",
                [f"Bench Press 3x5 @{round(bench['working_weight'] * 0.85 / 5) * 5}lb",
                 "Pull-ups 3x max",
                 "Farmer Carry 3x150ft @90lb",
                 "Ab Wheel 3x8"],
                "moderate", 40),
    ]
    return tw


def _build2_week(week_num: int, start: date, current_1rms: dict,
                  target_miles: float) -> TrainingWeek:
    """Build 2: peak volume + intensity (intervals, long, lifts)."""
    tw = TrainingWeek(
        week_num=week_num, phase="build2",
        phase_label="Build 2 — Peak Volume + Intensity",
        start_date=start, target_miles=target_miles,
        lift_sessions=2, run_sessions=5,
    )

    bench = calculate_training_weights(current_1rms.get("bench", 225), "build2")
    squat = calculate_training_weights(current_1rms.get("squat", 305), "build2")

    short = round(target_miles * 0.12, 1)
    moderate = round(target_miles * 0.20, 1)
    long_run = round(target_miles * 0.30, 1)
    intervals = round(target_miles * 0.18, 1)

    tw.workouts = [
        Workout(start, "run", f"Easy Run — {short} mi",
                [f"{short} mi easy"], "easy", 25),
        Workout(start + timedelta(1), "lift", "Full Body — Peak Strength",
                [f"Squat {squat['sets']}x{squat['reps']} @{squat['working_weight']}lb",
                 f"Bench Press {bench['sets']}x{bench['reps']} @{bench['working_weight']}lb",
                 "Weighted Pull-ups 4x5",
                 "Farmer Carry 3x200ft @90lb",
                 "Core: Plank 3x60s + Ab Wheel 3x8"],
                "hard", 65),
        Workout(start + timedelta(2), "run", f"Intervals — {intervals} mi",
                ["1 mi warmup",
                 "4x800m hard, 400m jog recovery",
                 "1 mi cooldown"], "hard", 40),
        Workout(start + timedelta(3), "run", f"Easy Run — {short} mi",
                [f"{short} mi recovery"], "easy", 25),
        Workout(start + timedelta(4), "run", f"Moderate Run — {moderate} mi",
                [f"{moderate} mi moderate with surges"], "moderate", 40),
        Workout(start + timedelta(5), "run", f"Long Run — {long_run} mi",
                [f"{long_run} mi easy-moderate, practice fueling"], "moderate", 75),
        Workout(start + timedelta(5), "lift", "Posterior Chain + Grip",
                ["Romanian Deadlift 3x6",
                 "Dead Hang 3x max (target 90s+)",
                 "DB Row 3x8",
                 "Sandbag carry 80lb x 200m x 3"],
                "moderate", 40),
        Workout(start + timedelta(6), "rest", "Full Rest",
                ["Complete rest"], "easy", 0),
    ]
    return tw


def _taper_week(week_num: int, start: date, current_1rms: dict,
                 target_miles: float, week_in_taper: int = 1) -> TrainingWeek:
    """Taper: reduce volume 60-90%, maintain intensity."""
    tw = TrainingWeek(
        week_num=week_num, phase="taper",
        phase_label="Taper — Volume Down, Sharpness Up",
        start_date=start, target_miles=target_miles,
        lift_sessions=1, run_sessions=4 if week_in_taper == 1 else 3,
    )

    bench = calculate_training_weights(current_1rms.get("bench", 225), "taper")
    squat = calculate_training_weights(current_1rms.get("squat", 305), "taper")

    short = round(target_miles * 0.20, 1)
    sharpener = round(target_miles * 0.25, 1)

    workouts = [
        Workout(start, "run", f"Easy Run — {short} mi",
                [f"{short} mi easy"], "easy", 25),
        Workout(start + timedelta(1), "lift", "Maintenance Lift (Low Volume)",
                [f"Squat {squat['sets']}x{squat['reps']} @{squat['working_weight']}lb",
                 f"Bench Press {bench['sets']}x{bench['reps']} @{bench['working_weight']}lb",
                 "Pull-ups 3x5", "Dead Hang 2x60s"],
                "moderate", 30),
        Workout(start + timedelta(2), "run", f"Race-Pace Sharpener — {sharpener} mi",
                [f"1 mi warmup, {max(1, sharpener - 1.5):.1f} mi at 10K pace, 0.5 mi cooldown"],
                "hard", 30),
        Workout(start + timedelta(3), "rest", "Rest", ["Complete rest"], "easy", 0),
        Workout(start + timedelta(4), "run", f"Easy Run — {short} mi",
                [f"{short} mi very easy"], "easy", 25),
        Workout(start + timedelta(5), "run", f"Shakeout — {round(target_miles * 0.15, 1)} mi",
                [f"{round(target_miles * 0.15, 1)} mi easy with 4x100m strides"],
                "easy", 20) if week_in_taper == 1 else
        Workout(start + timedelta(5), "rest", "Rest",
                ["Rest, hydrate, carb load begins"], "easy", 0),
        Workout(start + timedelta(6), "rest", "Rest",
                ["Full rest, sleep well"], "easy", 0),
    ]
    tw.workouts = workouts
    return tw


def _test_week(week_num: int, start: date) -> TrainingWeek:
    """Test week — perpetual peak. One quality time trial, then recovery.

    Replaces the old race-specific week. Without a race on the calendar
    the user still benefits from a hard effort that anchors the next
    cycle's pace targets: a 5K time trial gives a fresh VDOT/CS data
    point and the chart picks it up like any other run.
    """
    tw = TrainingWeek(
        week_num=week_num, phase="test",
        phase_label="Test Week — Time Trial + Recovery",
        start_date=start, target_miles=8,
        lift_sessions=0, run_sessions=3,
    )

    tw.workouts = [
        Workout(start, "run", "Shakeout — 2 mi",
                ["2 mi easy + 4x100m strides",
                 "Loosen up the day before the trial"], "easy", 20),
        Workout(start + timedelta(1), "rest", "Rest",
                ["Sleep, hydrate, light meals"], "easy", 0),
        Workout(start + timedelta(2), "run", "5K Time Trial",
                ["1 mi warmup",
                 "5K all-out (3.1 mi) — measure!",
                 "1 mi cooldown",
                 "Log the result; it sets next cycle's pace targets"],
                "hard", 45),
        Workout(start + timedelta(3), "rest", "Recovery",
                ["Light 20-min walk", "Foam roll",
                 "Protein + carbs focus"], "easy", 20),
        Workout(start + timedelta(4), "run", "Easy — 2 mi",
                ["2 mi VERY easy"], "easy", 20),
        Workout(start + timedelta(5), "mobility", "Mobility + Reset",
                ["20 min stretching + foam roll",
                 "Plan next 8-week block off the time-trial result"],
                "easy", 20),
        Workout(start + timedelta(6), "rest", "Rest",
                ["Full rest before the next block"], "easy", 0),
    ]
    return tw


# ---------------------------------------------------------------------------
# CTL-target-driven mileage progression
# ---------------------------------------------------------------------------

# Approximate relationship: 1 mile of easy running ≈ 10 TRIMP (normalized).
# Moderate ≈ 15, hard ≈ 20. Weighted average across a week's mix ≈ 12.
_TRIMP_PER_MILE = 12.0
_MAX_WEEKLY_INCREASE_PCT = 0.10  # 10% weekly cap (injury prevention)


def _compute_build_mileage(
    current_weekly_miles: float,
    current_ctl: float,
    target_ctl: float,
    n_build_weeks: int,
    tau_ctl: float = 42.0,
) -> list[float]:
    """Derive weekly mileage targets to reach a target CTL by end of build.

    Uses the Banister CTL formula:
        CTL(d+1) = CTL(d) + (daily_stress - CTL(d)) / tau
    to back-calculate the daily stress (and thus mileage) needed.

    Weekly mileage increase is capped at 10% per week.
    """
    if n_build_weeks <= 0:
        return []

    # Target: linear CTL ramp from current to target over build weeks
    ctl_targets = [
        current_ctl + (target_ctl - current_ctl) * (i + 1) / n_build_weeks
        for i in range(n_build_weeks)
    ]

    mileages = []
    ctl = current_ctl
    prev_miles = current_weekly_miles

    for week_idx in range(n_build_weeks):
        target = ctl_targets[week_idx]
        # Required daily stress to reach target CTL in 7 days
        # CTL after 7 days with constant daily stress s:
        # CTL_7 = CTL_0 + (s - CTL_0) * (1 - (1-1/tau)^7)
        # Solving for s: s = CTL_0 + (target - CTL_0) / (1 - (1-1/tau)^7)
        decay_factor = (1.0 - 1.0 / tau_ctl) ** 7
        required_daily_stress = ctl + (target - ctl) / (1.0 - decay_factor)
        required_daily_stress = max(required_daily_stress, 0)

        # Convert stress to mileage: weekly_stress = daily × 7
        # But only ~5 run days + 2 lift days. Lift stress is time-based, not mileage.
        # Approximate: 5 run days × miles_per_day × TRIMP_PER_MILE + 2 × 25 (lift)
        weekly_run_stress = required_daily_stress * 7 - 50  # subtract lift contribution
        weekly_run_stress = max(weekly_run_stress, 0)
        miles = weekly_run_stress / _TRIMP_PER_MILE

        # Cap at 10% increase per week
        max_miles = prev_miles * (1 + _MAX_WEEKLY_INCREASE_PCT)
        miles = min(miles, max_miles)
        miles = max(miles, prev_miles * 0.9)  # don't drop more than 10% either

        mileages.append(round(miles, 1))
        prev_miles = miles

        # Update CTL estimate for next week
        daily_stress = (miles * _TRIMP_PER_MILE + 50) / 7  # run + lift per day
        for _ in range(7):
            ctl = ctl + (daily_stress - ctl) / tau_ctl

    return mileages


def generate_training_plan(
    start_date: date,
    race1_date: date,
    race2_date: date,
    current_1rms: dict | None = None,
    current_weekly_miles: float = 20.0,
    target_peak_miles: float = 27.0,
    current_ctl: float | None = None,
    target_ctl: float | None = None,
) -> list[TrainingWeek]:
    """Generate an 8-week periodized plan with deload weeks.

    Progression: Build → Build → Deload → Build → Peak → Taper → Taper → Race

    Mileage builds from current level to target_peak_miles with a deload
    week every 3rd week (3:1 build-to-deload ratio). Lifting maintains
    or builds slightly during build weeks, reduces during deload and taper.

    Args:
        start_date: First day of the plan.
        race1_date: Legacy parameter — used to anchor a peak race week.
            Now unused inside this function (test week derives its date
            from start_date + 7 weeks). Kept in the signature so callers
            don't break. Will be removed in a future cleanup.
        race2_date: Legacy parameter — see race1_date. Originally the
            second race; now ignored.
        current_1rms: Current estimated 1RM for each lift.
        current_weekly_miles: Current weekly running volume.
        target_peak_miles: Peak weekly mileage target.
        current_ctl: Current CTL (optional, used for projections).
        target_ctl: Target CTL (optional).
    """
    if current_1rms is None:
        current_1rms = {"bench": 225, "squat": 305, "deadlift": 405, "ohp": 110}

    # 8-week structure with deload and taper
    # Phase: build, build, deload, build, peak, taper, taper, race
    base = current_weekly_miles
    peak = target_peak_miles

    week_plan = [
        # (phase,  miles,                    lift_pct, lift_sets, lift_reps, template)
        ("build1", round(base * 1.05, 1),    0.80,     3,         5,        "build1"),   # Wk 1
        ("build1", round(base * 1.15, 1),    0.82,     3,         5,        "build1"),   # Wk 2
        ("deload", round(base * 0.85, 1),    0.70,     2,         5,        "build1"),   # Wk 3: deload
        ("build2", round(peak * 0.93, 1),    0.82,     3,         4,        "build2"),   # Wk 4
        ("build2", round(peak, 1),           0.80,     2,         4,        "build2"),   # Wk 5: peak
        ("taper",  round(peak * 0.70, 1),    0.75,     2,         3,        "taper"),    # Wk 6
        ("taper",  round(peak * 0.45, 1),    0.70,     1,         3,        "taper"),    # Wk 7
        ("test",   8.0,                      0.60,     0,         0,        "test"),     # Wk 8
    ]

    weeks = []
    for i, (phase, miles, lift_pct, lift_sets, lift_reps, template) in enumerate(week_plan):
        week_start = start_date + timedelta(weeks=i)
        week_num = i + 1

        # Override lift calculations for this week
        override_1rms = {}
        for lift, max_val in current_1rms.items():
            wt = round(max_val * lift_pct / 5) * 5
            override_1rms[lift] = {"pct": lift_pct, "working_weight": wt,
                                   "sets": lift_sets, "reps": lift_reps}

        if template == "build1":
            tw = _build1_week(week_num, week_start, current_1rms, miles)
            tw.phase = phase
            if phase == "deload":
                tw.phase_label = "Deload — Recovery Week"
                tw.lift_sessions = 2
        elif template == "build2":
            tw = _build2_week(week_num, week_start, current_1rms, miles)
            tw.phase = phase
        elif template == "taper":
            tw = _taper_week(week_num, week_start, current_1rms, miles, i - 4)
            tw.phase = phase
        else:
            tw = _test_week(week_num, week_start)

        tw.target_miles = miles
        weeks.append(tw)

    return weeks


def plan_to_flat_list(weeks: list[TrainingWeek]) -> list[dict]:
    """Flatten the plan into a list of dicts for display."""
    rows = []
    for week in weeks:
        for workout in week.workouts:
            rows.append({
                "week": week.week_num,
                "phase": week.phase_label,
                "date": workout.day,
                "day_name": workout.day.strftime("%A"),
                "type": workout.session_type,
                "title": workout.title,
                "details": "\n".join(workout.details),
                "intensity": workout.intensity,
                "duration_min": workout.duration_min,
                "notes": workout.notes,
            })
    return rows
