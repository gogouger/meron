"""Running analytics page — ozniai.com subpage pattern."""

import json

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, clientside_callback, Output, Input, State, ALL, MATCH, ctx, no_update
import pandas as pd

from strava_analytics.web import data
from strava_analytics.web.components import charts
from strava_analytics.web.components.cards import stat_cell as _stat_cell
from strava_analytics.web.components.layout import (
    hero_section, page_section, feature_grid, numbered_card,
    cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, ACCENT_RED,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BG_CARD, BG_SURFACE, BORDER, RUN_TYPE_COLORS, FONT_MONO,
)
from strava_analytics.metrics import format_pace
from strava_analytics.critical_speed import fit_critical_speed, predict_race_times, cs_to_vdot

dash.register_page(__name__, path="/running", name="Running")


# Colors for run type badges
_TYPE_COLORS = {
    "race": ACCENT, "long": ACCENT_SLATE,
    "moderate": ACCENT_AMBER, "easy": ACCENT_SLATE,
}


def _duration_str(seconds):
    if pd.isna(seconds) or seconds <= 0:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


_route_cache = {}  # filename -> children; bounded to 32 entries
_ROUTE_CACHE_MAX = 32



def _run_card(run, idx):
    """Build a single expandable run card using HTML <details> (no Dash callbacks)."""
    run_type = run.get("run_type", "")
    type_color = _TYPE_COLORS.get(run_type, TEXT_MUTED)
    date_str = run["date"].strftime("%b %d, %Y")
    day_str = run["date"].strftime("%A")
    name = run.get("name", "Run")
    dist = run.get("distance_mi", 0)
    pace = format_pace(run.get("pace_min_per_mi"))
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
    rel_effort = run.get("relative_effort", None)
    if rel_effort and not pd.isna(rel_effort):
        primary_stats.append(_stat_cell("Effort", f"{rel_effort:.0f}"))
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
            "",
            id={"type": "route-btn", "index": route_key},
            n_clicks=0,
            style={"display": "none"},  # hidden — auto-triggered on card open
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


def _stroller_comparison_section(runs: pd.DataFrame) -> html.Div:
    """Side-by-side comparison of stroller vs non-stroller runs."""
    if "with_kid" not in runs.columns:
        return html.Div()

    stroller = runs[runs["with_kid"] == True].copy()
    normal = runs[runs["with_kid"] == False].copy()

    if stroller.empty or len(stroller) < 3:
        return html.P("Not enough stroller runs for comparison.",
                      style={"color": TEXT_MUTED})

    # Filter to valid pace range
    stroller = stroller[stroller["pace_min_per_mi"].between(6, 15)]
    normal = normal[normal["pace_min_per_mi"].between(6, 15)]

    # Core averages
    avg_solo_pace = normal["pace_min_per_mi"].mean()
    avg_str_pace = stroller["pace_min_per_mi"].mean()
    pace_overhead = avg_str_pace - avg_solo_pace

    best_solo = normal["pace_min_per_mi"].min()
    best_stroller = stroller["pace_min_per_mi"].min()

    # HR comparison (effort at same exertion — use adjusted HR if available)
    hr_col = "adjusted_hr" if "adjusted_hr" in stroller.columns else "avg_hr"
    has_hr = (stroller[hr_col].notna().any() and normal[hr_col].notna().any())
    avg_solo_hr = normal[hr_col].mean() if has_hr else None
    avg_str_hr = stroller[hr_col].mean() if has_hr else None

    # Effort-adjusted pace: what pace would stroller runs be at solo HR?
    # If stroller HR is higher, you're working harder to run the same pace.
    effort_note = None
    if has_hr and avg_solo_hr and avg_str_hr and avg_str_hr > 0:
        # Pace at equivalent HR = stroller_pace × (solo_hr / stroller_hr)
        effort_adj = avg_str_pace * (avg_solo_hr / avg_str_hr)
        effort_delta = effort_adj - avg_solo_pace
        sign = "+" if effort_delta > 0 else ""
        effort_note = f"At equivalent effort: {format_pace(effort_adj)} ({sign}{effort_delta:.1f} min/mi vs solo)"

    def _stat(label, value, sub=None, color=None):
        return html.Div([
            html.Div(label, style={
                "fontSize": "10px", "textTransform": "uppercase",
                "letterSpacing": "0.1em", "color": TEXT_MUTED, "marginBottom": "4px",
            }),
            html.Div(value, style={
                "fontFamily": FONT_MONO, "fontSize": "20px",
                "fontWeight": "600", "color": color or TEXT_PRIMARY,
            }),
            *([] if sub is None else [html.Div(sub, style={
                "fontSize": "11px", "color": TEXT_MUTED, "marginTop": "2px",
            })]),
        ], style={"padding": "12px 16px", "backgroundColor": BG_CARD,
                  "border": f"1px solid {BORDER}"})

    pace_color = ACCENT_RED if pace_overhead > 0.5 else ACCENT_AMBER if pace_overhead > 0 else ACCENT_SLATE
    sign = "+" if pace_overhead > 0 else ""

    stat_grid = html.Div([
        _stat("Avg Solo Pace", format_pace(avg_solo_pace), f"best: {format_pace(best_solo)}"),
        _stat("Avg Stroller Pace", format_pace(avg_str_pace), f"best: {format_pace(best_stroller)}"),
        _stat("Pace Overhead", f"{sign}{pace_overhead:.1f} min/mi",
              "stroller vs solo", color=pace_color),
        *([_stat("Avg HR (adjusted)", f"{avg_str_hr:.0f} bpm",
                 f"solo: {avg_solo_hr:.0f} bpm (+{avg_str_hr - avg_solo_hr:.0f})"
                 if avg_str_hr > avg_solo_hr else f"solo: {avg_solo_hr:.0f} bpm")]
          if has_hr else []),
    ], style={
        "display": "grid",
        "gridTemplateColumns": f"repeat({'4' if has_hr else '3'}, 1fr)",
        "gap": "12px", "marginBottom": "16px",
    })

    note_row = html.Div([
        html.Span(f"{len(stroller)} stroller runs vs {len(normal)} solo runs", style={
            "color": TEXT_MUTED, "fontSize": "12px",
        }),
        *([] if not effort_note else [
            html.Span(" · ", style={"color": TEXT_MUTED, "fontSize": "12px"}),
            html.Span(effort_note, style={"color": TEXT_SECONDARY, "fontSize": "12px"}),
        ]),
    ], style={"marginBottom": "20px"})

    return html.Div([
        note_row,
        stat_grid,
        html.Div(
            charts.stroller_pace_chart(runs, chart_id="stroller-pace"),
            style={"marginTop": "8px"},
        ),
    ])


