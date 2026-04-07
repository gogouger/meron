"""Running analytics page — ozniai.com subpage pattern."""

import json

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, clientside_callback, Output, Input, State, ALL, MATCH, ctx, no_update, ClientsideFunction
import pandas as pd
import plotly.graph_objects as go

from strava_analytics.web import data
from strava_analytics.web.components import charts
from strava_analytics.web.components.layout import (
    hero_section, page_section, feature_grid, numbered_card,
    cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_TEAL, ACCENT_GREEN, ACCENT_RED, ACCENT_YELLOW,
    ACCENT_PURPLE, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BG_CARD, BORDER, RUN_TYPE_COLORS,
)
from strava_analytics.metrics import format_pace

dash.register_page(__name__, path="/running", name="Running")

CHART_CONFIG = {
    "displaylogo": False,
    "scrollZoom": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "toImage", "autoScale2d"],
}

# Colors for run type badges
_TYPE_COLORS = {
    "race": ACCENT, "workout": ACCENT_TEAL, "long": ACCENT_PURPLE,
    "moderate": ACCENT_YELLOW, "easy": ACCENT_GREEN,
    "short/easy": "#0284c7", "ruck": ACCENT_PURPLE,
}


def _pace_str(pace_float):
    if pd.isna(pace_float):
        return "--"
    m = int(pace_float)
    s = int((pace_float - m) * 60)
    return f"{m}:{s:02d}"


def _duration_str(seconds):
    if pd.isna(seconds) or seconds <= 0:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


_route_cache = {}  # filename -> children; lazy-filled by load_route callback


def _stat_cell(label, val):
    return html.Div([
        html.Div(label, style={
            "fontSize": "10px", "fontWeight": "500",
            "textTransform": "uppercase", "letterSpacing": "0.1em",
            "color": TEXT_MUTED,
        }),
        html.Div(val, style={
            "fontFamily": "'IBM Plex Mono', monospace",
            "fontSize": "14px", "fontWeight": "600",
            "color": TEXT_PRIMARY,
        }),
    ], style={"minWidth": "80px"})


