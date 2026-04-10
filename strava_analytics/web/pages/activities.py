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
    HR_ZONE_COLORS, HR_ZONE_LABELS, FONT_MONO,
)
from strava_analytics.metrics import format_pace


# ── SVG lift icons (minimal line-art) ────────────────────────────────

_LIFT_ICONS = {
    "bench": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="24" x2="42" y2="24"/><rect x="10" y="18" width="4" height="12" rx="1"/><rect x="34" y="18" width="4" height="12" rx="1"/><circle cx="6" cy="24" r="3"/><circle cx="42" cy="24" r="3"/></svg>',
    "squat": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="8" y1="14" x2="40" y2="14"/><rect x="12" y="8" width="3" height="12" rx="1"/><rect x="33" y="8" width="3" height="12" rx="1"/><circle cx="8" cy="14" r="2.5"/><circle cx="40" cy="14" r="2.5"/><path d="M18 20 L18 30 Q18 36 24 38 Q30 36 30 30 L30 20"/></svg>',
    "deadlift": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="34" x2="42" y2="34"/><rect x="10" y="28" width="4" height="12" rx="1"/><rect x="34" y="28" width="4" height="12" rx="1"/><circle cx="6" cy="34" r="3"/><circle cx="42" cy="34" r="3"/><path d="M20 34 L20 18 M28 34 L28 18"/><line x1="18" y1="18" x2="30" y2="18"/></svg>',
    "ohp": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="8" y1="10" x2="40" y2="10"/><rect x="12" y="4" width="3" height="12" rx="1"/><rect x="33" y="4" width="3" height="12" rx="1"/><circle cx="8" cy="10" r="2.5"/><circle cx="40" cy="10" r="2.5"/><path d="M20 16 L20 34 M28 16 L28 34"/></svg>',
}


def _lift_icon(lift_name: str, size: int = 28) -> html.Div:
    """Return an inline SVG icon for a lift type."""
    key = lift_name.lower().split()[0] if lift_name else ""
    # Map common exercise names to icon keys
    for k in _LIFT_ICONS:
        if k in key:
            svg = _LIFT_ICONS[k]
            break
    else:
        svg = _LIFT_ICONS.get("bench", "")  # fallback

    from dash import html as _html
    return _html.Div(
        dangerously_allow_html=True,
        children="",
        style={
            "width": f"{size}px", "height": f"{size}px",
            "color": TEXT_MUTED, "flexShrink": "0",
        },
        **{"data-svg-icon": svg},
    )


# ── SVG Mini-map from cached route fingerprints ─────────────────────

_route_fingerprints: dict | None = None


def _load_route_fingerprints() -> dict:
    """Load cached route fingerprints (50-point GPS coords per route)."""
    global _route_fingerprints
    if _route_fingerprints is not None:
        return _route_fingerprints

    import json
    export_dir = data.get_export_dir()
    if export_dir is None:
        _route_fingerprints = {}
        return _route_fingerprints

    index_path = export_dir / "route_index.json"
    if not index_path.exists():
        _route_fingerprints = {}
        return _route_fingerprints

    try:
        raw = json.loads(index_path.read_text())
        _route_fingerprints = raw.get("fingerprints", {})
    except Exception:
        _route_fingerprints = {}
    return _route_fingerprints


_mini_map_counter = 0


def _mini_map(filename: str, height: int = 140) -> html.Div | None:
    """Render a Leaflet tile map with route overlay from cached fingerprints."""
    global _mini_map_counter
    fps = _load_route_fingerprints()
    fp = fps.get(filename)
    if not fp or not fp.get("points"):
        return None

    pts = fp["points"]  # [[lat, lon], ...]
    if len(pts) < 3:
        return None

    import json
    _mini_map_counter += 1
    map_id = f"mini-map-{_mini_map_counter}"
    coords = [[p[0], p[1]] for p in pts]
    map_cfg = json.dumps({
        "coords": coords,
        "color": ACCENT,
        "height": height,
    })

    return html.Div(
        html.Div(id=f"{map_id}-map", className="leaflet-map-box"),
        className="leaflet-map-wrap",
        style={
            "width": "100%", "marginTop": "12px",
            "borderRadius": "6px", "overflow": "hidden",
            "border": f"1px solid {BORDER}",
        },
        **{"data-mapcfg": map_cfg, "data-mapid": f"{map_id}-map"},
    )


