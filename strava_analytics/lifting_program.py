"""Gordon's lifting program — 35 training days (33 lift, 2 run).

Days are sequential program days, not calendar days.
Map to calendar by backtracking from most recent Weight Training activity.
Program ran from ~Jan 9, 2026 to Apr 3, 2026.
"""

from __future__ import annotations

import re


# Default anchor used by the backfill CLI (`meron-cli backfill-lifts`) — the
# date the program started in real life. Used to label historical Weight
# Training activities with their program-day name.
#
# LEGACY: prediction charts must NOT read this constant. Strength projections
# live in `web/pages/lifting.py` and project N weeks forward from `date.today()`
# — they don't care which day of a 36-day cycle "today" is. Importing this
# constant from chart code re-pins the projection horizon to Jan 2026 and
# defeats the rolling-window work in `web/plan_dates.py`.
PROGRAM_ANCHOR_DATE = "2026-01-09"

# Baseline PRs at program start (Jan 2026)
BASELINE = {
    "weight_lbs": 175,
    "bench_1rm": 165,
    "squat_1rm": 255,
    "deadlift_1rm": 365,
    "ohp_1rm": 100,  # dumbbell
    "fastest_mile": "6:03",
    "fastest_5k": "23:14",
    "max_pullups": 12,
    "max_pushups": 27,
    "max_air_squats": 67,
    "max_hang_s": 95,
    "max_situps": 46,
    "max_wall_sit_s": 65,
    "vertical_jump_in": 24,
}

# End-of-program PRs
END_PRS = {
    "bench_1rm": 225,
    "squat_1rm": 305,
    "deadlift_1rm": 405,
    "max_pullups": 15,
}

