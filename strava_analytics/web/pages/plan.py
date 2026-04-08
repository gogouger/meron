"""Training plan page — ozniai.com subpage pattern."""

from datetime import date

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, Output, Input
import pandas as pd

from strava_analytics.web import data
from strava_analytics.web.components import charts
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

dash.register_page(__name__, path="/plan", name="Training Plan")



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
    """Generate an ICS calendar string from the training plan."""
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


def layout(**_kwargs):
    df = data.get_df()

    current_1rms = _get_current_1rms(df)
    current_miles = _get_current_weekly_miles(df)

    plan = generate_training_plan(
        start_date=date(2026, 4, 6),
        race1_date=date(2026, 5, 25),
        race2_date=date(2026, 5, 31),
        current_1rms=current_1rms,
        current_weekly_miles=current_miles,
    )

    flat = plan_to_flat_list(plan)

    total_lift = sum(1 for r in flat if r["type"] == "lift")
    total_run = sum(1 for r in flat if r["type"] == "run")
    total_rest = sum(1 for r in flat if r["type"] in ("rest", "mobility"))

    # Pre-generate ICS content so the callback can access it
    ics_content = _generate_ics(flat)

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

        # The Numbers
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

        # Calendar
        page_section("CALENDAR", [
            charts.plan_calendar_chart(flat),
            _legend(),
        ], alt_bg=True),

        # Week by Week
        page_section("WEEK BY WEEK", [
            *[_phase_section(week) for week in plan],
        ]),

        # Obstacle Prep
        page_section("SPARTAN BEAST OBSTACLE PREPARATION", [
            _obstacle_prep_section(),
        ], alt_bg=True),

        # Science
        page_section("THE SCIENCE", [
            _science_section(),
        ]),

        # CTA
        cta_section("Now stop reading and go train."),

        # Footer
        footer(),
    ])


def _legend():
    items = []
    for wtype, color in WORKOUT_TYPE_COLORS.items():
        items.append(html.Span([
            html.Span("\u25a0 ", style={"color": color, "fontSize": "1.1rem"}),
            html.Span(wtype.title(), style={"marginRight": "16px", "fontSize": "0.85rem"}),
        ]))
    return html.Div(items, style={"marginTop": "16px"})


def _phase_section(week):
    phase_color = PHASE_COLORS.get(week.phase, ACCENT)

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

    return html.Div([
        html.H6([
            html.Span(f"Week {week.week_num}",
                      style={"color": phase_color, "fontWeight": "700"}),
            html.Span(f" \u2014 {week.phase_label}",
                      style={"color": TEXT_SECONDARY, "fontWeight": "400"}),
            html.Span(f" | {week.target_miles:.0f} mi target" if week.target_miles else "",
                      style={"color": TEXT_SECONDARY, "fontSize": "0.8rem",
                              "marginLeft": "8px"}),
        ], style={"marginBottom": "12px"}),
        *workout_cards,
    ], style={"marginBottom": "24px"})


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
            html.Summary("Concurrent Training"),
            html.Ul([
                html.Li("Wilson et al. (2012): Running causes greater interference with strength than cycling."),
                html.Li("Robineau et al. (2016): Separate run and lift sessions by 6+ hours."),
                html.Li("Ronnested et al. (2011): 75-85% 1RM, 2x/week sufficient for strength maintenance."),
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