def _heat_pace_section(runs: pd.DataFrame) -> html.Div:
    """Temperature impact on running pace."""
    if "weather_temp_f" not in runs.columns:
        return html.Div()

    df = runs[runs["weather_temp_f"].notna()
              & runs["pace_min_per_mi"].between(6, 15)].copy()
    if len(df) < 10:
        return html.P("Not enough runs with temperature data.",
                       style={"color": TEXT_MUTED})

    # Temperature buckets
    buckets = [
        ("<45\u00b0F", df[df["weather_temp_f"] < 45]),
        ("45-60\u00b0F", df[df["weather_temp_f"].between(45, 60)]),
        ("60-75\u00b0F", df[df["weather_temp_f"].between(60, 75)]),
        ("75-90\u00b0F", df[df["weather_temp_f"].between(75, 90)]),
        (">90\u00b0F", df[df["weather_temp_f"] > 90]),
    ]

    bucket_cards = []
    for label, subset in buckets:
        if subset.empty:
            continue
        avg_pace = format_pace(subset["pace_min_per_mi"].mean())
        bucket_cards.append(_stat_cell(label, f"{avg_pace} /mi"))

    # Heat cost estimate
    hot = df[df["weather_temp_f"] > 60]
    heat_cost_text = ""
    if len(hot) > 10:
        import numpy as np
        coeffs = np.polyfit(hot["weather_temp_f"], hot["pace_min_per_mi"], 1)
        cost_per_10 = coeffs[0] * 10
        if cost_per_10 > 0:
            secs = cost_per_10 * 60
            heat_cost_text = f"+{secs:.0f} sec/mi per 10\u00b0F above 60\u00b0F"

    children = []
    if bucket_cards:
        children.append(html.Div(bucket_cards, style={
            "display": "flex", "gap": "24px", "flexWrap": "wrap",
            "marginBottom": "20px",
        }))
    if heat_cost_text:
        children.append(html.P(heat_cost_text, style={
            "color": TEXT_SECONDARY, "fontSize": "0.9rem",
            "fontFamily": FONT_MONO,
            "marginBottom": "16px",
        }))
    children.append(charts.heat_vs_pace_chart(runs, chart_id="heat-pace"))

    return html.Div(children)