def _run_card(run, idx):
    """Build a single expandable run card using HTML <details> (no Dash callbacks)."""
    run_type = run.get("run_type", "")
    type_color = _TYPE_COLORS.get(run_type, TEXT_MUTED)
    date_str = run["date"].strftime("%b %d, %Y")
    day_str = run["date"].strftime("%A")
    name = run.get("name", "Run")
    dist = run.get("distance_mi", 0)
    pace = _pace_str(run.get("pace_min_per_mi"))
    duration = _duration_str(run.get("moving_time_s", 0))
    hr = run.get("avg_hr", 0)
    max_hr_val = run.get("max_hr", 0)
    elev = run.get("elevation_gain_ft", 0) or 0
    calories = run.get("calories", 0) or 0
    weather = run.get("weather_condition", "")
    temp_f = run.get("weather_temp_f", None)
    description = run.get("description", "")

    badge = html.Span(
        run_type or "run",
        style={
            "backgroundColor": type_color, "color": "white",
            "fontSize": "10px", "fontWeight": "600",
            "textTransform": "uppercase", "letterSpacing": "0.05em",
            "padding": "2px 8px", "marginLeft": "8px",
            "display": "inline-block",
        },
    )

    # Primary stats
    primary_stats = [
        _stat_cell("Distance", f"{dist:.1f} mi"),
        _stat_cell("Pace", f"{pace} /mi"),
        _stat_cell("Duration", duration),
    ]
    if hr and not pd.isna(hr):
        primary_stats.append(_stat_cell("Avg HR", f"{hr:.0f} bpm"))
    if elev > 0:
        primary_stats.append(_stat_cell("Elevation", f"\u2191{elev:.0f} ft"))

    # Secondary stats (shown when expanded)
    secondary = []
    if max_hr_val and not pd.isna(max_hr_val):
        secondary.append(_stat_cell("Max HR", f"{max_hr_val:.0f} bpm"))
    if calories and not pd.isna(calories) and calories > 0:
        secondary.append(_stat_cell("Calories", f"{calories:.0f}"))
    if temp_f is not None and not pd.isna(temp_f):
        secondary.append(_stat_cell("Temp", f"{temp_f:.0f}\u00b0F"))
    if weather and isinstance(weather, str) and weather.strip():
        secondary.append(_stat_cell("Weather", weather[:20]))

    # Build expandable detail content
    detail_content = []
    if secondary:
        detail_content.append(html.Div(secondary, style={
            "display": "flex", "gap": "24px", "flexWrap": "wrap",
            "marginTop": "12px", "paddingTop": "12px",
            "borderTop": f"1px solid {BORDER}",
        }))
    if description and isinstance(description, str) and description.strip():
        detail_content.append(html.P(description.strip(), style={
            "color": TEXT_SECONDARY, "fontSize": "13px",
            "marginTop": "12px", "fontStyle": "italic",
        }))

    date_id = run["date"].strftime("%Y-%m-%d")
    filename = run.get("filename", "")

    # Route button + lazy container (only when a FIT file exists)
    if filename:
        route_key = f"{date_id}-{idx}"
        detail_content.append(html.Button(
            "View Route & Charts",
            id={"type": "route-btn", "index": route_key},
            n_clicks=0,
            style={
                "background": "none", "border": "none", "cursor": "pointer",
                "color": ACCENT_TEAL, "fontSize": "13px", "fontWeight": "600",
                "padding": "0", "marginTop": "12px",
                "textDecoration": "underline",
            },
        ))
        detail_content.append(
            dcc.Loading(
                html.Div(
                    id={"type": "route-container", "index": route_key},
                ),
                type="dot",
            )
        )

    return html.Details([
        html.Summary([
            # Header row
            html.Div([
                html.Div([
                    html.Div([
                        html.Span(date_str, style={
                            "fontWeight": "600", "fontSize": "14px",
                            "color": TEXT_PRIMARY,
                        }),
                        html.Span(f" {day_str}", style={
                            "color": TEXT_MUTED, "fontSize": "13px",
                        }),
                        badge,
                    ]),
                    html.Div(name, style={
                        "fontSize": "13px", "color": TEXT_SECONDARY,
                        "marginTop": "2px",
                    }),
                ]),
            ], style={"marginBottom": "12px"}),
            # Primary stats
            html.Div(primary_stats, style={
                "display": "flex", "gap": "24px", "flexWrap": "wrap",
            }),
        ], style={"listStyle": "none", "cursor": "pointer"}),
        # Detail content (shown when expanded)
        html.Div(detail_content) if detail_content else None,
    ], id=f"run-card-{date_id}-{idx}",
       style={
        "backgroundColor": BG_CARD,
        "border": f"1px solid {BORDER}",
        "padding": "20px 24px", "marginBottom": "8px",
        "borderLeft": f"3px solid {type_color}",
    })


def _shoe_mileage_section(runs: pd.DataFrame) -> html.Div:
    """Show cumulative miles per shoe with retirement warnings."""
    if "gear" not in runs.columns:
        return html.Div()

    shoes = runs[runs["gear"].notna() & (runs["gear"] != "")].copy()
    if shoes.empty:
        return html.Div()

    shoe_stats = shoes.groupby("gear").agg(
        miles=("distance_mi", "sum"),
        runs=("activity_id", "count"),
        last_used=("date", "max"),
    ).sort_values("miles", ascending=False).reset_index()

    cards = []
    for _, shoe in shoe_stats.iterrows():
        miles = shoe["miles"]
        warning = miles >= 400
        cards.append(html.Div([
            html.Div([
                html.Span(shoe["gear"], style={
                    "fontWeight": "600", "fontSize": "14px", "color": TEXT_PRIMARY,
                }),
                html.Span(f"  {shoe['runs']} runs", style={
                    "color": TEXT_MUTED, "fontSize": "12px",
                }),
            ]),
            html.Div([
                html.Span(f"{miles:.0f} mi", style={
                    "fontFamily": "'IBM Plex Mono', monospace",
                    "fontSize": "18px", "fontWeight": "700",
                    "color": ACCENT_RED if warning else ACCENT_GREEN,
                }),
                html.Span(" — consider retiring" if warning else "", style={
                    "color": ACCENT_RED, "fontSize": "12px", "marginLeft": "8px",
                }),
            ], style={"marginTop": "4px"}),
        ], style={
            "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
            "padding": "16px 20px", "marginBottom": "8px",
            "borderLeft": f"3px solid {ACCENT_RED if warning else ACCENT_GREEN}",
        }))

    return html.Div(cards)


