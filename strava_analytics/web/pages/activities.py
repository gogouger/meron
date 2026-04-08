"""Activities — unified chronological feed of all activity types."""

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, clientside_callback, Output, Input, State, MATCH, no_update
import pandas as pd

from strava_analytics.web import data
from strava_analytics.web.components.cards import stat_cell, duration_str, activity_type_badge
from strava_analytics.web.components.routes import build_route_charts
from strava_analytics.web.components.layout import (
    hero_section, page_section, cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, ACCENT_RED,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BG_CARD, BORDER, ACTIVITY_TYPE_COLORS, LIFT_COLORS,
)
from strava_analytics.metrics import format_pace

dash.register_page(__name__, path="/activities", name="Activities")

_PAGE_SIZE = 50


# ── Card builders ─────────────────────────────────────────────────────

def _activity_card(row, idx: int) -> html.Details:
    """Build a single expandable activity card. Dispatches by type."""
    act_type = row.get("type", "")
    color = ACTIVITY_TYPE_COLORS.get(act_type, TEXT_MUTED)
    date_str = row["date"].strftime("%b %d, %Y")
    day_str = row["date"].strftime("%A")
    name = row.get("name", act_type or "Activity")
    date_id = row["date"].strftime("%Y-%m-%d")

    badge = activity_type_badge(act_type, color)

    # Primary stats — type-dependent
    primary = []
    detail_content = []

    dist = row.get("distance_mi", 0)
    dur = row.get("moving_time_s", 0)

    if act_type in ("Run", "Walk", "Hike", "Ride"):
        if dist and not pd.isna(dist) and dist > 0:
            primary.append(stat_cell("Distance", f"{dist:.1f} mi"))
        pace = row.get("pace_min_per_mi", None)
        if pace and not pd.isna(pace) and pace > 0:
            primary.append(stat_cell("Pace", f"{format_pace(pace)} /mi"))
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))
        hr = row.get("avg_hr", 0)
        if hr and not pd.isna(hr):
            primary.append(stat_cell("Avg HR", f"{hr:.0f} bpm"))
        elev = row.get("elevation_gain_ft", 0) or 0
        if elev > 0:
            primary.append(stat_cell("Elevation", f"\u2191{elev:.0f} ft"))

        # Detail: secondary stats
        secondary = []
        max_hr = row.get("max_hr", 0)
        if max_hr and not pd.isna(max_hr):
            secondary.append(stat_cell("Max HR", f"{max_hr:.0f} bpm"))
        cals = row.get("calories", 0)
        if cals and not pd.isna(cals) and cals > 0:
            secondary.append(stat_cell("Calories", f"{cals:.0f}"))
        temp = row.get("weather_temp_f", None)
        if temp is not None and not pd.isna(temp):
            secondary.append(stat_cell("Temp", f"{temp:.0f}\u00b0F"))
        weather = row.get("weather_condition", "")
        if weather and isinstance(weather, str) and weather.strip():
            secondary.append(stat_cell("Weather", weather[:20]))

        if secondary:
            detail_content.append(html.Div(secondary, style={
                "display": "flex", "gap": "24px", "flexWrap": "wrap",
                "marginTop": "12px", "paddingTop": "12px",
                "borderTop": f"1px solid {BORDER}",
            }))

        desc = row.get("description", "")
        if desc and isinstance(desc, str) and desc.strip():
            detail_content.append(html.P(desc.strip(), style={
                "color": TEXT_SECONDARY, "fontSize": "13px",
                "marginTop": "12px", "fontStyle": "italic",
            }))

        # Lazy route loading
        filename = row.get("filename", "")
        if filename:
            route_key = f"{date_id}-{idx}"
            detail_content.append(html.Button(
                "", id={"type": "act-route-btn", "index": route_key},
                n_clicks=0, style={"display": "none"},
            ))
            detail_content.append(
                dcc.Loading(
                    html.Div(id={"type": "act-route-container", "index": route_key}),
                    type="dot",
                )
            )

    elif act_type == "Weight Training":
        # Lift stats
        for label, col in [("Bench", "bench_weight"), ("Squat", "squat_weight"),
                            ("Deadlift", "deadlift_weight"), ("OHP", "ohp_weight")]:
            val = row.get(col, None)
            if val is not None and not pd.isna(val):
                primary.append(stat_cell(label, f"{val:.0f} lbs"))
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))

        # Detail: exercises
        exercises_str = row.get("lift_exercises", "")
        if exercises_str and not pd.isna(exercises_str):
            exercises = [e.strip() for e in str(exercises_str).split(";") if e.strip()]
            if exercises:
                detail_content.append(html.Div([
                    html.Div("EXERCISES", style={
                        "fontSize": "10px", "fontWeight": "600",
                        "textTransform": "uppercase", "letterSpacing": "0.1em",
                        "color": TEXT_MUTED, "marginBottom": "6px",
                    }),
                    html.Ul([
                        html.Li(ex, style={"fontSize": "13px", "color": TEXT_SECONDARY,
                                           "padding": "2px 0"})
                        for ex in exercises
                    ], style={"listStyleType": "disc", "paddingLeft": "18px", "margin": "0"}),
                ], style={"marginBottom": "12px"}))

        # Pullup stats
        pullup_sets = row.get("pullup_sets", None)
        pullup_reps = row.get("pullup_reps", None)
        parts = []
        if pullup_sets and not pd.isna(pullup_sets):
            parts.append(f"{int(pullup_sets)} sets")
        if pullup_reps and not pd.isna(pullup_reps):
            parts.append(f"{int(pullup_reps)} reps")
        if parts:
            detail_content.append(stat_cell("Pull-ups", " / ".join(parts)))

    else:
        # Swim, Yoga, Other
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))
        if dist and not pd.isna(dist) and dist > 0:
            primary.append(stat_cell("Distance", f"{dist:.1f} mi"))
        cals = row.get("calories", 0)
        if cals and not pd.isna(cals) and cals > 0:
            primary.append(stat_cell("Calories", f"{cals:.0f}"))

    # Run type sub-badge for runs
    run_type = row.get("run_type", "")
    run_badge = ""
    if act_type == "Run" and run_type:
        from strava_analytics.web.theme import RUN_TYPE_COLORS
        rt_color = RUN_TYPE_COLORS.get(run_type, TEXT_MUTED)
        run_badge = html.Span(
            run_type,
            style={
                "backgroundColor": rt_color, "color": "white",
                "fontSize": "9px", "fontWeight": "600",
                "textTransform": "uppercase", "letterSpacing": "0.05em",
                "padding": "1px 6px", "marginLeft": "6px",
                "display": "inline-block",
            },
        )

    return html.Details([
        html.Summary([
            html.Div([
                html.Div([
                    html.Span(date_str, style={
                        "fontWeight": "600", "fontSize": "14px", "color": TEXT_PRIMARY,
                    }),
                    html.Span(f" {day_str}", style={
                        "color": TEXT_MUTED, "fontSize": "13px",
                    }),
                    badge,
                    run_badge if run_badge else None,
                ]),
                html.Div(name, style={
                    "fontSize": "13px", "color": TEXT_SECONDARY, "marginTop": "2px",
                }),
            ], style={"marginBottom": "12px"}),
            html.Div(primary, style={
                "display": "flex", "gap": "24px", "flexWrap": "wrap",
            }) if primary else None,
        ], style={"listStyle": "none", "cursor": "pointer"}),
        html.Div(detail_content, style={
            "padding": "12px 0 0 0",
        }) if detail_content else None,
    ], id=f"activity-card-{date_id}-{idx}",
       style={
        "backgroundColor": BG_CARD,
        "border": f"1px solid {BORDER}",
        "padding": "20px 24px", "marginBottom": "8px",
        "borderLeft": f"3px solid {color}",
    })