def _format_race_time(seconds: float) -> str:
    """Format race time as H:MM:SS or M:SS."""
    if seconds <= 0:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _race_predictions_section(runs: pd.DataFrame) -> html.Div:
    """Build a Race Predictions section using the Critical Speed model."""
    best_efforts = data.get_best_efforts()
    if best_efforts is None or best_efforts.empty:
        return html.Div()

    # Compute weekly volume for Tanda marathon blend
    weekly_km = 0.0
    avg_pace_sec_per_km = 0.0
    if not runs.empty:
        recent = runs[runs["date"] >= runs["date"].max() - pd.Timedelta(weeks=8)]
        if not recent.empty:
            weeks = max((recent["date"].max() - recent["date"].min()).days / 7.0, 1.0)
            weekly_km = recent["distance_mi"].sum() * 1.60934 / weeks
            avg_pace_sec_per_km = recent["pace_min_per_mi"].mean() * 60 / 1.60934

    predictions = predict_race_times(best_efforts, weekly_km, avg_pace_sec_per_km)
    cs_params = predictions.pop("_cs_params", {})

    if cs_params.get("cs_m_per_s", 0) <= 0:
        return html.Div()

    cs_vdot = cs_to_vdot(cs_params["cs_m_per_s"])

    # Summary cards
    summary = feature_grid([
        numbered_card(1, "Critical Speed", f"R\u00b2={cs_params['r_squared']:.3f}",
                      value=f"{cs_params['cs_min_per_mi']:.1f} /mi", color=ACCENT),
        numbered_card(2, "VDOT", "from Critical Speed model",
                      value=f"{cs_vdot:.1f}", color=ACCENT_SLATE),
        numbered_card(3, "D\u2032", "anaerobic distance reserve",
                      value=f"{cs_params['d_prime_m']:.0f} m", color=ACCENT_AMBER),
        numbered_card(4, "Data Points", f"{cs_params['n_points']} best efforts",
                      value=str(cs_params["n_points"]), color=ACCENT_SLATE),
    ], columns=4)

    # Prediction table
    table_rows = []
    for dist_label in ["5K", "10K", "Half Marathon", "Marathon"]:
        pred = predictions.get(dist_label, {})
        time_s = pred.get("time_s", 0)
        pace = pred.get("pace_min_per_mi", 0)
        method = pred.get("method", "")
        confidence = pred.get("confidence", "")
        conf_color = ACCENT_SLATE if confidence == "high" else ACCENT_AMBER
        table_rows.append(html.Tr([
            html.Td(dist_label, style={"fontWeight": "600"}),
            html.Td(_format_race_time(time_s), style={"fontFamily": FONT_MONO}),
            html.Td(f"{format_pace(pace)} /mi" if pace else "--", style={
                "fontFamily": FONT_MONO, "color": "var(--text-secondary)",
            }),
            html.Td(method, style={"color": "var(--text-muted)", "fontSize": "12px"}),
            html.Td(confidence, style={"color": conf_color, "fontSize": "12px",
                                        "fontWeight": "600"}),
        ]))

    pred_table = html.Table([
        html.Thead(html.Tr([
            html.Th(h, style={
                "textAlign": "left", "padding": "8px 16px",
                "fontSize": "10px", "textTransform": "uppercase",
                "letterSpacing": "0.1em",
            }) for h in ["Distance", "Time", "Pace", "Method", "Confidence"]
        ])),
        html.Tbody(table_rows),
    ], className="table", style={
        "width": "100%", "borderCollapse": "collapse",
        "fontSize": "14px",
    })

    return page_section("RACE PREDICTIONS", [
        summary,
        html.Div(pred_table, style={"marginTop": "24px"}),
    ], alt_bg=True)


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
            "pace": format_pace(r.get("pace_min_per_mi")),
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
                              value=f"{avg_pace} /mi", color=ACCENT_SLATE),
                numbered_card(3, "Best 5K+ Pace", "runs over 3 miles",
                              value=f"{best_pace} /mi", color=ACCENT_SLATE),
                numbered_card(4, "Average HR", f"Max: {max_hr:.0f} bpm",
                              value=f"{avg_hr:.0f} bpm", color=ACCENT_RED),
            ], columns=4),
        ]),

        # Filters — compact inline bar
        html.Div([
            html.Div([
                html.Div([
                    html.Label("Run Type",
                               style={"fontSize": "11px", "color": TEXT_MUTED,
                                      "textTransform": "uppercase", "letterSpacing": "0.08em",
                                      "marginRight": "8px", "whiteSpace": "nowrap"}),
                    dcc.Dropdown(
                        id="run-type-filter",
                        options=[{"label": t, "value": t} for t in run_types],
                        multi=True,
                        placeholder="All types",
                        style={"minWidth": "180px"},
                    ),
                ], style={"display": "flex", "alignItems": "center", "gap": "4px"}),
                html.Div([
                    html.Label("Range",
                               style={"fontSize": "11px", "color": TEXT_MUTED,
                                      "textTransform": "uppercase", "letterSpacing": "0.08em",
                                      "marginRight": "8px"}),
                    html.Div([
                        html.Button("3M", id="range-3m", n_clicks=0,
                                    className="range-pill"),
                        html.Button("6M", id="range-6m", n_clicks=0,
                                    className="range-pill"),
                        html.Button("1Y", id="range-1y", n_clicks=0,
                                    className="range-pill"),
                        html.Button("ALL", id="range-all", n_clicks=1,
                                    className="range-pill range-pill-active"),
                    ], className="range-pill-bar"),
                    dcc.Store(id="run-time-range", data="all"),
                ], style={"display": "flex", "alignItems": "center", "gap": "4px"}),
            ], style={
                "display": "flex", "gap": "24px", "alignItems": "center",
                "flexWrap": "wrap",
            }),
        ], style={
            "backgroundColor": BG_SURFACE, "border": f"1px solid {BORDER}",
            "padding": "12px 24px", "margin": "0 auto",
            "maxWidth": "1200px",
        }),

        # Run metadata for hover tooltips
        dcc.Store(id="run-meta-store", data=run_meta),
        # Filenames for lazy route loading
        dcc.Store(id="run-filenames-store", data=filenames_dict),

        # Pace Trend (hover = preview, click = scroll to run card)
        page_section("PACE TREND", [
            html.P("Hover for preview. Click to jump to that run.",
                   style={"color": TEXT_MUTED, "fontSize": "12px",
                          "marginBottom": "8px"}),
            html.Div(id="pace-trend-container"),
            # Floating hover tooltip — follows mouse
            html.Div(id="run-hover-card", style={
                "display": "none",
                "position": "fixed",
                "zIndex": "1000",
                "backgroundColor": "var(--bg-card)",
                "border": f"1px solid {BORDER}",
                "boxShadow": "0 8px 24px rgba(0,0,0,0.12)",
                "padding": "12px",
                "width": "260px",
                "pointerEvents": "none",
            }),
        ]),

        # Race Predictions — Critical Speed model
        _race_predictions_section(runs),

        # Race chart (callback-driven, filter-aware)
        page_section("RACE FITNESS TREND", [
            html.Div(id="race-pred-container"),
        ], alt_bg=True),

        # Volume & Heart Rate
        page_section("VOLUME & EFFICIENCY", [
            dbc.Row([
                dbc.Col(html.Div(id="weekly-miles-container"), md=6),
                dbc.Col(html.Div(id="hr-vs-pace-container"), md=6),
            ]),
        ]),

        # Training Load (intensity-weighted)
        page_section("TRAINING LOAD", [
            html.P("Weekly load accounts for intensity, not just mileage.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                          "marginBottom": "16px"}),
            html.Div(id="weekly-load-container"),
        ], alt_bg=True),

        # HR Analysis
        page_section("HEART RATE ANALYSIS", [
            html.Div(id="hr-analysis-container"),
        ], alt_bg=True),


        # Stroller Comparison
        page_section("STROLLER IMPACT", [
            html.P("How much does the double stroller actually slow you down?",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem", "marginBottom": "20px"}),
            _stroller_comparison_section(runs),
        ]),

        # Heat & Pace
        page_section("HEAT & PACE", [
            html.P("How temperature affects your running pace.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem", "marginBottom": "20px"}),
            _heat_pace_section(runs),
        ], alt_bg=True),

        # Route Heatmap
        _heatmap_section(runs),

        # CTA
        cta_section(
            "Want to see every run?",
            "All activities in one place.",
            "View Activities \u2192", "/activities",
        ),

        # Floating "jump back" button (legacy, kept for calendar click)
        html.Button(
            "\u2191 Back to chart",
            id="jump-back-btn",
            n_clicks=0,
            style={"display": "none"},
        ),

        # Footer
        footer(),
    ])