def _inline_hr_zone_bar(row) -> html.Div | None:
    """Inline horizontal stacked bar showing HR zone distribution for one activity."""
    zone_secs = []
    has_data = False
    for z in range(1, 6):
        val = row.get(f"zone_{z}_s", 0)
        if pd.notna(val) and val > 0:
            has_data = True
        zone_secs.append(float(val) if pd.notna(val) else 0)

    if not has_data:
        return None

    total = sum(zone_secs)
    if total <= 0:
        return None

    segments = []
    for z in range(5):
        pct = zone_secs[z] / total * 100
        if pct < 0.5:
            continue
        color = HR_ZONE_COLORS.get(z + 1, TEXT_MUTED)
        mins = int(zone_secs[z] / 60)
        segments.append(html.Div(
            title=f"{HR_ZONE_LABELS[z]}: {mins}m",
            style={
                "width": f"{pct}%", "height": "100%",
                "backgroundColor": color, "display": "inline-block",
            },
        ))

    return html.Div([
        html.Div("HR ZONES", style={
            "fontSize": "10px", "fontWeight": "600",
            "textTransform": "uppercase", "letterSpacing": "0.1em",
            "color": TEXT_MUTED, "marginBottom": "4px",
        }),
        html.Div(segments, style={
            "height": "8px", "display": "flex",
            "borderRadius": "4px", "overflow": "hidden",
            "backgroundColor": BORDER,
        }),
    ], style={"marginTop": "12px", "paddingTop": "12px",
              "borderTop": f"1px solid {BORDER}"})

dash.register_page(__name__, path="/activities", name="Activities")

_PAGE_SIZE = 50


# ── Card builders ─────────────────────────────────────────────────────

