"""Training plan page — data-driven layout with fitness charts."""

from datetime import date, timedelta

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, Output, Input
import pandas as pd

from strava_analytics.web import data
from strava_analytics.web.components import charts
from strava_analytics.web.components.charts import (
    fitness_freshness_chart,
    mileage_progression_chart,
    strength_progression_chart,
    compliance_bar,
    enhanced_plan_calendar,
)
from strava_analytics.web.components.layout import (
    hero_section, page_section, statement_section, feature_grid,
    numbered_card, cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, ACCENT_RED,
    PHASE_COLORS, WORKOUT_TYPE_COLORS,
    TEXT_SECONDARY, TEXT_MUTED, BG_CARD, BORDER, FONT_MONO,
    TEXT_PRIMARY,
)
from strava_analytics.training_plan import (
    generate_training_plan, plan_to_flat_list,
    SPARTAN_OBSTACLE_PREP,
)
from strava_analytics.predictions import estimate_1rm
from strava_analytics.web.plan_data import (
    get_fitness_timeseries, get_current_fitness,
    get_mileage_progression, get_1rm_trends,
    get_projected_fitness, get_race_readiness, get_compliance,
    get_plan_projections,
)

dash.register_page(__name__, path="/plan", name="Training Plan")

# Plan constants
_START_DATE = date(2026, 4, 6)
_RACE1_DATE = date(2026, 5, 25)
_RACE2_DATE = date(2026, 5, 31)


def _get_current_1rms(df: pd.DataFrame) -> dict:
    lifts = df[df["type"] == "Weight Training"].copy()
    defaults = {"bench": 225, "squat": 305, "deadlift": 405, "ohp": 110}
    if lifts.empty:
        return defaults

    result = {}
    for lift in ["bench", "squat", "deadlift", "ohp"]:
        weight_col = f"{lift}_weight"
        volume_col = f"{lift}_volume"
        if weight_col not in lifts.columns:
            result[lift] = defaults[lift]
            continue

        recent = lifts[lifts[weight_col].notna() & (lifts[weight_col] > 0)].sort_values("date")
        if recent.empty:
            result[lift] = defaults[lift]
            continue

        actual_1rm = None
        for _, row in recent.iloc[::-1].iterrows():
            w = row[weight_col]
            vol = row.get(volume_col, 0) or 0
            if vol > 0 and abs(vol - w) < 1:
                actual_1rm = w
                break

        if actual_1rm:
            result[lift] = int(actual_1rm)
        else:
            last = recent.iloc[-1]
            w = last[weight_col]
            vol = last.get(volume_col, 0) or 0
            reps = max(1, int(vol / w / 3)) if w > 0 and vol > 0 else 3
            result[lift] = round(estimate_1rm(w, reps, rir=2, method="ensemble"))

    return result


def _get_current_weekly_miles(df: pd.DataFrame) -> float:
    runs = df[df["type"] == "Run"]
    if runs.empty:
        return 15.0
    now = runs["date"].max()
    last_4w = runs[runs["date"] >= now - pd.Timedelta(weeks=4)]
    return last_4w["distance_mi"].sum() / 4


