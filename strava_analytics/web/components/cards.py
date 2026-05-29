"""Reusable stat card components — MERON-themed."""

from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
import pandas as pd
from dash import html, dcc

from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, BG_CARD, BG_SURFACE, TEXT_PRIMARY,
    TEXT_SECONDARY, TEXT_MUTED, FONT_MONO, BORDER,
    ACTIVITY_TYPE_COLORS, LIFT_COLORS, RUN_TYPE_COLORS,
)
from strava_analytics.metrics import format_pace


def stat_card(title: str, value: str, subtitle: str = "",
              color: str = ACCENT) -> dbc.Card:
    """Create a KPI stat card with top border accent."""
    return dbc.Card(
        dbc.CardBody([
            html.P(title, className="stat-label"),
            html.H3(value, className="stat-value",
                     style={"color": color}),
            html.P(subtitle, className="stat-subtitle") if subtitle else None,
        ]),
        className="stat-card",
        style={"borderTop": f"2px solid {color}"},
    )


def stat_card_row(cards: list[dbc.Card]) -> dbc.Row:
    """Wrap stat cards in a responsive row."""
    n = len(cards)
    width = max(2, 12 // n)
    return dbc.Row(
        [dbc.Col(card, xs=6, md=width) for card in cards],
        className="g-3 mb-4",
    )


def container_card(title: str, children, accent_color: str = BORDER) -> html.Div:
    """Wrap content in a themed container — matches MERON card pattern."""
    return html.Div([
        html.Div(title, className="container-label"),
        html.Div(children, style={"padding": "0"}),
    ], className="container-card",
       style={"borderTop": f"1.5px solid {accent_color}"})


def metric_cell(label: str, value: str, delta: str = "",
                delta_color: str = ACCENT_SLATE) -> html.Div:
    """Single metric in a grid — label on top, monospace value below."""
    children = [
        html.Div(label, className="metric-label"),
        html.Div(value, className="metric-value"),
    ]
    if delta:
        children.append(html.Div(delta, className="metric-delta",
                                  style={"color": delta_color}))
    return html.Div(children, className="metric-cell")


def metric_grid(cells: list) -> html.Div:
    """Grid of metric cells."""
    return html.Div(cells, className="metric-grid")


# ── Shared activity card helpers ──────────────────────────────────────

def stat_cell(label: str, val: str) -> html.Div:
    """Small stat cell for activity card summaries (monospace value)."""
    return html.Div([
        html.Div(label, style={
            "fontSize": "10px", "fontWeight": "500",
            "textTransform": "uppercase", "letterSpacing": "0.1em",
            "color": "var(--text-muted)",
        }),
        html.Div(val, style={
            "fontFamily": "var(--font-mono)",
            "fontSize": "14px", "fontWeight": "600",
            "color": "var(--text-primary)",
        }),
    ], style={"minWidth": "80px"})


def duration_str(seconds) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    import pandas as _pd
    if _pd.isna(seconds) or seconds <= 0:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def activity_type_badge(type_name: str, color: str) -> html.Span:
    """Coloured pill badge for activity type / run type."""
    return html.Span(
        type_name or "activity",
        style={
            "backgroundColor": color, "color": "white",
            "fontSize": "10px", "fontWeight": "600",
            "textTransform": "uppercase", "letterSpacing": "0.05em",
            "padding": "2px 8px", "marginLeft": "8px",
            "display": "inline-block",
        },
    )


# ── Lift exercise SVG icons ──────────────────────────────────────────

_LIFT_ICONS = {
    "bench": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="24" x2="42" y2="24"/><rect x="10" y="18" width="4" height="12" rx="1"/><rect x="34" y="18" width="4" height="12" rx="1"/><circle cx="6" cy="24" r="3"/><circle cx="42" cy="24" r="3"/></svg>',
    "squat": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="8" y1="14" x2="40" y2="14"/><rect x="12" y="8" width="3" height="12" rx="1"/><rect x="33" y="8" width="3" height="12" rx="1"/><circle cx="8" cy="14" r="2.5"/><circle cx="40" cy="14" r="2.5"/><path d="M18 20 L18 30 Q18 36 24 38 Q30 36 30 30 L30 20"/></svg>',
    "deadlift": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="34" x2="42" y2="34"/><rect x="10" y="28" width="4" height="12" rx="1"/><rect x="34" y="28" width="4" height="12" rx="1"/><circle cx="6" cy="34" r="3"/><circle cx="42" cy="34" r="3"/><path d="M20 34 L20 18 M28 34 L28 18"/><line x1="18" y1="18" x2="30" y2="18"/></svg>',
    "ohp": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="8" y1="10" x2="40" y2="10"/><rect x="12" y="4" width="3" height="12" rx="1"/><rect x="33" y="4" width="3" height="12" rx="1"/><circle cx="8" cy="10" r="2.5"/><circle cx="40" cy="10" r="2.5"/><path d="M20 16 L20 34 M28 16 L28 34"/></svg>',
}

_GENERIC_ICON = (
    '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" '
    'stroke-width="2.5" stroke-linecap="round">'
    '<line x1="10" y1="24" x2="38" y2="24"/>'
    '<rect x="6" y="18" width="6" height="12" rx="1.5"/>'
    '<rect x="36" y="18" width="6" height="12" rx="1.5"/></svg>'
)

_NAME_TO_ICON = {
    "bench": "bench", "squat": "squat", "deadlift": "deadlift",
    "ohp": "ohp", "overhead": "ohp",
}


# ── Exercise parsing ─────────────────────────────────────────────────
# The canonical parser lives in ``lifting_program.parse_description`` so
# cards and enrichment share one implementation.
from strava_analytics.lifting_program import parse_description as _parse_exercises  # noqa: E402


def _exercise_cards(parsed_exercises: list[dict]) -> html.Div | None:
    """Build grid of exercise cards for a lifting session."""
    if not parsed_exercises:
        return None

    cards = []
    for ex in parsed_exercises:
        ex_name = ex["name"]
        n_sets, n_reps, wt = ex["sets"], ex["reps"], ex["weight"]
        scheme = f"{n_sets}\u00d7{n_reps}" if n_sets and n_reps else ""

        # Icon lookup
        icon_key = None
        for keyword, key in _NAME_TO_ICON.items():
            if keyword in ex_name.lower():
                icon_key = key
                break
        lift_color = LIFT_COLORS.get(icon_key, TEXT_MUTED)
        svg = _LIFT_ICONS.get(icon_key, _GENERIC_ICON)

        icon_div = html.Div(
            style={"width": "24px", "height": "24px",
                   "color": lift_color, "flexShrink": "0"},
            **{"data-svg-icon": svg},
        )

        # Rep ladder SVG
        rep_bars = None
        if n_sets > 0 and n_reps > 0:
            max_r = max(12, n_reps + 2)
            chart_h = 28
            axis_w = 14
            bar_w = 7
            bar_gap = 3
            bars_w = n_sets * (bar_w + bar_gap) - bar_gap
            total_w = axis_w + bars_w + 4

            grid_svg = ""
            for tick in [5, 10]:
                if tick > max_r:
                    continue
                y = chart_h - (tick / max_r * (chart_h - 2))
                grid_svg += (
                    f'<line x1="{axis_w}" y1="{y:.0f}" x2="{total_w}" y2="{y:.0f}" '
                    f'stroke="{TEXT_MUTED}" stroke-width="0.5" opacity="0.3"/>'
                    f'<text x="{axis_w - 2}" y="{y + 3:.0f}" font-size="7" '
                    f'fill="{TEXT_MUTED}" font-family="monospace" text-anchor="end">'
                    f'{tick}</text>'
                )
            bar_svg = ""
            for s in range(n_sets):
                bx = axis_w + s * (bar_w + bar_gap)
                bh = max(2, n_reps / max_r * (chart_h - 2))
                by = chart_h - bh
                bar_svg += (
                    f'<rect x="{bx}" y="{by:.1f}" width="{bar_w}" height="{bh:.1f}" '
                    f'rx="1.5" fill="{lift_color}" opacity="0.55"/>'
                )
            ladder_svg = (
                f'<svg viewBox="0 0 {total_w} {chart_h}" '
                f'xmlns="http://www.w3.org/2000/svg" '
                f'style="width:{total_w}px;height:{chart_h}px">'
                f'{grid_svg}{bar_svg}</svg>'
            )
            rep_bars = html.Div(
                style={"marginTop": "6px", "height": f"{chart_h}px"},
                **{"data-svg-icon": ladder_svg},
            )

        cards.append(html.Div([
            html.Div([
                icon_div,
                html.Div(ex_name, style={
                    "fontSize": "11px", "fontWeight": "600", "color": lift_color,
                }),
            ], style={"display": "flex", "gap": "6px", "alignItems": "center"}),
            html.Div([
                html.Span(f"{wt:.0f}", style={
                    "fontFamily": FONT_MONO, "fontSize": "16px", "fontWeight": "700",
                }) if wt else None,
                html.Span(f" {scheme}", style={
                    "fontFamily": FONT_MONO, "fontSize": "12px", "color": TEXT_SECONDARY,
                }) if scheme else None,
            ], style={"marginTop": "2px"}),
            rep_bars,
        ], style={
            "padding": "8px 10px",
            "backgroundColor": "var(--surface, #f5f5f4)",
            "border": f"1px solid {BORDER}",
            "borderRadius": "6px",
            "borderLeft": f"3px solid {lift_color}",
        }))

    return html.Div(cards, style={
        "display": "grid",
        "gridTemplateColumns": "repeat(auto-fill, minmax(140px, 1fr))",
        "gap": "6px", "marginTop": "10px",
    })


# ── Unified activity card body ───────────────────────────────────────

_card_uid = 0


def activity_card_body(
    row,
    *,
    show_detail: bool = True,
    route_mode: str = "lazy",
    card_id_prefix: str = "activity-card",
    idx: int = 0,
) -> dict:
    """Build activity card content from a DataFrame row.

    Returns dict with keys:
        header:  html.Div  — date, badges, name
        primary: list      — primary stat cells
        extra:   html.Div | None — exercise cards (lifts) or mini-map (runs)
        detail:  list      — expanded detail content
        color:   str       — accent color for border
        date_id: str       — YYYY-MM-DD for element IDs
    """
    global _card_uid

    act_type = row.get("type", "")
    color = ACTIVITY_TYPE_COLORS.get(act_type, TEXT_MUTED)
    name = row.get("name", act_type or "Activity")
    date_display = row["date"].strftime("%b %d, %Y")
    day_str = row["date"].strftime("%A")
    date_id = row["date"].strftime("%Y-%m-%d")

    # ── Badges ──
    badge = activity_type_badge(act_type, color)
    run_type = row.get("run_type", "")
    run_badge = None
    if act_type == "Run" and run_type:
        rt_color = RUN_TYPE_COLORS.get(run_type, TEXT_MUTED)
        run_badge = activity_type_badge(run_type, rt_color)

    header = html.Div([
        html.Div([
            html.Span(date_display, style={
                "fontWeight": "600", "fontSize": "14px", "color": TEXT_PRIMARY,
            }),
            html.Span(f" {day_str}", style={
                "color": TEXT_MUTED, "fontSize": "13px",
            }),
            badge,
            run_badge,
        ]),
        html.Div(name, style={
            "fontSize": "13px", "color": TEXT_SECONDARY, "marginTop": "2px",
        }),
    ], style={"marginBottom": "12px"})

    # ── Primary stats ──
    primary: list = []
    extra = None
    detail: list = []

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
        rel_effort = row.get("relative_effort", None)
        if rel_effort and not pd.isna(rel_effort):
            primary.append(stat_cell("Effort", f"{rel_effort:.0f}"))
        elev = row.get("elevation_gain_ft", 0) or 0
        if elev > 0:
            primary.append(stat_cell("Elevation", f"\u2191{elev:.0f} ft"))

        if show_detail:
            # Secondary stats
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
                detail.append(html.Div(secondary, style={
                    "display": "flex", "gap": "24px", "flexWrap": "wrap",
                    "marginTop": "12px", "paddingTop": "12px",
                    "borderTop": f"1px solid {BORDER}",
                }))

            desc = row.get("description", "")
            if desc and isinstance(desc, str) and desc.strip():
                detail.append(html.P(desc.strip(), style={
                    "color": TEXT_SECONDARY, "fontSize": "13px",
                    "marginTop": "12px", "fontStyle": "italic",
                }))

        # Route handling
        filename = row.get("filename", "")
        filename = str(filename) if filename and not pd.isna(filename) else ""
        source_id = row.get("_source_id") or row.get("source_id") or ""
        # API-synced activities have no filename but do have an encoded
        # polyline cached under ``strava:<source_id>`` in route_index.
        has_route = (
            (filename.endswith(".fit.gz")) or bool(source_id)
        )
        if has_route:
            if route_mode == "lazy":
                # Mini-map as card extra
                from strava_analytics.web.components.routes import _mini_map
                extra = _mini_map(filename, source_id=str(source_id) if source_id else None)
                # Lazy-load button + container
                route_key = f"{date_id}-{idx}"
                btn_type = f"{card_id_prefix}-route-btn" if card_id_prefix else "route-btn"
                ctr_type = f"{card_id_prefix}-route-container" if card_id_prefix else "route-container"
                detail.append(html.Button(
                    "", id={"type": btn_type, "index": route_key},
                    n_clicks=0, style={"display": "none"},
                ))
                detail.append(dcc.Loading(
                    html.Div(id={"type": ctr_type, "index": route_key}),
                    type="default",
                    className="meron-loading",
                    color="#1a8a77",
                ))
            elif route_mode == "eager" and act_type in ("Run", "Walk", "Hike", "Ride"):
                from strava_analytics.web.components.routes import build_route_charts
                from strava_analytics.web import data as _data
                route_el = build_route_charts(filename, df=_data.get_df())
                if route_el:
                    detail.append(html.Div(route_el, style={
                        "marginTop": "16px", "borderTop": f"1px solid {BORDER}",
                        "paddingTop": "12px",
                    }))

    elif act_type == "Weight Training":
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))
        hr = row.get("avg_hr", 0)
        if hr and not pd.isna(hr):
            primary.append(stat_cell("Avg HR", f"{hr:.0f} bpm"))
        cals = row.get("calories", 0)
        if cals and not pd.isna(cals) and cals > 0:
            primary.append(stat_cell("Calories", f"{cals:.0f}"))

        # Parse exercises and build cards
        parsed = _parse_exercises(row.get("lift_exercises", ""))
        extra = _exercise_cards(parsed)

        if show_detail:
            # Session summary stats
            total_volume = sum(e["weight"] * e["sets"] * e["reps"] for e in parsed if e["weight"])
            total_sets = sum(e["sets"] for e in parsed)
            detail_stats = []
            if total_volume:
                detail_stats.append(stat_cell("Total Volume", f"{total_volume:,.0f} lbs"))
            if total_sets:
                detail_stats.append(stat_cell("Total Sets", str(total_sets)))
            max_hr_val = row.get("max_hr", 0)
            if max_hr_val and not pd.isna(max_hr_val):
                detail_stats.append(stat_cell("Peak HR", f"{max_hr_val:.0f} bpm"))
            ts = row.get("training_stress", 0)
            if ts and not pd.isna(ts) and ts > 0:
                detail_stats.append(stat_cell("Training Stress", f"{ts:.0f}"))
            if detail_stats:
                detail.append(html.Div(detail_stats, style={
                    "display": "flex", "gap": "24px", "flexWrap": "wrap",
                    "marginBottom": "12px",
                }))

            # HR charts
            from strava_analytics.web.components.charts import (
                activity_hr_zone_chart, activity_hr_timeline_chart,
            )
            _card_uid += 1
            zone_secs = [float(row.get(f"zone_{z}_s", 0) or 0) for z in range(1, 6)]
            if sum(zone_secs) > 30:
                zc = activity_hr_zone_chart(zone_secs, chart_id=f"card-zones-{_card_uid}")
                if zc:
                    detail.append(zc)

            filename = row.get("filename", "")
            if filename and not pd.isna(filename) and str(filename).endswith(".fit.gz"):
                from strava_analytics.routes import parse_hr_stream
                from strava_analytics.web import data as _data
                hr_pts = parse_hr_stream(_data.get_export_dir() / str(filename))
                if len(hr_pts) > 10:
                    _card_uid += 1
                    est_max_hr = row.get("estimated_max_hr", 200) or 200
                    hc = activity_hr_timeline_chart(hr_pts, chart_id=f"card-hr-{_card_uid}",
                                                    max_hr=int(est_max_hr))
                    if hc:
                        detail.append(hc)

            # Pullup stats
            pullup_sets = row.get("pullup_sets", None)
            pullup_reps = row.get("pullup_reps", None)
            parts = []
            if pullup_sets and not pd.isna(pullup_sets):
                parts.append(f"{int(pullup_sets)} sets")
            if pullup_reps and not pd.isna(pullup_reps):
                parts.append(f"{int(pullup_reps)} reps")
            if parts:
                detail.append(stat_cell("Pull-ups", " / ".join(parts)))

    else:
        # Swim, Yoga, Other
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))
        if dist and not pd.isna(dist) and dist > 0:
            primary.append(stat_cell("Distance", f"{dist:.1f} mi"))
        cals = row.get("calories", 0)
        if cals and not pd.isna(cals) and cals > 0:
            primary.append(stat_cell("Calories", f"{cals:.0f}"))

    return {
        "header": header,
        "primary": primary,
        "extra": extra,
        "detail": detail,
        "color": color,
        "date_id": date_id,
    }