def _activity_card(row, idx: int, default_open: bool = False) -> html.Details:
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
    card_extra = None  # map (runs) or lift summary (lifts) — rendered as block outside flex row

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

        # Inline HR zone bar for this run
        zone_bar = _inline_hr_zone_bar(row)
        if zone_bar:
            detail_content.append(zone_bar)

        # Mini-map as separate block below stats + full route loading in detail
        filename = row.get("filename", "")
        if filename and str(filename).endswith(".fit.gz"):
            card_extra = _mini_map(str(filename))
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
        # Stats row: duration, HR, calories (compact)
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))
        hr = row.get("avg_hr", 0)
        if hr and not pd.isna(hr):
            primary.append(stat_cell("Avg HR", f"{hr:.0f} bpm"))
        cals = row.get("calories", 0)
        if cals and not pd.isna(cals) and cals > 0:
            primary.append(stat_cell("Calories", f"{cals:.0f}"))

        # Parse ALL exercises from lift_exercises string
        exercises_str = row.get("lift_exercises", "")
        parsed_exercises = []
        if exercises_str and not pd.isna(exercises_str):
            import re
            for ex_str in str(exercises_str).split(";"):
                ex_str = ex_str.strip()
                if not ex_str:
                    continue
                # Parse "Bench Press 3x5@190" or "Face Pull 3x5@30" or "Pull Up 1x15"
                m = re.match(r'^(.+?)\s+(\d+)x(\d+)(?:@(\d+(?:\.\d+)?))?$', ex_str)
                if m:
                    parsed_exercises.append({
                        "name": m.group(1).strip(),
                        "sets": int(m.group(2)),
                        "reps": int(m.group(3)),
                        "weight": float(m.group(4)) if m.group(4) else 0,
                    })
                else:
                    parsed_exercises.append({
                        "name": ex_str, "sets": 0, "reps": 0, "weight": 0,
                    })

        # Map exercise names to icon keys
        _name_to_icon = {
            "bench": "bench", "squat": "squat", "deadlift": "deadlift",
            "ohp": "ohp", "overhead": "ohp",
        }
        # Generic dumbbell icon for exercises without a specific icon
        _GENERIC_ICON = (
            '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" '
            'stroke-width="2.5" stroke-linecap="round">'
            '<line x1="10" y1="24" x2="38" y2="24"/>'
            '<rect x="6" y="18" width="6" height="12" rx="1.5"/>'
            '<rect x="36" y="18" width="6" height="12" rx="1.5"/></svg>'
        )

        # Build exercise cards for ALL exercises
        _lift_cards = []
        max_volume = 1  # for progress bar scaling
        for ex in parsed_exercises:
            vol = int(ex["weight"] * ex["sets"] * ex["reps"]) if ex["weight"] else 0
            if vol > max_volume:
                max_volume = vol

        for ex in parsed_exercises:
            ex_name = ex["name"]
            n_sets = ex["sets"]
            n_reps = ex["reps"]
            wt = ex["weight"]
            scheme = f"{n_sets}\u00d7{n_reps}" if n_sets and n_reps else ""
            volume = int(wt * n_sets * n_reps) if wt and n_sets and n_reps else 0

            # Find icon
            icon_key = None
            for keyword, key in _name_to_icon.items():
                if keyword in ex_name.lower():
                    icon_key = key
                    break
            lift_color = LIFT_COLORS.get(icon_key, TEXT_MUTED)
            svg = _LIFT_ICONS.get(icon_key, _GENERIC_ICON)

            icon_div = html.Div(
                style={
                    "width": "24px", "height": "24px",
                    "color": lift_color, "flexShrink": "0",
                },
                **{"data-svg-icon": svg},
            )

            # Rep ladder: tiny vertical bars, one per set, height = reps
            # 5-rep reference line helps distinguish 5 vs 8 reps at a glance
            max_reps_scale = 12  # visual scale
            ladder_h = 24  # total container height
            rep_bars = None
            if n_sets > 0 and n_reps > 0:
                bar_h = max(4, min(ladder_h, int(n_reps / max_reps_scale * ladder_h)))
                ref_5_h = int(5 / max_reps_scale * ladder_h)  # 5-rep reference
                rep_bars = html.Div([
                    # Reference line at 5 reps
                    html.Div(style={
                        "position": "absolute", "bottom": f"{ref_5_h}px",
                        "left": "0", "right": "0",
                        "borderBottom": f"1px dashed {BORDER}",
                    }),
                    # Bars
                    html.Div([
                        html.Div(style={
                            "width": "7px", "height": f"{bar_h}px",
                            "backgroundColor": lift_color, "opacity": "0.5",
                            "borderRadius": "1.5px",
                        }) for _ in range(n_sets)
                    ], style={
                        "display": "flex", "gap": "2px",
                        "alignItems": "flex-end", "height": "100%",
                    }),
                ], style={
                    "position": "relative",
                    "marginTop": "6px", "height": f"{ladder_h}px",
                })

            _lift_cards.append(html.Div([
                html.Div([
                    icon_div,
                    html.Div(ex_name, style={
                        "fontSize": "11px", "fontWeight": "600",
                        "color": lift_color,
                    }),
                ], style={"display": "flex", "gap": "6px", "alignItems": "center"}),
                html.Div([
                    html.Span(f"{wt:.0f}", style={
                        "fontFamily": FONT_MONO,
                        "fontSize": "16px", "fontWeight": "700",
                    }) if wt else None,
                    html.Span(f" {scheme}", style={
                        "fontFamily": FONT_MONO, "fontSize": "12px",
                        "color": TEXT_SECONDARY,
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

        if _lift_cards:
            card_extra = html.Div(_lift_cards, style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fill, minmax(140px, 1fr))",
                "gap": "6px", "marginTop": "10px",
            })

        # Expanded detail: session stats + HR timeline + pullups + HR zones

        # Session summary stats
        total_volume = sum(
            ex["weight"] * ex["sets"] * ex["reps"]
            for ex in parsed_exercises if ex["weight"]
        )
        total_sets = sum(ex["sets"] for ex in parsed_exercises)
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
            detail_content.append(html.Div(detail_stats, style={
                "display": "flex", "gap": "24px", "flexWrap": "wrap",
                "marginBottom": "12px",
            }))

        # HR timeline chart (SVG sparkline from FIT HR stream)
        filename = row.get("filename", "")
        if filename and str(filename).endswith(".fit.gz"):
            from strava_analytics.routes import parse_hr_stream
            hr_pts = parse_hr_stream(data.get_export_dir() / str(filename))
            if len(hr_pts) > 10:
                hrs = [p[1] for p in hr_pts]
                t0 = hr_pts[0][0]
                times_min = [(p[0] - t0).total_seconds() / 60 for p in hr_pts]
                max_t = max(times_min) or 1
                min_hr = min(hrs)
                max_hr = max(hrs)
                hr_range = max_hr - min_hr or 1
                chart_w, chart_h = 400, 60

                # Build SVG polyline for HR
                step = max(1, len(hrs) // 100)  # downsample to ~100 points
                svg_pts = []
                for i in range(0, len(hrs), step):
                    x = times_min[i] / max_t * chart_w
                    y = chart_h - (hrs[i] - min_hr) / hr_range * (chart_h - 4) - 2
                    svg_pts.append(f"{x:.1f},{y:.1f}")

                # Fill area under curve
                area_pts = svg_pts + [f"{chart_w:.1f},{chart_h}", "0,{chart_h}"]
                hr_svg = (
                    f'<svg viewBox="0 0 {chart_w} {chart_h}" '
                    f'xmlns="http://www.w3.org/2000/svg" '
                    f'style="width:100%;height:{chart_h}px" preserveAspectRatio="none">'
                    f'<polygon points="{" ".join(area_pts)}" '
                    f'fill="{ACCENT_RED}" opacity="0.1"/>'
                    f'<polyline points="{" ".join(svg_pts)}" fill="none" '
                    f'stroke="{ACCENT_RED}" stroke-width="1.5" opacity="0.7"/>'
                    f'<text x="2" y="10" font-size="9" fill="{TEXT_MUTED}" '
                    f'font-family="monospace">{max_hr:.0f}</text>'
                    f'<text x="2" y="{chart_h - 2}" font-size="9" fill="{TEXT_MUTED}" '
                    f'font-family="monospace">{min_hr:.0f}</text>'
                    f'</svg>'
                )

                detail_content.append(html.Div([
                    html.Div("HEART RATE", style={
                        "fontSize": "10px", "fontWeight": "600",
                        "textTransform": "uppercase", "letterSpacing": "0.1em",
                        "color": TEXT_MUTED, "marginBottom": "4px",
                    }),
                    html.Div(
                        style={
                            "width": "100%", "height": f"{chart_h}px",
                            "borderRadius": "4px", "overflow": "hidden",
                            "backgroundColor": "var(--surface, #1c1917)",
                            "border": f"1px solid {BORDER}",
                        },
                        **{"data-svg-icon": hr_svg},
                    ),
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

        # HR zone bar
        zone_bar = _inline_hr_zone_bar(row)
        if zone_bar:
            detail_content.append(zone_bar)

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
            card_extra,
        ], style={"listStyle": "none", "cursor": "pointer"}),
        html.Div(detail_content, style={
            "padding": "12px 0 0 0",
        }) if detail_content else None,
    ], id=f"activity-card-{date_id}-{idx}",
       open=default_open,
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
        cards.append(_activity_card(row, idx, default_open=False))
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
    return build_route_charts(filename, df=data.get_df())