def _heatmap_section(runs: pd.DataFrame) -> html.Div:
    """Route heatmap — all run GPS data overlaid on one map."""
    import json
    from pathlib import Path

    export_dir = data.get_export_dir()
    if export_dir is None:
        return html.Div()

    index_path = Path(export_dir) / "route_index.json"
    if not index_path.exists():
        return html.Div()

    try:
        raw = json.loads(index_path.read_text())
        fps = raw.get("fingerprints", {})
    except Exception:
        return html.Div()

    if not fps:
        return html.Div()

    # Aggregate all GPS points from fingerprints
    # Each point gets intensity 1.0 — overlapping points accumulate density
    heat_data = []
    for fn, fp in fps.items():
        pts = fp.get("points", [])
        for lat, lon in pts:
            heat_data.append([lat, lon, 0.5])

    if len(heat_data) < 10:
        return html.Div()

    map_cfg = json.dumps({
        "heatData": heat_data,
        "heatRadius": 6,
        "heatBlur": 10,
        "heatMaxZoom": 16,
        "height": 400,
    })

    map_id = "run-heatmap"

    return page_section("ROUTE HEATMAP", [
        html.P(f"{len(fps)} routes overlaid. Brighter = more frequently run.",
               style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                      "marginBottom": "12px"}),
        html.Div(
            html.Div(id=f"{map_id}-map", className="leaflet-map-box"),
            className="leaflet-map-wrap",
            style={
                "width": "100%", "borderRadius": "8px", "overflow": "hidden",
                "border": f"1px solid {BORDER}",
            },
            **{"data-mapcfg": map_cfg, "data-mapid": f"{map_id}-map"},
        ),
    ], alt_bg=True)


