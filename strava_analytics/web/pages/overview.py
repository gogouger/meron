"""Overview — hybrid landing page modeled on ozniai.com homepage."""

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc
import pandas as pd

from strava_analytics.web import data
from strava_analytics.web.components import charts
from strava_analytics.web.components.layout import (
    hero_section, page_section, statement_section, feature_grid,
    numbered_card, cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_TEAL, ACCENT_GREEN, ACCENT_YELLOW, ACCENT_RED,
    TEXT_SECONDARY,
)
from strava_analytics.metrics import format_pace
from strava_analytics.vo2max import compute_athlete_vdot
from strava_analytics.lifting_program import END_PRS

dash.register_page(__name__, path="/", name="Overview")

CHART_CONFIG = {
    "displaylogo": False,
    "scrollZoom": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "toImage", "autoScale2d"],
}


def layout(**_kwargs):
    df = data.get_df()
    runs = data.get_runs()
    lifts = data.get_lifts()
    profile = data.get_profile()

    # Totals
    total_activities = len(df)
    total_miles = df["distance_mi"].sum()
    total_runs = len(runs)
    total_lifts = len(lifts)
    start_date = df["date"].min()

    # Running stats
    avg_pace = format_pace(runs["pace_min_per_mi"].mean()) if not runs.empty else "--"

    # Current fatigue
    fatigue_now = "Unknown"
    if "fatigue_level" in df.columns:
        recent_fatigue = df[df["fatigue_level"].notna()].tail(1)
        if not recent_fatigue.empty:
            fatigue_now = recent_fatigue.iloc[0]["fatigue_level"]

    # VDOT
    try:
        vdot = compute_athlete_vdot(df)
    except Exception:
        vdot = 0

    # Lifting maxes
    bench_1rm = END_PRS.get("bench_1rm", "?")
    squat_1rm = END_PRS.get("squat_1rm", "?")
    dl_1rm = END_PRS.get("deadlift_1rm", "?")

    # Fatigue-driven statement
    statements = {
        "Fresh": "Rested and dangerous.",
        "Normal": "Consistent beats heroic. Keep stacking days.",
        "Fatigued": "The body is willing. The legs disagree.",
        "Heavy Load": "Respect the load. Recovery is training too.",
        "Unknown": "The data speaks. You just have to listen.",
    }
    form_text = statements.get(fatigue_now, statements["Unknown"])

    return html.Div([
        # Hero
        hero_section(
            label="STRAVA ANALYTICS",
            headline="Your body is a machine. Here's the telemetry.",
            subtext=(
                f"{total_activities} activities. {total_miles:,.0f} miles. "
                f"Since {start_date:%B %Y}."
            ),
            cta_buttons=[
                dcc.Link("Start Running \u2192", href="/running",
                         className="btn-accent"),
                dcc.Link("View Plan", href="/plan",
                         className="btn-ghost"),
            ],
        ),

        # What We Track — ozniai.com "What We Build" pattern
        page_section("WHAT WE TRACK", [
            feature_grid([
                numbered_card(
                    1, "Running",
                    f"{total_runs} runs at {avg_pace} avg pace. "
                    "Pace trends, heart rate analysis, and estimated race fitness.",
                    link_text="Learn more", link_href="/running",
                ),
                numbered_card(
                    2, "Strength",
                    f"{total_lifts} sessions logged. "
                    f"Bench {bench_1rm} / Squat {squat_1rm} / Deadlift {dl_1rm}.",
                    link_text="Learn more", link_href="/lifting",
                ),
                numbered_card(
                    3, "Racing",
                    f"VDOT {vdot:.1f}. Next up: Boulder Bolder 10K (May 25) "
                    "and Spartan Beast (May 31).",
                    link_text="Learn more", link_href="/races",
                ),
            ]),
        ]),

        # Statement — current form
        statement_section("CURRENT FORM", form_text),

        # Training Load chart
        page_section("TRAINING LOAD", [
            html.P("Acute vs chronic training load. Green means go.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                          "marginBottom": "20px"}),
            dcc.Loading(type="dot", children=[
                dcc.Graph(figure=charts.fatigue_chart(df), config=CHART_CONFIG),
            ]),
        ], alt_bg=True),

        # Activity heatmap
        page_section("ACTIVITY", [
            html.P("Every square is a day you showed up.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                          "marginBottom": "20px"}),
            dcc.Loading(type="dot", children=[
                dcc.Graph(figure=charts.activity_heatmap(df), config=CHART_CONFIG),
            ]),
        ]),

        # CTA
        cta_section(
            "Ready to dig deeper?",
            "Your running, lifting, and race data \u2014 broken down.",
            "Explore Running \u2192", "/running",
        ),

        # Footer
        footer(),
    ])