def _stroller_comparison_section(runs: pd.DataFrame) -> html.Div:
    """Side-by-side comparison of stroller vs non-stroller runs."""
    if "with_kid" not in runs.columns:
        return html.Div()

    stroller = runs[runs["with_kid"] == True]
    normal = runs[runs["with_kid"] == False]

    if stroller.empty or len(stroller) < 3:
        return html.P("Not enough stroller runs for comparison.",
                      style={"color": TEXT_MUTED})

    # Build comparison
    def _compare_row(label, stroller_val, normal_val, unit="", lower_is_better=False):
        diff = stroller_val - normal_val
        if lower_is_better:
            color = ACCENT_GREEN if diff < 0 else ACCENT_RED
        else:
            color = ACCENT_GREEN if diff > 0 else ACCENT_RED
        sign = "+" if diff > 0 else ""
        return html.Div([
            html.Div(label, style={"fontSize": "10px", "textTransform": "uppercase",
                                    "letterSpacing": "0.1em", "color": TEXT_MUTED,
                                    "gridColumn": "1 / -1", "marginBottom": "4px"}),
            html.Div(f"{normal_val:.1f}{unit}", style={
                "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "16px",
                "fontWeight": "600", "color": TEXT_PRIMARY,
            }),
            html.Div(f"{stroller_val:.1f}{unit}", style={
                "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "16px",
                "fontWeight": "600", "color": TEXT_PRIMARY,
            }),
            html.Div(f"{sign}{diff:.1f}{unit}", style={
                "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "13px",
                "fontWeight": "600", "color": color,
            }),
        ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr 1fr",
                  "gap": "4px", "padding": "8px 0",
                  "borderBottom": f"1px solid {BORDER}"})

    header = html.Div([
        html.Div("", style={"fontWeight": "600"}),
        html.Div("Solo", style={"fontSize": "11px", "fontWeight": "600",
                                 "textTransform": "uppercase", "color": TEXT_MUTED}),
        html.Div("Stroller", style={"fontSize": "11px", "fontWeight": "600",
                                     "textTransform": "uppercase", "color": TEXT_MUTED}),
        html.Div("Diff", style={"fontSize": "11px", "fontWeight": "600",
                                 "textTransform": "uppercase", "color": TEXT_MUTED}),
    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr 1fr",
              "gap": "4px", "padding": "8px 0",
              "borderBottom": f"1px solid {BORDER}"})

    rows = [header]
    rows.append(_compare_row("Avg Pace (min/mi)",
                             stroller["pace_min_per_mi"].mean(),
                             normal["pace_min_per_mi"].mean(),
                             "", lower_is_better=True))

    if stroller["avg_hr"].notna().any() and normal["avg_hr"].notna().any():
        rows.append(_compare_row("Avg HR (bpm)",
                                 stroller["avg_hr"].mean(),
                                 normal["avg_hr"].mean(),
                                 "", lower_is_better=True))

    rows.append(_compare_row("Avg Distance (mi)",
                             stroller["distance_mi"].mean(),
                             normal["distance_mi"].mean()))

    return html.Div([
        html.Div([
            html.Span(f"{len(stroller)} stroller runs", style={
                "color": TEXT_SECONDARY, "fontSize": "13px",
            }),
            html.Span(f" vs {len(normal)} solo runs", style={
                "color": TEXT_MUTED, "fontSize": "13px",
            }),
        ], style={"marginBottom": "16px"}),
        html.Div(rows, style={
            "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
            "padding": "16px 20px",
        }),
    ])