def _adjusted_hr_section(runs: pd.DataFrame) -> html.Div:
    if "adjusted_hr" not in runs.columns or "hr_adjustment" not in runs.columns:
        return html.P("No HR adjustment data.",
                       style={"color": TEXT_SECONDARY})

    hr_runs = runs[runs["adjusted_hr"].notna()]
    if hr_runs.empty:
        return html.P("No runs with HR data.",
                       style={"color": TEXT_SECONDARY})

    # Summary metrics
    adjusted = runs[runs["hr_adjustment"] > 0]
    avg_adj = adjusted["hr_adjustment"].mean() if not adjusted.empty else 0
    kid_runs = (adjusted[adjusted["with_kid"] == True]
                if "with_kid" in adjusted.columns else pd.DataFrame())

    zone_runs = hr_runs[hr_runs["hr_zone"].notna()] if "hr_zone" in hr_runs.columns else pd.DataFrame()
    most_common_zone = ""
    pct_easy = 0
    pct_hard = 0
    if not zone_runs.empty:
        zone_counts = zone_runs["hr_zone"].value_counts()
        top_zone = int(zone_counts.idxmax())
        zone_names = {1: "Recovery", 2: "Easy", 3: "Moderate", 4: "Threshold", 5: "Max"}
        most_common_zone = f"Z{top_zone} {zone_names.get(top_zone, '')}"
        total_z = len(zone_runs)
        pct_easy = round((zone_counts.get(1, 0) + zone_counts.get(2, 0)) / total_z * 100)
        pct_hard = round((zone_counts.get(4, 0) + zone_counts.get(5, 0)) / total_z * 100)

    metrics_row = html.Div([
        _stat_cell("Avg HR Adjustment",
                   f"-{avg_adj:.1f} bpm" if avg_adj > 0 else "None"),
        _stat_cell("Most Common Zone", most_common_zone or "--"),
        _stat_cell("Easy (Z1-Z2)", f"{pct_easy}%"),
        _stat_cell("Hard (Z4-Z5)", f"{pct_hard}%"),
    ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap",
              "marginBottom": "20px"})

    text_items = []
    if not adjusted.empty:
        text_items.append(html.P(
            f"{len(adjusted)} runs adjusted for heat/stroller conditions.",
            style={"color": TEXT_MUTED, "fontSize": "0.85rem"}))
    if not kid_runs.empty:
        text_items.append(html.P(
            f"{len(kid_runs)} stroller runs (avg -{kid_runs['hr_adjustment'].mean():.1f} bpm adjustment).",
            style={"color": TEXT_MUTED, "fontSize": "0.85rem"}))

    chart_row = dbc.Row([
        dbc.Col(charts.hr_zone_distribution_chart(hr_runs, chart_id="hr-zones"), md=5),
        dbc.Col(charts.hr_over_time_chart(hr_runs, chart_id="hr-trend"), md=7),
    ])

    return html.Div([metrics_row, *text_items, chart_row])