# ── Layout ────────────────────────────────────────────────────────────

def layout(**_kwargs):
    df = data.get_df()
    if df.empty:
        return html.P("No activity data available.")

    sorted_df = df.sort_values("date", ascending=False)
    total = len(sorted_df)
    types = sorted(df["type"].dropna().unique())

    # Build cards + filename mapping
    cards = []
    filenames_dict = {}
    for idx, (_, row) in enumerate(sorted_df.iterrows()):
        cards.append(_activity_card(row, idx))
        fn = row.get("filename", "")
        if fn:
            date_id = row["date"].strftime("%Y-%m-%d")
            filenames_dict[f"{date_id}-{idx}"] = fn

    visible = cards[:_PAGE_SIZE]
    hidden = cards[_PAGE_SIZE:]

    return html.Div([
        hero_section(
            label="ACTIVITIES",
            headline="Everything. One feed.",
            subtext=f"{total} activities across {len(types)} types.",
        ),

        # Filters
        page_section("FILTER", [
            dbc.Row([
                dbc.Col([
                    html.Label("Activity Type",
                               style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
                    dcc.Dropdown(
                        id="activity-type-filter",
                        options=[{"label": t, "value": t} for t in types],
                        multi=True,
                        placeholder="All types",
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Date Range",
                               style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
                    dcc.DatePickerRange(
                        id="activity-date-range",
                        start_date=df["date"].min(),
                        end_date=df["date"].max(),
                        style={"fontSize": "0.85rem"},
                    ),
                ], md=6),
            ]),
        ], alt_bg=True),

        # Activity feed
        page_section("ALL ACTIVITIES", [
            html.Div(visible, id="visible-activity-cards"),
            html.Div(hidden, id="hidden-activity-cards",
                      style={"display": "none"}) if hidden else html.Div(
                          id="hidden-activity-cards", style={"display": "none"}),
            html.Button(
                f"Show All ({len(hidden)} more)",
                id="show-all-activities-btn",
                n_clicks=0,
                style={
                    "display": "block" if hidden else "none",
                    "margin": "20px auto",
                    "padding": "10px 24px",
                    "fontSize": "14px", "fontWeight": "600",
                    "color": TEXT_PRIMARY, "backgroundColor": BG_CARD,
                    "border": f"1px solid {BORDER}", "cursor": "pointer",
                },
            ),
        ]),

        # Filename store for lazy route loading
        dcc.Store(id="act-filenames-store", data=filenames_dict),

        cta_section(
            "Back to the numbers?",
            "Charts, predictions, and training plans.",
            "Running \u2192", "/running",
        ),
        footer(),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────

# Show all activities
clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        return [{"display": "block"}, {"display": "none"}];
    }
    """,
    Output("hidden-activity-cards", "style"),
    Output("show-all-activities-btn", "style"),
    Input("show-all-activities-btn", "n_clicks"),
    prevent_initial_call=True,
)


# Lazy route loading
@callback(
    Output({"type": "act-route-container", "index": MATCH}, "children"),
    Input({"type": "act-route-btn", "index": MATCH}, "n_clicks"),
    State({"type": "act-route-btn", "index": MATCH}, "id"),
    State("act-filenames-store", "data"),
    prevent_initial_call=True,
)
def load_activity_route(n_clicks, btn_id, filenames):
    if not n_clicks:
        return no_update
    key = btn_id["index"]
    filename = filenames.get(key, "")
    if not filename:
        return html.P("No GPS data for this activity.", style={"color": TEXT_MUTED})
    return build_route_charts(filename)