def _generate_ics(plan_rows: list[dict]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Strava Analytics//Training Plan//EN",
        "CALSCALE:GREGORIAN",
    ]
    for row in plan_rows:
        dt = row["date"]
        title = row["title"]
        intensity = row.get("intensity", "")
        workout_type = row.get("type", "")
        date_str = dt.strftime("%Y%m%d")
        lines.extend([
            "BEGIN:VEVENT",
            f"DTSTART;VALUE=DATE:{date_str}",
            f"DTEND;VALUE=DATE:{date_str}",
            f"SUMMARY:{title}",
            f"DESCRIPTION:{workout_type} - {intensity}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def _readiness_badge(readiness: dict) -> html.Div:
    """Compact race readiness badge."""
    label = readiness["readiness_label"]
    tsb = readiness["tsb"]
    color_map = {
        "Peak Form": ACCENT_SLATE,
        "Good Form": ACCENT_AMBER,
        "Neutral": TEXT_MUTED,
        "Fatigued": ACCENT_RED,
    }
    color = color_map.get(label, TEXT_MUTED)
    rd = readiness["race_date"]

    return html.Div([
        html.Div(rd.strftime("%b %d"), style={
            "fontSize": "12px", "color": TEXT_MUTED, "marginBottom": "4px",
        }),
        html.Div(label, style={
            "fontSize": "14px", "fontWeight": "600", "color": color,
        }),
        html.Div(f"CTL {readiness['ctl']} / ATL {readiness['atl']} / TSB {tsb:+.0f}", style={
            "fontSize": "11px", "color": TEXT_SECONDARY, "marginTop": "4px",
        }),
    ], style={
        "padding": "12px 16px",
        "border": f"1px solid {BORDER}",
        "borderLeft": f"3px solid {color}",
        "backgroundColor": BG_CARD,
        "flex": "1",
        "minWidth": "180px",
    })


def layout(**_kwargs):
    df = data.get_df()

    current_1rms = _get_current_1rms(df)
    current_miles = _get_current_weekly_miles(df)
    target_peak = 27.0

    fitness = get_current_fitness(df)

    plan = generate_training_plan(
        start_date=_START_DATE,
        race1_date=_RACE1_DATE,
        race2_date=_RACE2_DATE,
        current_1rms=current_1rms,
        current_weekly_miles=current_miles,
        target_peak_miles=target_peak,
    )

    flat = plan_to_flat_list(plan)
    ics_content = _generate_ics(flat)

    # Data computations
    projected = get_projected_fitness(df, plan)
    mileage = get_mileage_progression(df, plan)
    strength_trends = get_1rm_trends(df)
    race_readiness = get_race_readiness(df, plan, [_RACE1_DATE, _RACE2_DATE])
    compliance_data = get_compliance(df, flat)
    best_efforts_df = data.get_best_efforts()
    plan_projections = get_plan_projections(df, plan, current_1rms, best_efforts_df)

    # Current race prediction
    from strava_analytics.critical_speed import predict_race_times
    import pandas as pd
    runs = df[df["type"] == "Run"]
    recent = runs[runs["date"] >= runs["date"].max() - pd.Timedelta(weeks=8)]
    wkm = recent["distance_mi"].sum() / 8 * 1.60934 if not recent.empty else 0
    apace = recent["pace_min_per_mi"].mean() * 60 / 1.60934 if not recent.empty else 0
    cs_preds = predict_race_times(best_efforts_df, weekly_km=wkm, avg_pace_sec_per_km=apace)
    cs_10k_s = cs_preds.get("10K", {}).get("time_s", 0)
    cs_5k_s = cs_preds.get("5K", {}).get("time_s", 0)

    # Projected race times
    race_proj = plan_projections.get("race_projections", {})
    proj_10k = race_proj.get("10K", {})
    proj_5k = race_proj.get("5K", {})
    str_proj = plan_projections.get("strength_projections", {})

    # Race readiness at race day
    rd1 = race_readiness[0] if race_readiness else {}
    rd2 = race_readiness[1] if len(race_readiness) > 1 else {}

    today = date.today()

    return html.Div([
        # Hero
        hero_section(
            label="TRAINING PLAN",
            headline="Your plan. Your projection.",
            subtext=(
                f"Boulder Bolder 10K (May 25) + Spartan Beast (May 31). "
                f"{current_miles:.0f} mi/wk \u2192 {target_peak:.0f} mi/wk peak. "
                f"Deload week 3. Taper weeks 6-7."
            ),
        ),

        dcc.Download(id="ics-download"),
        dcc.Store(id="ics-store", data=ics_content),

        # ── NOW vs RACE DAY (compact table) ──
        page_section("NOW \u2192 RACE DAY", [
            _now_vs_raceday_table(
                current_miles, target_peak, cs_5k_s, cs_10k_s,
                proj_5k, proj_10k, current_1rms, str_proj,
                fitness, rd1,
            ),
        ]),

        # ── MILEAGE BUILD ──
        page_section("MILEAGE BUILD", [
            mileage_progression_chart(mileage),
        ], alt_bg=True),

        # ── RACE PROJECTION ──
        page_section("RACE PROJECTION", [
            html.P("Estimated race times based on current fitness + plan improvements.",
                   style={"color": TEXT_SECONDARY, "fontSize": "13px", "marginBottom": "12px"}),
            _race_projection_chart(runs, best_efforts_df, race_proj, plan),
        ]),

        # ── STRENGTH PROJECTION ──
        page_section("STRENGTH PROJECTION", [
            html.Div([
                html.Div([
                    strength_progression_chart(
                        lift, prog_df,
                        projected=_build_1rm_projection(lift, str_proj, plan),
                    ),
                ], style={"flex": "1", "minWidth": "300px"})
                for lift, prog_df in strength_trends.items()
            ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap"})
            if strength_trends else
            html.P("No lifting data.", style={"color": TEXT_MUTED}),
        ]),

        # ── RACE READINESS ──
        page_section("RACE READINESS", [
            html.Div(
                [_readiness_badge(r) for r in race_readiness] if race_readiness else [
                    html.P("Insufficient data.", style={"color": TEXT_MUTED})
                ],
                style={"display": "flex", "gap": "16px", "flexWrap": "wrap"},
            ),
        ], alt_bg=True),

        # ── COMPLIANCE ──
        *(
            [page_section("COMPLIANCE", [
                compliance_bar(compliance_data["pct"]),
            ])]
            if compliance_data["total_planned"] > 0 else []
        ),

        # ── CALENDAR ──
        page_section("THE PLAN", [
            enhanced_plan_calendar(flat, compliance_data),
            _legend(),
        ], alt_bg=True),

        # ── WEEK BY WEEK ──
        page_section("WEEK BY WEEK", [
            *[_phase_section(week, today) for week in plan],
        ]),

        # ── FITNESS & FRESHNESS (last — supplementary detail) ──
        page_section("FITNESS & FRESHNESS", [
            fitness_freshness_chart(projected, race_dates=[_RACE1_DATE, _RACE2_DATE]),
        ], alt_bg=True),

        # Science
        page_section("THE SCIENCE", [
            _science_section(),
        ]),

        # Export + CTA
        html.Div(
            html.Button("Export to Calendar (.ics)", id="export-ics-btn",
                        className="btn-ghost",
                        style={"margin": "0 auto", "display": "block"}),
            style={"textAlign": "center", "marginBottom": "24px"},
        ),

        cta_section("Now stop reading and go train."),
        footer(),
    ])


def _race_projection_chart(runs, best_efforts_df, race_proj, plan_weeks) -> html.Div:
    """Build a 10K race prediction chart with projected dashed line."""
    from strava_analytics.web.components.charts import _single_race_chart
    import pandas as pd

    proj_10k = race_proj.get("10K", {})
    if not proj_10k:
        return html.P("Insufficient data for race projection.", style={"color": TEXT_MUTED})

    # Build projected points: linear from current to projected over plan weeks
    current_min = proj_10k.get("current_min", 0)
    projected_min = proj_10k.get("projected_min", 0)
    if not current_min or not projected_min or not plan_weeks:
        return html.P("Insufficient data.", style={"color": TEXT_MUTED})

    n = len(plan_weeks)
    proj_points = []
    for i, week in enumerate(plan_weeks):
        t = (i + 1) / n
        val = current_min + (projected_min - current_min) * t
        proj_points.append({"date": pd.Timestamp(week.start_date), "time_min": round(val, 2)})

    return _single_race_chart(
        runs, 10000, "10K Projection", "plan-race-10k",
        best_efforts=best_efforts_df,
        projected=proj_points,
    )


def _build_1rm_projection(lift: str, str_proj: dict, plan_weeks: list) -> list:
    """Build projected 1RM data points for the plan period (weekly)."""
    import pandas as pd
    proj = str_proj.get(lift, {})
    current = proj.get("current", 0)
    projected = proj.get("projected", 0)
    if not current or not projected or not plan_weeks:
        return []

    n_weeks = len(plan_weeks)
    points = []
    for i, week in enumerate(plan_weeks):
        # Linear interpolation from current to projected over build weeks
        t = (i + 1) / n_weeks
        val = current + (projected - current) * t
        week_date = pd.Timestamp(week.start_date)
        points.append({"date": week_date, "value": round(val, 1)})
    return points


def _now_vs_raceday_table(
    current_miles, target_peak, cs_5k_s, cs_10k_s,
    proj_5k, proj_10k, current_1rms, str_proj,
    fitness, rd1,
) -> html.Div:
    """Compact table: metric | now | race day | delta."""
    rows_data = [
        ("Weekly Miles", f"{current_miles:.0f} mi", f"{target_peak:.0f} mi",
         f"+{((target_peak / current_miles) - 1) * 100:.0f}%" if current_miles else ""),
        ("5K", _fmt_time(cs_5k_s / 60) if cs_5k_s else "--",
         _fmt_time(proj_5k.get("projected_min", 0)) if proj_5k else "--",
         f"{proj_5k.get('delta_pct', 0):+.1f}%" if proj_5k else ""),
        ("10K", _fmt_time(cs_10k_s / 60) if cs_10k_s else "--",
         _fmt_time(proj_10k.get("projected_min", 0)) if proj_10k else "--",
         f"{proj_10k.get('delta_pct', 0):+.1f}%" if proj_10k else ""),
        ("Bench", f"{current_1rms.get('bench', 0)} lb",
         f"{str_proj.get('bench', {}).get('projected', 0)} lb",
         f"{str_proj.get('bench', {}).get('delta_pct', 0):+.1f}%"),
        ("Squat", f"{current_1rms.get('squat', 0)} lb",
         f"{str_proj.get('squat', {}).get('projected', 0)} lb",
         f"{str_proj.get('squat', {}).get('delta_pct', 0):+.1f}%"),
        ("Fitness (CTL)", f"{fitness['ctl']:.0f}",
         f"{rd1.get('ctl', 0):.0f}" if rd1 else "--", ""),
        ("Form (TSB)", f"{fitness['tsb']:+.0f} ({fitness['label']})",
         f"{rd1.get('tsb', 0):+.0f} ({rd1.get('readiness_label', '')})" if rd1 else "--", ""),
    ]

    header = html.Div([
        html.Span("", style={"flex": "2"}),
        html.Span("Now", style={
            "flex": "2", "fontSize": "10px", "fontWeight": "600",
            "textTransform": "uppercase", "letterSpacing": "0.08em",
            "color": TEXT_MUTED, "textAlign": "right",
        }),
        html.Span("Race Day", style={
            "flex": "2", "fontSize": "10px", "fontWeight": "600",
            "textTransform": "uppercase", "letterSpacing": "0.08em",
            "color": ACCENT, "textAlign": "right",
        }),
        html.Span("", style={"flex": "1"}),
    ], style={"display": "flex", "padding": "0 0 8px 0",
              "borderBottom": f"1px solid {BORDER}"})

    rows = []
    for label, now_val, proj_val, delta in rows_data:
        is_positive = delta.startswith("+") if delta else False
        delta_color = ACCENT_SLATE if is_positive else ACCENT_RED if delta.startswith("-") else TEXT_MUTED
        rows.append(html.Div([
            html.Span(label, style={
                "flex": "2", "fontSize": "11px", "color": TEXT_SECONDARY,
            }),
            html.Span(now_val, style={
                "flex": "2", "fontFamily": FONT_MONO, "fontSize": "12px",
                "textAlign": "right", "color": TEXT_MUTED,
            }),
            html.Span(proj_val, style={
                "flex": "2", "fontFamily": FONT_MONO, "fontSize": "12px",
                "fontWeight": "600", "textAlign": "right",
            }),
            html.Span(delta, style={
                "flex": "1", "fontFamily": FONT_MONO, "fontSize": "10px",
                "color": delta_color, "textAlign": "right",
            }),
        ], style={"display": "flex", "padding": "3px 0",
                  "borderBottom": f"1px solid {BORDER}",
                  "alignItems": "baseline"}))

    return html.Div([header, *rows], style={
        "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
        "borderRadius": "6px", "padding": "8px 12px",
    })


def _metric_row(label: str, value: str, unit: str) -> html.Div:
    """Single row in the Now/Race Day comparison."""
    return html.Div([
        html.Span(label, style={
            "fontSize": "12px", "color": TEXT_MUTED,
            "minWidth": "80px", "display": "inline-block",
        }),
        html.Span(value, style={
            "fontFamily": FONT_MONO, "fontSize": "16px", "fontWeight": "700",
        }),
        html.Span(f" {unit}", style={
            "fontSize": "11px", "color": TEXT_SECONDARY, "marginLeft": "4px",
        }) if unit else None,
    ], style={"padding": "4px 0"})


def _fmt_time(minutes: float) -> str:
    """Format minutes to M:SS or H:MM:SS."""
    total_s = int(minutes * 60)
    if total_s < 3600:
        m = total_s // 60
        s = total_s % 60
        return f"{m}:{s:02d}"
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h}:{m:02d}:{s:02d}"


def _projected_outcomes_section(projections: dict) -> html.Div:
    """Render the projected outcomes from the Banister model."""
    race_proj = projections.get("race_projections", {})
    strength_proj = projections.get("strength_projections", {})

    if not race_proj and not strength_proj:
        return html.P("Insufficient data for projections.", style={"color": TEXT_MUTED})

    items = []

    # Method label
    if race_proj:
        first = next(iter(race_proj.values()))
        method = first.get("method", "")
        if method:
            items.append(html.P(method, style={
                "color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "16px",
                "fontStyle": "italic",
            }))

    # Race projections
    if race_proj:
        race_rows = []
        for dist, data in race_proj.items():
            delta = data["delta_pct"]
            color = ACCENT_SLATE if delta < 0 else ACCENT_RED
            arrow = "\u2193" if delta < 0 else "\u2191"
            race_rows.append(html.Div([
                html.Span(dist, style={
                    "fontWeight": "600", "minWidth": "120px", "display": "inline-block",
                }),
                html.Span(f"{_fmt_time(data['current_min'])}", style={
                    "color": TEXT_SECONDARY, "minWidth": "70px", "display": "inline-block",
                }),
                html.Span(" \u2192 ", style={"color": TEXT_MUTED}),
                html.Span(f"{_fmt_time(data['projected_min'])}", style={
                    "fontWeight": "700", "color": color, "minWidth": "70px",
                    "display": "inline-block",
                }),
                html.Span(f" {arrow} {abs(delta):.1f}%", style={
                    "color": color, "fontSize": "13px", "marginLeft": "8px",
                }),
            ], style={"marginBottom": "8px", "fontSize": "14px"}))

        items.append(html.Div([
            html.H6("Race Times", style={"color": ACCENT, "marginBottom": "8px",
                                          "fontSize": "13px", "letterSpacing": "0.05em"}),
            *race_rows,
        ], style={"marginBottom": "20px"}))

    # Strength projections
    if strength_proj:
        str_rows = []
        _lift_names = {"bench": "Bench", "squat": "Squat",
                       "deadlift": "Deadlift", "ohp": "OHP"}
        for lift, data in strength_proj.items():
            delta = data["delta_pct"]
            color = ACCENT_SLATE if delta > 0 else ACCENT_RED
            arrow = "\u2191" if delta > 0 else "\u2193"
            str_rows.append(html.Div([
                html.Span(_lift_names.get(lift, lift.title()), style={
                    "fontWeight": "600", "minWidth": "120px", "display": "inline-block",
                }),
                html.Span(f"{data['current']} lb", style={
                    "color": TEXT_SECONDARY, "minWidth": "70px", "display": "inline-block",
                }),
                html.Span(" \u2192 ", style={"color": TEXT_MUTED}),
                html.Span(f"{data['projected']} lb", style={
                    "fontWeight": "700", "color": color, "minWidth": "70px",
                    "display": "inline-block",
                }),
                html.Span(f" {arrow} {abs(delta):.1f}%", style={
                    "color": color, "fontSize": "13px", "marginLeft": "8px",
                }),
            ], style={"marginBottom": "8px", "fontSize": "14px"}))

        items.append(html.Div([
            html.H6("Estimated 1RM", style={"color": ACCENT_AMBER, "marginBottom": "8px",
                                              "fontSize": "13px", "letterSpacing": "0.05em"}),
            *str_rows,
        ]))

    return html.Div(items, style={
        "backgroundColor": BG_CARD, "padding": "20px",
        "border": f"1px solid {BORDER}",
    })


def _legend():
    items = []
    for wtype, color in WORKOUT_TYPE_COLORS.items():
        items.append(html.Span([
            html.Span("\u25a0 ", style={"color": color, "fontSize": "1.1rem"}),
            html.Span(wtype.title(), style={"marginRight": "16px", "fontSize": "0.85rem"}),
        ]))
    items.append(html.Span([
        html.Span("\u25a0 ", style={"color": "rgba(34,197,94,0.7)", "fontSize": "1.1rem"}),
        html.Span("Completed", style={"marginRight": "16px", "fontSize": "0.85rem"}),
    ]))
    return html.Div(items, style={"marginTop": "16px"})


def _phase_section(week, today: date):
    phase_color = PHASE_COLORS.get(week.phase, ACCENT)

    week_end = week.start_date + timedelta(days=6)
    is_past = week_end < today
    is_current = week.start_date <= today <= week_end

    workout_cards = []
    for w in week.workouts:
        color = WORKOUT_TYPE_COLORS.get(w.session_type, TEXT_SECONDARY)
        workout_cards.append(html.Div([
            html.Div([
                html.Span(w.day.strftime("%a %b %d"),
                          style={"color": TEXT_SECONDARY, "fontSize": "0.8rem",
                                  "marginRight": "12px", "minWidth": "80px",
                                  "display": "inline-block"}),
                html.Span(w.title, className="workout-title"),
                html.Span(f" ({w.intensity})" if w.intensity else "",
                          style={"color": TEXT_SECONDARY, "fontSize": "0.8rem"}),
            ]),
            html.Div([
                html.Div(detail, style={"fontSize": "0.8rem", "color": TEXT_SECONDARY})
                for detail in w.details
            ], className="workout-detail") if w.details else None,
            html.Div(w.notes, style={"fontSize": "0.8rem", "color": ACCENT,
                                       "marginTop": "4px"}) if w.notes else None,
        ], className="workout-card",
           style={"borderLeftColor": color}))

    summary = html.H6([
        html.Span(f"Week {week.week_num}",
                  style={"color": phase_color, "fontWeight": "700"}),
        html.Span(f" \u2014 {week.phase_label}",
                  style={"color": TEXT_SECONDARY, "fontWeight": "400"}),
        html.Span(f" | {week.target_miles:.0f} mi target" if week.target_miles else "",
                  style={"color": TEXT_SECONDARY, "fontSize": "0.8rem",
                          "marginLeft": "8px"}),
        html.Span(" \u2190 THIS WEEK" if is_current else "",
                  style={"color": ACCENT, "fontSize": "0.75rem",
                          "marginLeft": "8px", "fontWeight": "600"}),
    ], style={"marginBottom": "12px"})

    return html.Details([
        html.Summary(summary, style={"cursor": "pointer", "listStyle": "none"}),
        html.Div(workout_cards, style={"paddingLeft": "8px"}),
    ], open=not is_past, style={"marginBottom": "24px"})


def _obstacle_prep_section():
    items = []
    for category, info in SPARTAN_OBSTACLE_PREP.items():
        label = category.replace("_", " ").title()
        exercises = info["exercises"]
        freq = info.get("frequency", "")
        items.append(html.Div([
            html.H6(label, style={"color": ACCENT_AMBER, "marginBottom": "4px"}),
            html.Ul([html.Li(ex, style={"fontSize": "0.85rem", "color": TEXT_SECONDARY})
                      for ex in exercises]),
            html.P(f"Frequency: {freq}",
                   style={"fontSize": "0.8rem", "color": TEXT_MUTED})
            if freq else None,
        ], style={"marginBottom": "12px"}))
    return html.Div(items, style={
        "backgroundColor": BG_CARD, "padding": "16px",
        "border": f"1px solid {BORDER}", "marginBottom": "24px",
    })


def _science_section():
    return html.Div([
        html.Details([
            html.Summary("Training Load & Predictions"),
            html.Ul([
                html.Li("Banister (1975/1991): Fitness-fatigue impulse-response model. "
                         "Exponential TRIMP with physiologically-derived HR-lactate weighting."),
                html.Li("Mujika & Padilla (2000): ~2.5%/week VO2max decay with complete detraining."),
                html.Li("Hickson et al. (1985): Volume can be cut by 2/3 with no VO2max loss "
                         "if intensity is maintained."),
                html.Li("Ogasawara et al. (2013): No 1RM loss during 3-week detraining periods."),
                html.Li("McMaster et al. (2013): ~2%/week 1RM decay after 3-week grace period."),
            ], style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
        ]),
        html.Details([
            html.Summary("Concurrent Training"),
            html.Ul([
                html.Li("Wilson et al. (2012): Running causes greater interference with strength than cycling."),
                html.Li("Robineau et al. (2016): Separate run and lift sessions by 6+ hours."),
                html.Li("Ronnested et al. (2011): 75-85% 1RM, 2x/week sufficient for strength maintenance."),
                html.Li("Rhea et al. (2003): 1-2%/week 1RM gains for trained individuals."),
            ], style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
        ]),
        html.Details([
            html.Summary("Taper Protocol"),
            html.Ul([
                html.Li("Mujika & Padilla (2003): 60-90% volume reduction, maintain intensity."),
                html.Li("Exponential taper > linear taper for performance."),
                html.Li("Expected improvement: ~3% (range 0.5-6%)."),
            ], style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
        ]),
        html.Details([
            html.Summary("Periodization"),
            html.Ul([
                html.Li("Issurin (2010): Block periodization with phase-specific focus."),
                html.Li("Back-to-back race strategy: 10K as sharpener, 5-day recovery before Spartan."),
            ], style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
        ]),
    ], style={"fontSize": "0.9rem", "marginBottom": "24px"})


@callback(
    Output("ics-download", "data"),
    Input("export-ics-btn", "n_clicks"),
    Input("ics-store", "data"),
    prevent_initial_call=True,
)
def download_ics(n_clicks, ics_content):
    if not n_clicks or not ics_content:
        return None
    return dict(content=ics_content, filename="training-plan.ics", type="text/calendar")