# Clientside callback: pill buttons → update run-time-range store + highlight
clientside_callback(
    """
    function(n3m, n6m, n1y, nall) {
        const ctx = dash_clientside.callback_context;
        if (!ctx.triggered.length) return dash_clientside.no_update;
        const btn = ctx.triggered[0].prop_id.split(".")[0];
        const map = {"range-3m": "3m", "range-6m": "6m", "range-1y": "1y", "range-all": "all"};
        const val = map[btn] || "all";
        // Highlight active pill
        var pills = document.querySelectorAll(".range-pill");
        pills.forEach(function(p) {
            if (p.id === btn) {
                p.classList.add("range-pill-active");
            } else {
                p.classList.remove("range-pill-active");
            }
        });
        return val;
    }
    """,
    Output("run-time-range", "data"),
    Input("range-3m", "n_clicks"),
    Input("range-6m", "n_clicks"),
    Input("range-1y", "n_clicks"),
    Input("range-all", "n_clicks"),
)


@callback(
    Output("pace-trend-container", "children"),
    Output("weekly-miles-container", "children"),
    Output("hr-vs-pace-container", "children"),
    Output("race-pred-container", "children"),
    Output("hr-analysis-container", "children"),
    Output("weekly-load-container", "children"),
    Input("run-type-filter", "value"),
    Input("run-time-range", "data"),
    Input("data-version-store", "data"),
    State("run-meta-store", "data"),
)
def update_charts(run_types, time_range, _data_version, run_meta):
    runs = data.get_runs().copy()

    if run_types:
        runs = runs[runs["run_type"].isin(run_types)]

    # Apply time range filter
    if time_range and time_range != "all":
        now = runs["date"].max()
        days = {"3m": 90, "6m": 180, "1y": 365}.get(time_range, 9999)
        cutoff = now - pd.Timedelta(days=days)
        runs = runs[runs["date"] >= cutoff]

    # Charts return html.Div with inline Chart.js rendering script
    pace_chart = charts.pace_trend_chart(runs, chart_id="pace-trend", run_meta=run_meta)
    return (
        pace_chart,
        charts.weekly_mileage_chart(runs, chart_id="weekly-miles"),
        charts.aerobic_efficiency_chart(runs, chart_id="hr-vs-pace", run_meta=run_meta),
        charts.race_predictions_chart(runs, chart_id="race-pred",
                                      best_efforts=data.get_best_efforts()),
        _adjusted_hr_section(runs),
        charts.weekly_training_load_chart(runs, chart_id="weekly-load"),
    )


def _smooth(vals, window=7):
    """Rolling average for smoothing noisy stream data."""
    arr = pd.Series(vals)
    return arr.rolling(window, min_periods=1, center=True).mean().tolist()


def _gap_factor(grade_pct: float) -> float:
    """Minetti cost factor for grade-adjusted pace. Shared by splits table and chart."""
    f = 1.0 + grade_pct * 0.033 if grade_pct > 0 else 1.0 + grade_pct * 0.017
    return max(0.7, min(1.8, f))


def _compute_gap(speed_ms, altitude_m, distance_m):
    """Grade-adjusted pace from speed, altitude, and distance streams."""
    if not speed_ms or not altitude_m or not distance_m or len(speed_ms) < 3:
        return []
    gap = []
    for i in range(len(speed_ms)):
        s = speed_ms[i]
        if s is None or s <= 0.3:
            gap.append(None)
            continue
        if i > 0 and i < len(altitude_m) and i < len(distance_m):
            d_elev = altitude_m[min(i, len(altitude_m)-1)] - altitude_m[max(i-1, 0)]
            d_dist = distance_m[min(i, len(distance_m)-1)] - distance_m[max(i-1, 0)]
            grade = d_elev / d_dist if d_dist > 1 else 0
        else:
            grade = 0
        adj = _gap_factor(grade * 100)
        gap_speed = s * adj
        pace = 26.8224 / gap_speed if gap_speed > 0.3 else None
        gap.append(pace if pace and pace < 20 else None)
    return gap


def _build_route_charts(filename):
    """Delegate to shared route builder."""
    from strava_analytics.web.components.routes import build_route_charts
    return build_route_charts(filename, df=data.get_df())


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
        return html.P("No GPS data for this run.", style={"color": TEXT_MUTED})
    return _build_route_charts(filename)