def layout(**_kwargs):
    runs = data.get_runs()

    if runs.empty:
        return html.P("No running data available.")

    total_runs = len(runs)
    total_miles = runs["distance_mi"].sum()
    avg_pace = format_pace(runs["pace_min_per_mi"].mean())
    runs_5k_plus = runs[runs["distance_mi"] >= 3.0]
    best_pace = format_pace(runs_5k_plus["pace_min_per_mi"].min()) if not runs_5k_plus.empty else format_pace(runs["pace_min_per_mi"].min())
    avg_hr = runs["avg_hr"].mean()
    max_hr = runs["max_hr"].max()

    # Run type options
    run_types = sorted(runs["run_type"].unique()) if "run_type" in runs.columns else []

    # Build run metadata for hover previews (no GPS parsing — that happens on demand)
    run_meta = {}
    for _, r in runs.iterrows():
        date_str = r["date"].strftime("%Y-%m-%d")
        run_meta[date_str] = {
            "name": r.get("name", "Run"),
            "dist": f"{r.get('distance_mi', 0):.1f} mi",
            "pace": _pace_str(r.get("pace_min_per_mi")),
            "duration": _duration_str(r.get("moving_time_s", 0)),
            "hr": f"{r['avg_hr']:.0f} bpm" if not pd.isna(r.get("avg_hr", None)) else "",
            "type": r.get("run_type", ""),
            "filename": r.get("filename", ""),
        }

    # Build run cards (most recent first) — lightweight, no Plotly graphs
    sorted_runs = runs.sort_values("date", ascending=False)
    run_cards = []
    filenames_dict = {}
    for idx, (_, run) in enumerate(sorted_runs.iterrows()):
        run_cards.append(_run_card(run, idx))
        fn = run.get("filename", "")
        if fn:
            date_id = run["date"].strftime("%Y-%m-%d")
            filenames_dict[f"{date_id}-{idx}"] = fn

    return html.Div([
        # Hero
        hero_section(
            label="RUNNING",
            headline="Every mile tells a story. Most of them hurt.",
            subtext=f"{total_runs} runs. {total_miles:.0f} miles. Best 5K+ pace: {best_pace} /mi.",
        ),

        # By the Numbers
        page_section("BY THE NUMBERS", [
            feature_grid([
                numbered_card(1, "Total Runs", f"{total_miles:.0f} total miles",
                              value=str(total_runs), color=ACCENT),
                numbered_card(2, "Average Pace", "all runs",
                              value=f"{avg_pace} /mi", color=ACCENT_TEAL),
                numbered_card(3, "Best 5K+ Pace", "runs over 3 miles",
                              value=f"{best_pace} /mi", color=ACCENT_GREEN),
                numbered_card(4, "Average HR", f"Max: {max_hr:.0f} bpm",
                              value=f"{avg_hr:.0f} bpm", color=ACCENT_RED),
            ], columns=4),
        ]),

        # Filters
        page_section("FILTER YOUR RUNS", [
            dbc.Row([
                dbc.Col([
                    html.Label("Run Type",
                               style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
                    dcc.Dropdown(
                        id="run-type-filter",
                        options=[{"label": t, "value": t} for t in run_types],
                        multi=True,
                        placeholder="All types",
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Date Range",
                               style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
                    dcc.DatePickerRange(
                        id="run-date-range",
                        start_date=runs["date"].min(),
                        end_date=runs["date"].max(),
                        style={"fontSize": "0.85rem"},
                    ),
                ], md=6),
            ]),
        ], alt_bg=True),

        # Run metadata for hover tooltips
        dcc.Store(id="run-meta-store", data=run_meta),
        # Filenames for lazy route loading
        dcc.Store(id="run-filenames-store", data=filenames_dict),

        # Pace Trend (hover = preview, click = scroll to run card)
        page_section("PACE TREND", [
            html.P("Hover for preview. Click to jump to that run.",
                   style={"color": TEXT_MUTED, "fontSize": "12px",
                          "marginBottom": "8px"}),
            dcc.Loading(type="dot", children=[
                dcc.Graph(id="pace-trend", config=CHART_CONFIG),
            ]),
            # Floating hover tooltip — follows mouse
            html.Div(id="run-hover-card", style={
                "display": "none",
                "position": "fixed",
                "zIndex": "1000",
                "backgroundColor": "#ffffff",
                "border": f"1px solid {BORDER}",
                "boxShadow": "0 8px 24px rgba(0,0,0,0.12)",
                "padding": "12px",
                "width": "260px",
                "pointerEvents": "none",
            }),
        ]),

        # Hidden divs for callbacks
        html.Div(id="scroll-target", style={"display": "none"}),
        html.Div(id="hover-target", style={"display": "none"}),
        html.Div(id="hr-scroll-target", style={"display": "none"}),
        html.Div(id="est5k-scroll-target", style={"display": "none"}),

        # Race Fitness
        page_section("RACE FITNESS", [
            html.P("How fast could you run a 5K right now? Click a point to jump to that run.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                          "marginBottom": "20px"}),
            dcc.Loading(type="dot", children=[
                dcc.Graph(id="est-5k", config=CHART_CONFIG),
            ]),
        ], alt_bg=True),

        # Volume & Heart Rate
        page_section("VOLUME & HEART RATE", [
            dbc.Row([
                dbc.Col(dcc.Loading(type="dot", children=[
                    dcc.Graph(id="weekly-miles", config=CHART_CONFIG),
                ]), md=6),
                dbc.Col(dcc.Loading(type="dot", children=[
                    dcc.Graph(id="hr-vs-pace", config=CHART_CONFIG),
                ]), md=6),
            ]),
        ]),

        # HR Analysis
        page_section("HEART RATE ANALYSIS", [
            _adjusted_hr_section(runs),
        ], alt_bg=True),

        # Shoe Mileage
        page_section("SHOE MILEAGE", [
            html.P("Track your miles. Retire shoes before they retire you.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem", "marginBottom": "20px"}),
            _shoe_mileage_section(runs),
        ], alt_bg=True),

        # Stroller Comparison
        page_section("STROLLER IMPACT", [
            html.P("How much does the double stroller actually slow you down?",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem", "marginBottom": "20px"}),
            _stroller_comparison_section(runs),
        ]),

        # Run Log
        page_section("RUN LOG", [
            html.P(f"{total_runs} runs, most recent first. Click a chart point to jump here.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                          "marginBottom": "20px"}),
            html.Div(run_cards[:25], id="visible-run-cards"),
            html.Div(run_cards[25:], id="hidden-run-cards",
                      style={"display": "none"}) if len(run_cards) > 25 else html.Div(id="hidden-run-cards", style={"display": "none"}),
            html.Button(
                f"Show All Runs ({len(run_cards) - 25} more)",
                id="show-all-runs-btn",
                n_clicks=0,
                style={
                    "display": "block" if len(run_cards) > 25 else "none",
                    "margin": "20px auto",
                    "padding": "10px 24px",
                    "fontSize": "14px",
                    "fontWeight": "600",
                    "color": TEXT_PRIMARY,
                    "backgroundColor": BG_CARD,
                    "border": f"1px solid {BORDER}",
                    "cursor": "pointer",
                },
            ),
        ]),

        # CTA
        cta_section(
            "Want to see where this fitness takes you?",
            "Race predictions powered by your actual training data.",
            "Race Predictions \u2192", "/races",
        ),

        # Footer
        footer(),
    ])


def _adjusted_hr_section(runs: pd.DataFrame) -> html.Div:
    if "adjusted_hr" not in runs.columns or "hr_adjustment" not in runs.columns:
        return html.P("No HR adjustment data.",
                       style={"color": TEXT_SECONDARY})

    adjusted = runs[runs["hr_adjustment"] > 0]
    if adjusted.empty:
        return html.P("No runs with HR adjustments (heat/stroller).",
                       style={"color": TEXT_SECONDARY})

    avg_adj = adjusted["hr_adjustment"].mean()
    kid_runs = (adjusted[adjusted.get("with_kid", False)]
                if "with_kid" in adjusted.columns else pd.DataFrame())

    items = [
        html.P(f"Avg HR adjustment: -{avg_adj:.1f} bpm across {len(adjusted)} runs",
               style={"color": TEXT_SECONDARY, "fontSize": "0.9rem"}),
    ]
    if not kid_runs.empty:
        items.append(html.P(
            f"Stroller/kid runs: {len(kid_runs)} "
            f"(avg -{kid_runs['hr_adjustment'].mean():.1f} bpm)",
            style={"color": TEXT_SECONDARY, "fontSize": "0.9rem"},
        ))

    return html.Div(items)


@callback(
    Output("pace-trend", "figure"),
    Output("weekly-miles", "figure"),
    Output("hr-vs-pace", "figure"),
    Output("est-5k", "figure"),
    Input("run-type-filter", "value"),
    Input("run-date-range", "start_date"),
    Input("run-date-range", "end_date"),
)
def update_charts(run_types, start_date, end_date):
    runs = data.get_runs().copy()

    if run_types:
        runs = runs[runs["run_type"].isin(run_types)]
    if start_date:
        runs = runs[runs["date"] >= start_date]
    if end_date:
        runs = runs[runs["date"] <= end_date]

    pace_fig = charts.pace_trend_chart(runs)
    pace_fig.update_layout(clickmode="event+select")
    # Suppress native Plotly tooltip — custom hover card provides the info
    pace_fig.update_traces(hovertemplate=None, hoverinfo="none")

    hr_fig = charts.hr_vs_pace_chart(runs)
    hr_fig.update_layout(clickmode="event+select")

    est5k_fig = charts.est_5k_chart(runs)
    est5k_fig.update_layout(clickmode="event+select")

    return (
        pace_fig,
        charts.weekly_mileage_chart(runs),
        hr_fig,
        est5k_fig,
    )


def _build_route_charts(filename):
    """Build route map + stream charts for a run. Called by individual route callbacks."""
    if filename in _route_cache:
        return _route_cache[filename]

    from strava_analytics.routes import parse_activity

    export_dir = data.get_export_dir()
    stream = parse_activity(export_dir / filename)
    children = []

    map_config = {"displaylogo": False, "scrollZoom": True,
                  "modeBarButtonsToRemove": ["select2d", "lasso2d", "toImage"]}
    sm_config = {"displaylogo": False, "scrollZoom": True,
                 "modeBarButtonsToRemove": ["select2d", "lasso2d", "toImage",
                                             "autoScale2d", "zoom2d", "zoomIn2d", "zoomOut2d"]}

    if stream.coords:
        lats = [c[0] for c in stream.coords]
        lons = [c[1] for c in stream.coords]
        center_lat = (min(lats) + max(lats)) / 2
        center_lon = (min(lons) + max(lons)) / 2
        extent = max(max(lats) - min(lats), max(lons) - min(lons))
        zoom = 15 if extent < 0.005 else 14 if extent < 0.02 else 13 if extent < 0.05 else 12 if extent < 0.1 else 11 if extent < 0.3 else 10

        map_fig = go.Figure(go.Scattermapbox(
            lat=lats, lon=lons, mode="lines",
            line=dict(width=3, color=ACCENT), hoverinfo="skip",
        ))
        map_fig.update_layout(
            mapbox=dict(style="carto-positron",
                        center=dict(lat=center_lat, lon=center_lon), zoom=zoom),
            margin=dict(l=0, r=0, t=0, b=0),
            height=300, paper_bgcolor="rgba(0,0,0,0)", showlegend=False, dragmode="pan",
        )
        children.append(dcc.Graph(figure=map_fig, config=map_config))

    dist_mi = [d / 1609.344 for d in stream.distance_m] if stream.distance_m else []
    x_title = "Distance (mi)" if dist_mi else ""
    _cl = dict(height=180, margin=dict(l=45, r=10, t=30, b=30),
               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis_title=x_title)

    if stream.heart_rate and len(stream.heart_rate) > 5:
        hr = [h for h in stream.heart_rate if h > 0]
        hr_x = dist_mi[:len(stream.heart_rate)] if dist_mi else list(range(len(stream.heart_rate)))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hr_x, y=[min(hr)-10]*len(hr_x), mode="lines",
                                  line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=hr_x, y=stream.heart_rate, mode="lines",
                                  line=dict(color=ACCENT_RED, width=1.5),
                                  fill="tonexty", fillcolor="rgba(220,38,38,0.1)",
                                  hovertemplate="%{y} bpm<extra></extra>", showlegend=False))
        fig.update_layout(title=dict(text="Heart Rate", font=dict(size=12)),
                          yaxis=dict(title="bpm", range=[min(hr)-10, max(hr)+10]),
                          showlegend=False, **_cl)
        children.append(dcc.Graph(figure=fig, config=sm_config))

    if stream.speed_ms and len(stream.speed_ms) > 5:
        pv = [26.8224/s if s > 0.5 else None for s in stream.speed_ms]
        px = dist_mi[:len(pv)] if dist_mi else list(range(len(pv)))
        vp = [p for p in pv if p and p < 20]
        if vp:
            fig = go.Figure(go.Scatter(x=px, y=pv, mode="lines",
                                        line=dict(color=ACCENT_TEAL, width=1.5),
                                        hovertemplate="%{y:.1f} min/mi<extra></extra>",
                                        connectgaps=False))
            fig.update_layout(title=dict(text="Pace", font=dict(size=12)),
                              yaxis=dict(title="min/mi", range=[min(max(vp)+0.5,18), min(vp)-0.5]),
                              showlegend=False, **_cl)
            children.append(dcc.Graph(figure=fig, config=sm_config))

    if stream.altitude_m and len(stream.altitude_m) > 5:
        ef = [a * 3.28084 for a in stream.altitude_m]
        ex = dist_mi[:len(ef)] if dist_mi else list(range(len(ef)))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=ex, y=[min(ef)-20]*len(ex), mode="lines",
                                  line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=ex, y=ef, mode="lines",
                                  line=dict(color=ACCENT_GREEN, width=1.5),
                                  fill="tonexty", fillcolor="rgba(22,163,74,0.1)",
                                  hovertemplate="%{y:.0f} ft<extra></extra>", showlegend=False))
        fig.update_layout(title=dict(text="Elevation", font=dict(size=12)),
                          yaxis=dict(title="ft", range=[min(ef)-20, max(ef)+20]),
                          showlegend=False, **_cl)
        children.append(dcc.Graph(figure=fig, config=sm_config))

    # Splits bar chart
    from strava_analytics.routes import compute_splits
    splits = compute_splits(stream)
    if splits:
        split_labels = [f"Mi {s['split_num']}" if s['distance_mi'] > 0.9
                        else f"{s['distance_mi']:.1f}" for s in splits]
        split_paces = [s["pace_min_per_mi"] for s in splits]

        # Color by pace: faster = green, slower = red
        avg_pace = sum(split_paces) / len(split_paces) if split_paces else 10
        colors = [ACCENT_GREEN if p <= avg_pace else ACCENT_RED for p in split_paces]

        # Format pace for hover
        pace_strs = [f"{int(p)}:{int((p % 1) * 60):02d}" for p in split_paces]

        fig = go.Figure(go.Bar(
            x=split_labels, y=split_paces,
            marker_color=colors,
            hovertemplate="%{x}: %{customdata} /mi<extra></extra>",
            customdata=pace_strs,
        ))
        fig.update_layout(
            title=dict(text="Mile Splits", font=dict(size=12)),
            yaxis=dict(title="Pace (min/mi)", autorange="reversed"),
            showlegend=False,
            height=200,
            margin=dict(l=45, r=10, t=30, b=30),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        children.append(dcc.Graph(figure=fig, config=sm_config))

    result = children if children else [html.P("No GPS data.", style={"color": TEXT_MUTED})]
    _route_cache[filename] = result
    return result


@callback(
    Output({"type": "route-container", "index": MATCH}, "children"),
    Input({"type": "route-btn", "index": MATCH}, "n_clicks"),
    State({"type": "route-btn", "index": MATCH}, "id"),
    State("run-filenames-store", "data"),
    prevent_initial_call=True,
)
def load_route(n_clicks, btn_id, filenames):
    if not n_clicks:
        return no_update
    key = btn_id["index"]
    filename = filenames.get(key, "")
    if not filename:
        return html.P("No GPS data for this run.", style={"color": "#a8a29e"})
    return _build_route_charts(filename)


def _scroll_to_card_js(customdata_index: int) -> str:
    """Generate JS that scrolls to the run card matching the clicked chart point."""
    return f"""
    function(clickData) {{
        if (!clickData || !clickData.points || !clickData.points[0]) return "";
        var pt = clickData.points[0];
        var dateStr = pt.customdata ? pt.customdata[{customdata_index}] : null;
        if (!dateStr) return "";
        var hoverCard = document.getElementById("run-hover-card");
        if (hoverCard) hoverCard.style.display = "none";
        var cards = document.querySelectorAll('details[id^="run-card-' + dateStr + '"]');
        if (cards.length > 0) {{
            var card = cards[0];
            card.open = true;
            card.scrollIntoView({{behavior: "smooth", block: "center"}});
            card.style.transition = "box-shadow 0.3s";
            card.style.boxShadow = "0 0 0 3px #ef3c4a";
            setTimeout(function() {{ card.style.boxShadow = ""; }}, 2500);
        }}
        return dateStr;
    }}
    """


# Click-to-scroll: pace-trend (date_str at customdata[3])
clientside_callback(
    _scroll_to_card_js(3),
    Output("scroll-target", "children"),
    Input("pace-trend", "clickData"),
    prevent_initial_call=True,
)

# Click-to-scroll: hr-vs-pace (date_str at customdata[2])
clientside_callback(
    _scroll_to_card_js(2),
    Output("hr-scroll-target", "children"),
    Input("hr-vs-pace", "clickData"),
    prevent_initial_call=True,
)

# Click-to-scroll: est-5k (date_str at customdata[3])
clientside_callback(
    _scroll_to_card_js(3),
    Output("est5k-scroll-target", "children"),
    Input("est-5k", "clickData"),
    prevent_initial_call=True,
)


# Clientside callback: hover on pace-trend → show mini route preview card
clientside_callback(
    """
    function(hoverData, runMeta) {
        var card = document.getElementById("run-hover-card");
        if (!card) return "";
        if (!hoverData || !hoverData.points || !hoverData.points[0]) {
            card.style.display = "none";
            return "";
        }
        var pt = hoverData.points[0];
        var dateStr = pt.customdata ? pt.customdata[3] : null;
        if (!dateStr || !runMeta || !runMeta[dateStr]) {
            card.style.display = "none";
            return "";
        }

        var info = runMeta[dateStr];

        var typeColor = {"race":"#ef3c4a","workout":"#0891b2","long":"#9333ea","moderate":"#ca8a04","easy":"#16a34a","short/easy":"#0284c7"};
        var tc = typeColor[info.type] || "#a8a29e";
        var badge = info.type ? '<span style="background:' + tc + ';color:#fff;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;padding:1px 6px;margin-left:6px">' + info.type + '</span>' : '';

        card.innerHTML =
            '<div style="font-weight:600;font-size:13px;color:#0c0a09">' + info.name + badge + '</div>' +
            '<div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:6px 16px">' +
                '<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.1em;color:#a8a29e">Distance</div><div style="font-family:IBM Plex Mono,monospace;font-size:14px;font-weight:600;color:#0c0a09">' + info.dist + '</div></div>' +
                '<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.1em;color:#a8a29e">Pace</div><div style="font-family:IBM Plex Mono,monospace;font-size:14px;font-weight:600;color:#0c0a09">' + info.pace + '/mi</div></div>' +
                '<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.1em;color:#a8a29e">Duration</div><div style="font-family:IBM Plex Mono,monospace;font-size:14px;font-weight:600;color:#0c0a09">' + info.duration + '</div></div>' +
                (info.hr ? '<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.1em;color:#a8a29e">Avg HR</div><div style="font-family:IBM Plex Mono,monospace;font-size:14px;font-weight:600;color:#0c0a09">' + info.hr + '</div></div>' : '') +
            '</div>' +
            '<div style="margin-top:8px;font-size:11px;color:#a8a29e">Click to view details \u2193</div>';

        card.style.display = "block";
        return dateStr;
    }
    """,
    Output("hover-target", "children"),
    Input("pace-trend", "hoverData"),
    State("run-meta-store", "data"),
    prevent_initial_call=True,
)


# Show all runs: unhide hidden cards and hide the button
clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        return [{"display": "block"}, {"display": "none"}];
    }
    """,
    Output("hidden-run-cards", "style"),
    Output("show-all-runs-btn", "style"),
    Input("show-all-runs-btn", "n_clicks"),
    prevent_initial_call=True,
)