# Each entry: (day_num, day_type, exercises)
# day_type: "lift" or "run"
# exercises: list of (exercise_name, sets, reps, weight_lbs) or description string for runs
# For bodyweight: weight=0. For variable rep counts, use the primary working set.
PROGRAM = [
    (1, "lift", [
        ("Bench Press", 5, 4, 135),
        ("Pull Up", 5, 5, 0),
        ("Pulley Row", 3, 8, 90),
        ("DB Incline Press", 3, 8, 40),
        ("Ab Wheel Rollout", 2, 4, 0),
        ("Tib Raise", None, None, 0),
        ("Tricep Pulldown", None, None, 0),
    ]),
    (2, "run", "5.6 miles easy"),
    (3, "lift", [
        ("Lunge", 4, 6, 95),
        ("Front Squat", 4, 5, 95),
        ("Stiff Leg DL", 3, 8, 225),
        ("Tib Raise", 3, 12, 0),
        ("Calf Raise", None, None, 0),
        ("90/90 Hip Raise", None, None, 0),
    ]),
    (4, "lift", [
        ("Pull Up", 5, 4, 0),
        ("Bench Press", 5, 4, 135),
        ("Overhead Press", 3, 8, 75),
        ("Farmer Carry", 3, 8, 90),
        ("Tib Raise", None, None, 0),
        ("Swim", None, None, 0),
        ("Abs", None, None, 0),
        ("Bicep Curl", None, None, 0),
    ]),
    (5, "run", "2 mile run"),
    (6, "lift", [
        ("Bench Press", 5, 4, 135),
        ("Pull Up", 5, 4, 0),
        ("Pulley Row", 3, 8, 90),
        ("DB Incline Press", 3, 8, 40),
        ("Squat Heel Raise", 2, 2, 225),
        ("Tib Raise", None, None, 0),
        ("Tricep Pulldown", None, None, 0),
    ]),
    (7, "lift", [
        ("Squat", 3, 3, 225),
        ("Deadlift", 3, 2, 315),
        ("Valley Girl", 2, 10, 0),
        ("BW RDL", 2, 10, 0),
        ("90/90", 2, 10, 0),
        ("Calf/Knee Drive", 2, 10, 0),
        ("Abs", None, None, 0),
    ]),
    (8, "lift", [
        ("Bench Press", 5, 4, 145),
        ("Pull Up", 5, 5, 0),
        ("Pulley Row", 3, 8, 100),
        ("DB Incline Press", 3, 7, 45),
        ("Squat Heel Raise", 2, 2, 225),
        ("Tib Raise", None, None, 0),
        ("Tricep Pulldown", None, None, 0),
        ("Valley Girl", 2, 10, 0),
        ("BW RDL", 2, 10, 0),
        ("90/90", 2, 10, 0),
        ("Calf/Knee Drive", 2, 10, 0),
    ]),
    (9, "lift", [
        ("Squat", 3, 3, 235),
        ("Deadlift", 3, 2, 325),
        ("Valley Girl", 2, 10, 0),
        ("BW RDL", 2, 10, 0),
        ("90/90", 2, 10, 0),
        ("Calf/Knee Drive", 2, 10, 0),
        ("Abs", None, None, 0),
    ]),
    (10, "lift", [
        ("Squat Heel Raise", 4, 5, 185),
        ("Bench Press", 4, 5, 145),
        ("Pull Up", 4, 5, 0),
        ("Valley Girl", 2, 10, 0),
        ("BW RDL", 2, 10, 0),
        ("90/90", 2, 10, 0),
        ("Calf/Knee Drive", 2, 10, 0),
    ]),
    (11, "lift", [
        ("Pull Up", 5, 4, 0),
        ("Bench Press", 5, 4, 155),
        ("Overhead Press", 3, 5, 105),
        ("Farmer Carry", 3, None, 90),
        ("Tib Raise", None, None, 0),
        ("Swim", None, None, 0),
        ("Abs", None, None, 0),
        ("Bicep Curl", None, None, 0),
    ]),
    (12, "lift", [
        ("Squat", 5, 5, 195),
    ]),
    (13, "lift", [
        ("Squat", 3, 3, 235),
        ("Deadlift", 3, 2, 325),
        ("Valley Girl", 2, 10, 0),
        ("BW RDL", 2, 10, 0),
        ("90/90", 2, 10, 0),
        ("Calf/Knee Drive", 2, 10, 0),
        ("Abs", None, None, 0),
    ]),
    (14, "lift", [
        ("Pull Up (Vest)", 5, 4, 0),
        ("Bench Press", 5, 4, 155),
        ("Tib Raise", None, None, 0),
    ]),
    (15, "lift", [
        ("Squat Heel Raise", 5, 5, 200),
        ("Bench Press", 4, 4, 155),
        ("Pull Up (Weighted)", 4, 4, 0),
    ]),
    (16, "lift", [
        ("Pull Up (Weighted)", 5, 4, 0),
        ("Bench Press", 5, 4, 165),
        ("Overhead Press", 3, 5, 105),
        ("Heavy Row", 3, 8, 0),
        ("Tib Raise", None, None, 0),
        ("Abs", None, None, 0),
    ]),
    (17, "lift", [
        ("Squat", 3, 3, 240),
        ("Deadlift", 3, 2, 340),
    ]),
    (18, "lift", [
        ("Pull Up (Weighted)", 5, 4, 0),
        ("Bench Press", 5, 4, 170),
        ("Sitback", None, None, 0),
    ]),
    # User's list has a duplicate "Day 17" here — this is actually Day 19 in sequence
    (19, "lift", [
        ("Squat", 3, 3, 245),
        ("Deadlift", 3, 2, 350),
    ]),
    (20, "lift", [
        ("Pull Up (Weighted)", 5, 4, 0),
        ("Bench Press", 5, 4, 170),
        ("Overhead Press", 3, 5, 110),
        ("Heavy Row", 3, 8, 0),
    ]),
    (21, "lift", [
        ("Squat", 5, 5, 205),
    ]),
    (22, "lift", [
        ("Pull Up (Weighted)", 5, 4, 0),
        ("Bench Press", 5, 4, 175),
        ("Stiff Leg DL", 1, None, 135),
    ]),
    (23, "lift", [
        ("Squat", 3, 3, 250),
        ("Deadlift", 3, 2, 360),
    ]),
    (24, "lift", [
        ("Bench Press", 5, 4, 175),
        ("Hip Thrust", 3, 8, 135),
        ("Bench Row (DB)", 3, 5, 50),
    ]),
    (25, "lift", [
        ("Squat", 5, 5, 210),
    ]),
    (26, "lift", [
        ("Pull Up (Weighted)", 5, 5, 0),
        ("Bench Press", 5, 4, 180),
        ("Hip Thrust", 2, 8, 135),
    ]),
    (27, "lift", [
        ("Squat", 3, 3, 255),
        ("Deadlift", 3, 2, 365),
    ]),
    (28, "lift", [
        ("Pull Up (Weighted)", 3, 8, 0),
        ("Bench Press", 3, 3, 200),
        ("Hip Thrust", 2, 8, 155),
    ]),
    (29, "lift", [
        ("Squat", 5, 5, 215),
        ("Overhead Press", 3, 5, 110),
        ("Bench Row (DB)", 3, 5, 50),
    ]),
    (30, "lift", [
        ("Pull Up (Weighted)", 5, 5, 0),
        ("Bench Press", 5, 5, 185),
        ("Hip Thrust", 3, 8, 155),
    ]),
    (31, "lift", [
        ("Squat", 3, 3, 260),
        ("Deadlift", 3, 2, 370),
    ]),
    (32, "lift", [
        ("Face Pull", 3, 8, 30),
        ("Bench Press", 3, 3, 205),
        ("Hip Thrust", 3, 5, 225),
    ]),
    (33, "lift", [
        ("Squat", 5, 5, 220),
        ("Overhead Press (DB)", 3, 5, 100),
        ("Bench Row (DB)", 3, 8, 50),
    ]),
    (34, "lift", [
        ("Bench Press", 1, 1, 225),  # 1RM
        ("Pull Up", 1, 15, 0),
    ]),
    (35, "lift", [
        ("Squat", 1, 1, 305),  # 1RM
        ("Deadlift", 1, 1, 405),  # 1RM
    ]),
    (36, "lift", [
        ("Bench Press", 3, 5, 190),
        ("Hip Thrust", 3, 5, 230),
        ("Bench Row (DB)", 3, 8, 50),
        ("Face Pull", 3, 5, 30),
    ]),
]


