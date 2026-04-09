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
    TEXT_SECONDARY, TEXT_MUTED, BG_CARD, BORDER,
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

    # Get current CTL for target-driven plan scaling
    fitness = get_current_fitness(df)
    current_ctl = fitness["ctl"]
    # Target CTL: 20% above current (realistic 8-week improvement)
    target_ctl = current_ctl * 1.20 if current_ctl > 0 else None

    plan = generate_training_plan(
        start_date=_START_DATE,
        race1_date=_RACE1_DATE,
        race2_date=_RACE2_DATE,
        current_1rms=current_1rms,
        current_weekly_miles=current_miles,
        current_ctl=current_ctl if current_ctl > 0 else None,
        target_ctl=target_ctl,
    )

    flat = plan_to_flat_list(plan)

    total_lift = sum(1 for r in flat if r["type"] == "lift")
    total_run = sum(1 for r in flat if r["type"] == "run")
    total_rest = sum(1 for r in flat if r["type"] in ("rest", "mobility"))

    ics_content = _generate_ics(flat)

    # Data computations
    projected = get_projected_fitness(df, plan)
    mileage = get_mileage_progression(df, plan)
    strength_trends = get_1rm_trends(df)
    race_readiness = get_race_readiness(df, plan, [_RACE1_DATE, _RACE2_DATE])
    compliance_data = get_compliance(df, flat)
    plan_projections = get_plan_projections(df, plan, current_1rms)

    today = date.today()

    return html.Div([
        # Hero
        hero_section(
            label="TRAINING PLAN",
            headline="8 weeks. 2 races. No excuses.",
            subtext=(
                "Boulder Bolder 10K (May 25) + Spartan Beast (May 30-31). "
                "Calibrated from your current fitness."
            ),
        ),

        # ICS export
        dcc.Download(id="ics-download"),
        dcc.Store(id="ics-store", data=ics_content),
        html.Div(
            html.Button("Export to Calendar (.ics)", id="export-ics-btn",
                        style={
                            "background": "none",
                            "border": f"1px solid {ACCENT}",
                            "color": ACCENT,
                            "padding": "8px 20px",
                            "fontSize": "14px",
                            "fontWeight": "600",
                            "cursor": "pointer",
                            "letterSpacing": "0.05em",
                        }),
            style={"textAlign": "center", "marginBottom": "24px"},
        ),

        # ── FITNESS STATE ──
        page_section("CURRENT FITNESS", [
            feature_grid([
                numbered_card(1, "Fitness (CTL)", "",
                              value=f"{fitness['ctl']:.0f}", color=ACCENT_SLATE),
                numbered_card(2, "Fatigue (ATL)", "",
                              value=f"{fitness['atl']:.0f}", color=ACCENT),
                numbered_card(3, "Form (TSB)", "",
                              value=f"{fitness['tsb']:+.0f}", color=ACCENT_AMBER),
                numbered_card(4, "Status", "",
                              value=fitness["label"], color=ACCENT_SLATE),
            ], columns=4),
            fitness_freshness_chart(projected, race_dates=[_RACE1_DATE, _RACE2_DATE]),
        ]),

        # ── RACE READINESS ──
        page_section("RACE READINESS", [
            html.P("Projected fitness at race dates based on planned training load.",
                   style={"color": TEXT_SECONDARY, "fontSize": "13px", "marginBottom": "16px"}),
            html.Div(
                [_readiness_badge(r) for r in race_readiness] if race_readiness else [
                    html.P("Insufficient data for projections.", style={"color": TEXT_MUTED})
                ],
                style={"display": "flex", "gap": "16px", "flexWrap": "wrap"},
            ),
        ], alt_bg=True),

        # ── EXPECTED OUTCOMES ──
        page_section("EXPECTED OUTCOMES", [
            _projected_outcomes_section(plan_projections),
        ]),

        # ── THE NUMBERS ──
        page_section("THE NUMBERS", [
            feature_grid([
                numbered_card(1, "Duration", "Apr 6 \u2014 May 31",
                              value="8 weeks", color=ACCENT),
                numbered_card(2, "Lift Sessions", "",
                              value=str(total_lift), color=ACCENT_AMBER),
                numbered_card(3, "Run Sessions", "",
                              value=str(total_run), color=ACCENT_SLATE),
                numbered_card(4, "Rest Days", "",
                              value=str(total_rest), color=ACCENT_SLATE),
            ], columns=4),
        ]),

        # Statement
        statement_section(
            "STARTING POINT",
            f"Starting from {current_miles:.0f} miles/week and a "
            f"{current_1rms['squat']}lb squat. Let\u2019s see what 8 weeks can do.",
        ),

        # ── MILEAGE PROGRESSION ──
        page_section("MILEAGE PROGRESSION", [
            mileage_progression_chart(mileage),
        ], alt_bg=True),

        # ── STRENGTH TRENDS ──
        page_section("STRENGTH TRENDS", [
            html.Div([
                html.Div([
                    strength_progression_chart(lift, prog_df),
                ], style={"flex": "1", "minWidth": "300px"})
                for lift, prog_df in strength_trends.items()
            ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap"})
            if strength_trends else
            html.P("No lifting data available for strength trends.",
                   style={"color": TEXT_MUTED}),
        ]),

        # ── COMPLIANCE ──
        *(
            [page_section("PLAN COMPLIANCE", [
                compliance_bar(compliance_data["pct"]),
                html.Div([
                    html.Span(f"{compliance_data['total_completed']}", style={
                        "fontWeight": "700", "color": ACCENT_SLATE,
                    }),
                    html.Span(f" of {compliance_data['total_planned']} planned sessions completed",
                              style={"color": TEXT_SECONDARY, "fontSize": "13px"}),
                ], style={"marginBottom": "16px"}),
            ], alt_bg=True)]
            if compliance_data["total_planned"] > 0 else []
        ),

        # ── CALENDAR ──
        page_section("CALENDAR", [
            enhanced_plan_calendar(flat, compliance_data),
            _legend(),
        ]),

        # ── WEEK BY WEEK ──
        page_section("WEEK BY WEEK", [
            *[_phase_section(week, today) for week in plan],
        ], alt_bg=True),

        # Obstacle Prep
        page_section("SPARTAN BEAST OBSTACLE PREPARATION", [
            _obstacle_prep_section(),
        ]),

        # Science
        page_section("THE SCIENCE", [
            _science_section(),
        ], alt_bg=True),

        # CTA
        cta_section("Now stop reading and go train."),

        # Footer
        footer(),
    ])


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
    params = projections.get("banister_params", {})

    if not race_proj and not strength_proj:
        return html.P("Insufficient data for projections.", style={"color": TEXT_MUTED})

    items = []

    # Method label
    method = ""
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
        for lift, data in strength_proj.items():
            delta = data["delta_pct"]
            color = ACCENT_SLATE if delta > 0 else ACCENT_RED
            arrow = "\u2191" if delta > 0 else "\u2193"
            str_rows.append(html.Div([
                html.Span(lift.title(), style={
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
