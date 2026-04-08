"""Dash web application — Ozni AI brand-matched layout."""

import argparse
import logging
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, page_container, Input, Output, State, callback, clientside_callback
import pandas as pd

from strava_analytics.web import data
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_RED, TEXT_PRIMARY, TEXT_SECONDARY,
    TEXT_MUTED, BG_CARD, BORDER, ACTIVITY_TYPE_COLORS, RUN_TYPE_COLORS,
    LIFT_COLORS,
)
from strava_analytics.metrics import format_pace
from strava_analytics.web.components.cards import stat_cell, duration_str, activity_type_badge
from strava_analytics.web.components.routes import build_route_charts


def create_app() -> dash.Dash:
    app = dash.Dash(
        __name__,
        use_pages=True,
        pages_folder=str(Path(__file__).parent / "pages"),
        external_stylesheets=[
            dbc.themes.FLATLY,
            "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap",
            "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        ],
        external_scripts=[
            "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",
            "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js",
            "https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js",
            "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js",
            "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        ],
        suppress_callback_exceptions=True,
        title="Strava Analytics — Ozni AI",
        update_title=None,
    )

    # Hamburger icon (three-line SVG)
    hamburger_svg = html.Span(
        dash.dcc.Markdown(
            '<svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/>'
            '<line x1="3" y1="12" x2="21" y2="12"/>'
            '<line x1="3" y1="18" x2="21" y2="18"/></svg>',
            dangerously_allow_html=True,
        ),
    )

    # Navbar — matches ozniai.com fixed nav pattern (mobile-responsive)
    navbar = html.Nav([
        html.Div([
            html.Div([
                # Brand
                dcc.Link(
                    html.Span("Strava Analytics", className="brand-text"),
                    href="/", className="brand-link",
                ),
                # Mobile hamburger toggle
                html.Button(
                    hamburger_svg,
                    id="nav-toggle",
                    className="nav-toggle",
                    **{"aria-label": "Toggle navigation"},
                ),
                # Nav links
                html.Div([
                    dcc.Link("Overview", href="/", className="ozni-nav-link"),
                    dcc.Link("Running", href="/running", className="ozni-nav-link"),
                    dcc.Link("Lifting", href="/lifting", className="ozni-nav-link"),
                    dcc.Link("Activities", href="/activities", className="ozni-nav-link"),
                    dcc.Link("Predictions", href="/races", className="ozni-nav-link"),
                    dcc.Link("Plan", href="/plan", className="ozni-nav-link"),
                    dcc.Link("\u2699", href="/settings", className="ozni-nav-link",
                             style={"fontSize": "18px", "opacity": "0.6"},
                             title="Settings"),
                ], id="nav-links", className="nav-links"),
            ], className="nav-inner"),
        ], className="nav-container"),
    ], className="ozni-navbar")

    app.layout = html.Div([
        dcc.Location(id="url"),
        html.Div(id="page-title-target", style={"display": "none"}),
        # Global data version — incremented whenever settings are saved and data reloaded
        dcc.Store(id="data-version-store", data=0, storage_type="memory"),
        # Modal system: JS sets location hash → clientside callback → store → server renders
        dcc.Store(id="activity-modal-store", data=None),
        navbar,
        html.Main([
            page_container,
        ]),
        # Activity modal overlay — rendered by server callback
        html.Div(id="activity-modal-container"),
    ])

    # Dynamic page title based on current URL
    clientside_callback(
        """
        function(pathname) {
            var titles = {
                "/": "Overview",
                "/running": "Running",
                "/lifting": "Lifting",
                "/activities": "Activities",
                "/races": "Predictions",
                "/plan": "Plan",
                "/settings": "Settings"
            };
            var page = titles[pathname] || "Overview";
            document.title = "Strava Analytics \u2014 " + page;
            return "";
        }
        """,
        Output("page-title-target", "children"),
        Input("url", "pathname"),
    )

    # Mobile nav toggle — open/close the nav-links panel
    clientside_callback(
        """
        function(n_clicks) {
            var links = document.getElementById("nav-links");
            if (links) {
                links.classList.toggle("nav-open");
            }
            return "";
        }
        """,
        Output("nav-toggle", "className"),
        Input("nav-toggle", "n_clicks"),
        prevent_initial_call=True,
    )

    # Modal trigger: JS sets location hash to #modal:YYYY-MM-DD
    # This clientside callback watches the hash and forwards to the store
    clientside_callback(
        """
        function(href) {
            if (!href) return window.dash_clientside.no_update;
            var hash = new URL(href).hash;
            if (hash && hash.startsWith("#modal:")) {
                var dateStr = hash.substring(7);
                // Clear the hash so it can be re-triggered for same date
                history.replaceState(null, "", window.location.pathname + window.location.search);
                return {date: dateStr, ts: Date.now()};
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("activity-modal-store", "data"),
        Input("url", "href"),
        prevent_initial_call=True,
    )

    # Close modal: clicking close button clears the store
    clientside_callback(
        """
        function(n_clicks) {
            if (!n_clicks) return window.dash_clientside.no_update;
            return null;
        }
        """,
        Output("activity-modal-store", "data", allow_duplicate=True),
        Input("modal-close-btn", "n_clicks"),
        prevent_initial_call=True,
    )

    return app


# ── Global modal callback (outside create_app so it registers at import) ──

@callback(
    Output("activity-modal-container", "children"),
    Input("activity-modal-store", "data"),
    prevent_initial_call=True,
)
def render_activity_modal(modal_data):
    """Render the activity modal overlay when triggered by a chart click."""
    if not modal_data or not modal_data.get("date"):
        return html.Div()

    date_str = modal_data["date"]
    df = data.get_df()

    # Find activity by date string
    matches = df[df["date"].dt.strftime("%Y-%m-%d") == date_str]
    if matches.empty:
        return html.Div()

    row = matches.iloc[0]
    act_type = row.get("type", "")
    color = ACTIVITY_TYPE_COLORS.get(act_type, TEXT_MUTED)
    name = row.get("name", act_type or "Activity")
    date_display = row["date"].strftime("%b %d, %Y — %A")

    # Build stats
    stats = []
    dist = row.get("distance_mi", 0)
    dur = row.get("moving_time_s", 0)
    pace = row.get("pace_min_per_mi", None)
    hr = row.get("avg_hr", 0)
    max_hr = row.get("max_hr", 0)
    elev = row.get("elevation_gain_ft", 0) or 0
    cals = row.get("calories", 0)

    if dist and not pd.isna(dist) and dist > 0:
        stats.append(stat_cell("Distance", f"{dist:.1f} mi"))
    if pace and not pd.isna(pace) and pace > 0:
        stats.append(stat_cell("Pace", f"{format_pace(pace)} /mi"))
    if dur and not pd.isna(dur) and dur > 0:
        stats.append(stat_cell("Duration", duration_str(dur)))
    if hr and not pd.isna(hr):
        stats.append(stat_cell("Avg HR", f"{hr:.0f} bpm"))
    if max_hr and not pd.isna(max_hr):
        stats.append(stat_cell("Max HR", f"{max_hr:.0f} bpm"))
    if elev > 0:
        stats.append(stat_cell("Elevation", f"\u2191{elev:.0f} ft"))
    if cals and not pd.isna(cals) and cals > 0:
        stats.append(stat_cell("Calories", f"{cals:.0f}"))

    # Lift-specific stats
    if act_type == "Weight Training":
        for label, col in [("Bench", "bench_weight"), ("Squat", "squat_weight"),
                            ("Deadlift", "deadlift_weight"), ("OHP", "ohp_weight")]:
            val = row.get(col, None)
            if val is not None and not pd.isna(val):
                stats.append(stat_cell(label, f"{val:.0f} lbs"))

    # Description
    desc = row.get("description", "")
    desc_el = None
    if desc and isinstance(desc, str) and desc.strip():
        desc_el = html.P(desc.strip(), style={
            "color": TEXT_SECONDARY, "fontSize": "13px",
            "marginTop": "16px", "fontStyle": "italic",
            "borderTop": f"1px solid {BORDER}", "paddingTop": "12px",
        })

    # Route charts (eager load in modal since user explicitly clicked)
    route_el = None
    filename = row.get("filename", "")
    if filename and act_type in ("Run", "Walk", "Hike", "Ride"):
        route_el = html.Div(
            build_route_charts(filename, df=data.get_df()),
            style={"marginTop": "16px", "borderTop": f"1px solid {BORDER}",
                   "paddingTop": "12px"},
        )

    # Lift exercises
    exercises_el = None
    if act_type == "Weight Training":
        exercises_str = row.get("lift_exercises", "")
        if exercises_str and not pd.isna(exercises_str):
            exercises = [e.strip() for e in str(exercises_str).split(";") if e.strip()]
            if exercises:
                exercises_el = html.Div([
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
                ], style={"marginTop": "16px", "borderTop": f"1px solid {BORDER}",
                          "paddingTop": "12px"})

    # Type badge
    badge = activity_type_badge(act_type, color)
    run_type = row.get("run_type", "")
    run_badge = None
    if act_type == "Run" and run_type:
        rt_color = RUN_TYPE_COLORS.get(run_type, TEXT_MUTED)
        run_badge = activity_type_badge(run_type, rt_color)

    return html.Div([
        # Backdrop
        html.Div(id="modal-backdrop"),
        # Content
        html.Div([
            html.Button("\u00d7", id="modal-close-btn"),
            html.Div([
                html.Div([
                    html.Span(date_display, style={
                        "fontSize": "12px", "color": TEXT_MUTED,
                    }),
                    badge,
                    run_badge,
                ]),
                html.H4(name, style={
                    "fontSize": "18px", "fontWeight": "700",
                    "color": TEXT_PRIMARY, "marginTop": "4px", "marginBottom": "16px",
                }),
                html.Div(stats, style={
                    "display": "flex", "gap": "24px", "flexWrap": "wrap",
                }),
                desc_el,
                exercises_el,
                route_el,
            ]),
        ], id="modal-content"),
    ], id="activity-modal-overlay")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Strava Analytics Web Dashboard")
    parser.add_argument("export_dir",
                        help="Path to Strava export directory")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    data.init(args.export_dir)
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug, dev_tools_ui=False)


if __name__ == "__main__":
    main()