def get_lift_days():
    """Return only the lift-type days from the program."""
    return [(d, t, ex) for d, t, ex in PROGRAM if t == "lift"]


def get_primary_lifts(exercises: list) -> dict:
    """Extract the heaviest working weight for primary compound lifts."""
    result = {
        "bench_weight": None,
        "bench_volume": 0,
        "bench_sets": None,
        "bench_reps": None,
        "squat_weight": None,
        "squat_volume": 0,
        "squat_sets": None,
        "squat_reps": None,
        "deadlift_weight": None,
        "deadlift_volume": 0,
        "deadlift_sets": None,
        "deadlift_reps": None,
        "ohp_weight": None,
        "ohp_volume": 0,
        "ohp_sets": None,
        "ohp_reps": None,
        "pullup_sets": None,
        "pullup_reps": None,
        "hip_thrust_weight": None,
    }
    for name, sets, reps, weight in exercises:
        s = sets or 0
        r = reps or 0
        lower_name = name.lower()
        if "bench press" in lower_name or "bench" == lower_name:
            result["bench_weight"] = weight
            result["bench_volume"] = s * r * weight
            result["bench_sets"] = s
            result["bench_reps"] = r
        elif ("squat" in lower_name
              and "heel" not in lower_name
              and "front" not in lower_name
              and "air" not in lower_name):
            if weight > (result["squat_weight"] or 0):
                result["squat_weight"] = weight
                result["squat_volume"] = s * r * weight
                result["squat_sets"] = s
                result["squat_reps"] = r
        elif "deadlift" in lower_name and "stiff" not in lower_name and "glute" not in lower_name:
            if weight > (result["deadlift_weight"] or 0):
                result["deadlift_weight"] = weight
                result["deadlift_volume"] = s * r * weight
                result["deadlift_sets"] = s
                result["deadlift_reps"] = r
        elif "overhead" in lower_name or "ohp" in lower_name:
            result["ohp_weight"] = weight
            result["ohp_volume"] = s * r * weight
            result["ohp_sets"] = s
            result["ohp_reps"] = r
        elif "pull up" in lower_name or "pull-up" in lower_name:
            result["pullup_sets"] = s
            result["pullup_reps"] = r
        elif "hip thrust" in lower_name:
            result["hip_thrust_weight"] = weight
    return result


# ── Description (de)serialisation ───────────────────────────────────
#
# An activity's description is a compact, parseable string:
#   "Bench Press 5x4@135; Pull Up 5x5; Tib Raise"
# used both for the backfill (writing new descriptions) and for
# downstream enrichment (parsing description → per-activity weights).


def format_program_day_description(exercises) -> str:
    """Serialise a program day's ``exercises`` list to a description string."""
    parts: list[str] = []
    for name, sets, reps, weight in exercises:
        s = int(sets) if sets else 0
        r = int(reps) if reps else 0
        w = float(weight) if weight else 0.0
        if s and r and w:
            parts.append(f"{name} {s}x{r}@{int(w) if w == int(w) else w}")
        elif s and r:
            parts.append(f"{name} {s}x{r}")
        else:
            parts.append(name)
    return "; ".join(parts)


_EX_PATTERN = re.compile(r"^(.+?)\s+(\d+)x(\d+)(?:@(\d+(?:\.\d+)?))?$")


def parse_description(exercises_str) -> list[dict]:
    """Parse a description string back into ``[{name, sets, reps, weight}]``.

    Inverse of :func:`format_program_day_description`. Tolerant of
    whitespace and missing weight; unparseable fragments get a zeroed
    entry so the exercise still appears in UI lists.
    """
    if not exercises_str:
        return []
    # pandas NaN compatibility without importing pandas here.
    if isinstance(exercises_str, float) and exercises_str != exercises_str:
        return []
    parsed: list[dict] = []
    for ex_str in str(exercises_str).split(";"):
        ex_str = ex_str.strip()
        if not ex_str:
            continue
        m = _EX_PATTERN.match(ex_str)
        if m:
            parsed.append({
                "name": m.group(1).strip(),
                "sets": int(m.group(2)),
                "reps": int(m.group(3)),
                "weight": float(m.group(4)) if m.group(4) else 0.0,
            })
        else:
            parsed.append({"name": ex_str, "sets": 0, "reps": 0, "weight": 0.0})
    return parsed
