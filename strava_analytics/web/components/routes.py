"""Route chart building — Leaflet maps + Chart.js stream overlays.

Extracted from running.py so it can be shared by both the activities page
and the activity modal overlay.
"""

import json

import pandas as pd
from dash import html, dcc

from strava_analytics.web import data
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, ACCENT_RED,
    TEXT_PRIMARY, TEXT_MUTED, BORDER, SLATE_60,
)
from strava_analytics.metrics import format_pace

_ZONE_COLORS = {1: SLATE_60, 2: ACCENT_SLATE, 3: ACCENT_AMBER, 4: ACCENT, 5: ACCENT_RED}
_ZONE_LABELS = ["Z1 Recovery", "Z2 Easy", "Z3 Moderate", "Z4 Threshold", "Z5 Max"]

# Effort color gradient: blue (low) → gold (mid) → red (high)
_EFFORT_STOPS = [
    (0.0, (91, 155, 213)),    # ACCENT_SLATE  — low effort
    (0.5, (212, 168, 75)),    # ACCENT_AMBER  — mid effort
    (1.0, (239, 60, 74)),     # ACCENT        — high effort
]


def _effort_color(t: float) -> str:
    """Return an rgba color for normalized effort *t* (0–1)."""
    t = max(0.0, min(1.0, t))
    for i in range(len(_EFFORT_STOPS) - 1):
        t0, c0 = _EFFORT_STOPS[i]
        t1, c1 = _EFFORT_STOPS[i + 1]
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 != t0 else 0
            r = int(c0[0] + (c1[0] - c0[0]) * f)
            g = int(c0[1] + (c1[1] - c0[1]) * f)
            b = int(c0[2] + (c1[2] - c0[2]) * f)
            return f"rgb({r},{g},{b})"
    return f"rgb{_EFFORT_STOPS[-1][1]}"


_route_cache: dict = {}
_ROUTE_CACHE_MAX = 32
_route_map_counter = 0


def _smooth(vals, window=7):
    """Rolling average for smoothing noisy stream data."""
    arr = pd.Series(vals)
    return arr.rolling(window, min_periods=1, center=True).mean().tolist()


def _gap_factor(grade_pct: float) -> float:
    """Minetti cost factor for grade-adjusted pace."""
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
            d_elev = altitude_m[min(i, len(altitude_m) - 1)] - altitude_m[max(i - 1, 0)]
            d_dist = distance_m[min(i, len(distance_m) - 1)] - distance_m[max(i - 1, 0)]
            grade = d_elev / d_dist if d_dist > 1 else 0
        else:
            grade = 0
        adj = _gap_factor(grade * 100)
        gap_speed = s * adj
        pace = 26.8224 / gap_speed if gap_speed > 0.3 else None
        gap.append(pace if pace and pace < 20 else None)
    return gap


def build_route_charts(filename: str, df: pd.DataFrame | None = None) -> list:
    """Build route map + stream charts for a run. Returns list of Dash components.

    If *df* is provided, ghost overlays for previous runs on the same route
    are included automatically.
    """
    global _route_map_counter

    if filename in _route_cache:
        return _route_cache[filename]

    from strava_analytics.routes import parse_activity

    export_dir = data.get_export_dir()
    stream = parse_activity(export_dir / filename)
    children = []

    if stream.coords:
        _route_map_counter += 1
        map_id = f"route-map-{_route_map_counter}"
        coords = [[c[0], c[1]] for c in stream.coords]

        map_cfg = json.dumps({"coords": coords, "color": ACCENT, "height": 300})
        children.append(html.Div(
            html.Div(id=f"{map_id}-map", className="leaflet-map-box"),
            className="leaflet-map-wrap",
            **{"data-mapcfg": map_cfg, "data-mapid": f"{map_id}-map"},
        ))

    from strava_analytics.routes import compute_splits
    dist_mi = [d / 1609.344 for d in stream.distance_m] if stream.distance_m else []
    splits = compute_splits(stream)
    elev_ft = [a * 3.28084 for a in stream.altitude_m] if stream.altitude_m else []

    # Splits table
    if splits:
        fastest = min(s["pace_min_per_mi"] for s in splits)
        avg_pace = sum(s["pace_min_per_mi"] for s in splits) / len(splits)
        _mono = "'IBM Plex Mono', monospace"
        _hdr_s = {"fontSize": "9px", "fontWeight": "600", "textTransform": "uppercase",
                  "letterSpacing": "0.06em", "color": TEXT_MUTED}

        header = html.Div([
            html.Span("Mi", style={**_hdr_s, "width": "22px"}),
            html.Span("Pace", style={**_hdr_s, "width": "42px"}),
            html.Span("GAP", style={**_hdr_s, "width": "42px"}),
            html.Span("", style={"flex": "1"}),
            html.Span("Elev", style={**_hdr_s, "width": "40px", "textAlign": "right"}),
            html.Span("HR", style={**_hdr_s, "width": "32px", "textAlign": "right"}),
        ], style={"display": "flex", "gap": "6px", "padding": "3px 0"})

        rows = [header]
        for s in splits:
            p = s["pace_min_per_mi"]
            bar_pct = min(100, max(8, (fastest / p) * 100)) if p > 0 else 8
            elev_c = s.get("elevation_change_ft", 0)
            elev_str = f"{elev_c:+.0f}" if elev_c else "0"
            hr_val = s["avg_hr"]
            hr_str = f"{hr_val:.0f}" if hr_val > 0 else ""
            dist_ft = s["distance_mi"] * 5280
            grade_pct = (elev_c / dist_ft * 100) if dist_ft > 0 else 0
            gf = _gap_factor(grade_pct)
            gap_pace = p / gf if gf > 0 else p

            rows.append(html.Div([
                html.Span(
                    str(s["split_num"]) if s["distance_mi"] >= 0.9 else f".{int(s['distance_mi'] * 10)}",
                    style={"width": "22px", "fontWeight": "600", "color": TEXT_PRIMARY,
                           "fontFamily": _mono, "fontSize": "12px"},
                ),
                html.Span(format_pace(p), style={
                    "width": "42px", "fontFamily": _mono, "fontSize": "12px", "color": TEXT_PRIMARY,
                }),
                html.Span(format_pace(gap_pace), style={
                    "width": "42px", "fontFamily": _mono, "fontSize": "11px", "color": TEXT_MUTED,
                }),
                html.Div(
                    html.Div(style={
                        "width": f"{bar_pct}%", "height": "100%",
                        "background": ACCENT_SLATE, "borderRadius": "2px", "opacity": "0.75",
                    }),
                    style={"flex": "1", "height": "10px", "display": "flex", "alignItems": "center"},
                ),
                html.Span(elev_str, style={
                    "width": "40px", "textAlign": "right", "fontFamily": _mono,
                    "fontSize": "11px", "color": TEXT_MUTED,
                }),
                html.Span(hr_str, style={
                    "width": "32px", "textAlign": "right", "fontFamily": _mono,
                    "fontSize": "11px", "color": ACCENT_RED if hr_val > 0 else TEXT_MUTED,
                }),
            ], style={"display": "flex", "gap": "6px", "padding": "3px 0", "alignItems": "center"},
               title=f"Mi {s['split_num']}: {format_pace(p)}/mi, GAP {format_pace(gap_pace)}/mi, {elev_str}ft, {hr_str} bpm"))

        rows.append(html.Div([
            html.Span("", style={"width": "22px"}),
            html.Span(format_pace(avg_pace), style={
                "width": "42px", "fontFamily": _mono, "fontSize": "11px",
                "fontWeight": "600", "color": TEXT_MUTED,
            }),
            html.Span("avg", style={"fontSize": "9px", "color": TEXT_MUTED}),
        ], style={"display": "flex", "gap": "6px", "padding": "3px 0",
                  "borderTop": f"1px solid {BORDER}"}))

        children.append(html.Div(rows, style={"marginTop": "10px"}))

    # Stream chart (pace/GAP/HR/elevation)
    has_pace = stream.speed_ms and len(stream.speed_ms) > 5
    has_hr = stream.heart_rate and len(stream.heart_rate) > 5
    if has_pace:
        pv_raw = [26.8224 / s if s > 0.5 else None for s in stream.speed_ms]
        px_vals = dist_mi[:len(pv_raw)] if dist_mi else list(range(len(pv_raw)))
        vp = [p for p in pv_raw if p and p < 20]

        if vp:
            pv = _smooth([p if p and p < 20 else None for p in pv_raw], window=15)
            gap_raw = _compute_gap(stream.speed_ms, stream.altitude_m, stream.distance_m)
            gap = _smooth([g if g and g < 20 else None for g in gap_raw], window=15)
            hr_smooth = _smooth(stream.heart_rate, window=11) if has_hr else []

            _route_map_counter_local = _route_map_counter
            stream_id = f"stream-{_route_map_counter_local}"
            x_labels = [round(x, 2) for x in px_vals[:len(pv)]]
            datasets = []

            if elev_ft and dist_mi:
                elev_smooth = _smooth(elev_ft, window=7)
                datasets.append({
                    "label": "_Elevation", "data": [round(e, 0) for e in elev_smooth[:len(x_labels)]],
                    "borderColor": "transparent", "backgroundColor": "rgba(150,150,150,0.08)",
                    "fill": True, "pointRadius": 0, "yAxisID": "y1", "tension": 0.3, "order": 3,
                })

            datasets.append({
                "label": "Pace", "data": [round(v, 2) if v else None for v in pv],
                "borderColor": ACCENT_SLATE, "backgroundColor": "rgba(91,155,213,0.12)",
                "borderWidth": 2.5, "fill": True, "pointRadius": 0,
                "yAxisID": "y", "tension": 0.3, "spanGaps": True, "order": 2,
            })

            if gap:
                datasets.append({
                    "label": "GAP", "data": [round(v, 2) if v else None for v in gap[:len(x_labels)]],
                    "borderColor": ACCENT_AMBER, "borderWidth": 1.5, "borderDash": [4, 4],
                    "fill": False, "pointRadius": 0, "yAxisID": "y", "tension": 0.3,
                    "spanGaps": True, "order": 1,
                })

            if has_hr and hr_smooth:
                datasets.append({
                    "label": "HR", "data": [round(v, 0) if v else None for v in hr_smooth[:len(x_labels)]],
                    "borderColor": ACCENT_RED, "borderWidth": 2, "fill": False,
                    "pointRadius": 0, "yAxisID": "y2", "tension": 0.3, "spanGaps": True, "order": 0,
                })

            pace_min_val = min(vp) - 0.5
            pace_max_val = max(vp) + 0.5
            hr_vals = [h for h in (stream.heart_rate or []) if h and h > 0]

            scales = {
                "x": {
                    "title": {"display": True, "text": "mi"},
                    "ticks": {"stepSize": 0.25},
                    "grid": {"display": True},
                },
                "y": {"reverse": True, "min": pace_min_val, "max": pace_max_val,
                       "title": {"display": True, "text": "pace /mi"}, "position": "left",
                       "grid": {"display": False}},
            }
            if elev_ft:
                scales["y1"] = {"display": False, "min": min(elev_ft) - 20,
                                "max": max(elev_ft) + 20, "position": "right",
                                "grid": {"display": False}}
            if has_hr and hr_vals:
                scales["y2"] = {"min": min(hr_vals) - 10, "max": max(hr_vals) + 10,
                                "title": {"display": True, "text": "hr bpm"},
                                "position": "right", "grid": {"display": False}}

            stream_cfg = json.dumps({
                "type": "line",
                "data": {"labels": x_labels, "datasets": datasets},
                "options": {
                    "responsive": True, "maintainAspectRatio": False,
                    "interaction": {"mode": "index", "intersect": False},
                    "plugins": {
                        "legend": {
                            "display": True, "position": "bottom",
                            "labels": {"boxWidth": 12, "padding": 8, "usePointStyle": True},
                        },
                    },
                    "scales": scales,
                },
            })

            # Use data-chartcfg so the MutationObserver renders it
            # (inline scripts don't execute when injected via Dash callbacks)
            children.append(html.Div([
                html.Div(className="cjs-canvas-box", style={"height": "200px"}),
            ], id=f"{stream_id}-wrap", className="cjs-chart-wrap",
               style={"marginTop": "8px"},
               **{"data-chartcfg": stream_cfg}))

    # Per-run HR zone time bar chart
    if stream.heart_rate and stream.timestamps and len(stream.heart_rate) > 10:
        cfg = data.get_athlete_config()
        max_hr = cfg.get("max_hr", 200)
        zone_pct = cfg.get("zones_pct", [60, 70, 80, 90])
        boundaries = [int(max_hr * p / 100) for p in zone_pct]

        zone_secs = [0.0] * 5
        for i in range(1, len(stream.heart_rate)):
            hr = stream.heart_rate[i]
            if not hr or hr <= 0:
                continue
            # Time delta
            t0, t1 = stream.timestamps[i - 1], stream.timestamps[i]
            if hasattr(t0, "timestamp"):
                dt = (t1 - t0).total_seconds()
            elif isinstance(t0, (int, float)):
                dt = t1 - t0
            else:
                dt = 1.0
            if dt <= 0 or dt > 300:
                continue
            # Classify into zone
            if hr < boundaries[0]:
                z = 0
            elif hr < boundaries[1]:
                z = 1
            elif hr < boundaries[2]:
                z = 2
            elif hr < boundaries[3]:
                z = 3
            else:
                z = 4
            zone_secs[z] += dt

        zone_mins = [round(s / 60, 1) for s in zone_secs]
        if max(zone_mins) > 0:
            _route_map_counter += 1
            zone_id = f"run-zones-{_route_map_counter}"
            colors = [_ZONE_COLORS.get(z, TEXT_MUTED) for z in range(1, 6)]
            zone_cfg = json.dumps({
                "type": "bar",
                "data": {
                    "labels": _ZONE_LABELS,
                    "datasets": [{"label": "Minutes", "data": zone_mins,
                                  "backgroundColor": colors, "borderRadius": 2}],
                },
                "options": {
                    "indexAxis": "y",
                    "plugins": {"legend": {"display": False}},
                    "scales": {
                        "x": {"beginAtZero": True, "min": 0,
                               "title": {"display": True, "text": "Minutes"},
                               "max": round(max(zone_mins) * 1.15, 1)},
                        "y": {},
                    },
                },
            })
            children.append(html.Div([
                html.Div(className="cjs-canvas-box", style={"height": "160px"}),
            ], id=f"{zone_id}-wrap", className="cjs-chart-wrap",
               style={"marginTop": "8px"},
               **{"data-chartcfg": zone_cfg}))

    # Route history — compare all runs on the same GPS route
    if df is not None:
        try:
            from strava_analytics.route_matching import get_route_matches
            match_fns = get_route_matches(filename, df, export_dir)
            if match_fns:
                # Include current run + matches, sorted by date
                all_fns = [filename] + match_fns
                all_rows = df[df["filename"].isin(all_fns)].sort_values("date", ascending=False)

                # Normalize relative effort for color gradient
                efforts = all_rows["relative_effort"].fillna(0).tolist()
                e_min, e_max = min(efforts), max(efforts)
                e_range = e_max - e_min if e_max > e_min else 1.0

                # Build datasets and run list rows
                _route_map_counter += 1
                hist_id = f"route-hist-{_route_map_counter}"
                run_list_rows = []

                for ri, (_, rrow) in enumerate(all_rows.iterrows()):
                    is_current = rrow["filename"] == filename
                    effort = rrow.get("relative_effort", 0) or 0
                    t = (effort - e_min) / e_range
                    color = _effort_color(t)

                    r_date = rrow["date"].strftime("%b %d, %Y") if hasattr(rrow["date"], "strftime") else str(rrow["date"])
                    avg_pace = rrow.get("pace_min_per_mi", 0) or 0
                    dist = rrow.get("distance_mi", 0) or 0

                    # Run list row
                    _mono = "'IBM Plex Mono', monospace"
                    run_list_rows.append(html.Div([
                        html.Span(style={
                            "width": "10px", "height": "10px", "borderRadius": "50%",
                            "background": color, "display": "inline-block",
                            "flexShrink": "0",
                        }),
                        html.Span(r_date, style={
                            "fontWeight": "700" if is_current else "500",
                            "fontSize": "12px", "color": "var(--text-primary)",
                            "minWidth": "90px",
                        }),
                        html.Span(format_pace(avg_pace) + "/mi" if avg_pace else "",
                                  style={"fontFamily": _mono, "fontSize": "12px",
                                         "color": "var(--text-primary)", "minWidth": "55px"}),
                        html.Span(f"{dist:.1f} mi" if dist else "",
                                  style={"fontFamily": _mono, "fontSize": "11px",
                                         "color": "var(--text-muted)", "minWidth": "45px"}),
                        html.Span(f"{int(effort)}" if effort else "",
                                  style={"fontFamily": _mono, "fontSize": "10px",
                                         "color": color, "fontWeight": "600",
                                         "minWidth": "30px", "textAlign": "right"}),
                    ], style={
                        "display": "flex", "gap": "8px", "alignItems": "center",
                        "padding": "5px 8px", "borderRadius": "4px",
                        "background": "var(--elevated)" if is_current else "transparent",
                    }))

                if run_list_rows and len(run_list_rows) >= 2:
                    # Pace-over-time scatter: x=date, y=avg pace, dot colored by effort
                    # Sort chronologically for the chart
                    chart_rows = all_rows.sort_values("date")
                    chart_points = []
                    chart_colors = []
                    chart_sizes = []
                    avg_paces = []
                    for _, cr in chart_rows.iterrows():
                        ap = cr.get("pace_min_per_mi", 0) or 0
                        if not ap or ap <= 0:
                            continue
                        eff = cr.get("relative_effort", 0) or 0
                        t = (eff - e_min) / e_range
                        chart_points.append({
                            "x": cr["date"].isoformat() if hasattr(cr["date"], "isoformat") else str(cr["date"]),
                            "y": round(ap, 2),
                        })
                        chart_colors.append(_effort_color(t))
                        chart_sizes.append(6 if cr["filename"] != filename else 9)
                        avg_paces.append(ap)

                    if len(chart_points) >= 2:
                        p_min = min(avg_paces) - 0.3
                        p_max = max(avg_paces) + 0.3

                        hist_cfg_obj = {
                            "type": "scatter",
                            "data": {"datasets": [{
                                "label": "_runs",
                                "data": chart_points,
                                "backgroundColor": chart_colors,
                                "borderColor": chart_colors,
                                "pointRadius": chart_sizes,
                                "pointHoverRadius": [s + 2 for s in chart_sizes],
                                "showLine": True,
                                "borderColor": "rgba(168,162,158,0.25)",
                                "borderWidth": 1,
                                "fill": False,
                                "tension": 0.3,
                            }]},
                            "options": {
                                "responsive": True, "maintainAspectRatio": False,
                                "interaction": {"mode": "nearest", "intersect": True},
                                "plugins": {"legend": {"display": False}},
                                "scales": {
                                    "x": {
                                        "type": "time", "time": {"unit": "week"},
                                        "grid": {"display": True},
                                    },
                                    "y": {
                                        "reverse": True, "min": p_min, "max": p_max,
                                        "title": {"display": True, "text": "avg pace /mi"},
                                        "grid": {"display": False},
                                    },
                                },
                            },
                            "_meta": {
                                "routeHistoryHover": True,
                                "scrollListId": f"{hist_id}-list",
                            },
                        }
                        hist_cfg = json.dumps(hist_cfg_obj)

                        # Tag each run list row with a data-index for scroll targeting
                        for i, row_div in enumerate(run_list_rows):
                            row_div.id = f"{hist_id}-row-{i}"

                        children.append(html.Div([
                            html.Div("ROUTE HISTORY", style={
                                "fontSize": "10px", "fontWeight": "700",
                                "letterSpacing": "0.1em", "color": "var(--text-muted)",
                                "marginBottom": "8px",
                            }),
                            html.Div([
                                # Scrollable run list
                                html.Div(run_list_rows, id=f"{hist_id}-list", style={
                                    "maxHeight": "220px", "overflowY": "auto",
                                    "paddingRight": "4px",
                                    "flex": "0 0 auto", "minWidth": "280px",
                                }),
                                # Pace over time chart
                                html.Div([
                                    html.Div(className="cjs-canvas-box", style={"height": "200px"}),
                                ], id=f"{hist_id}-wrap", className="cjs-chart-wrap",
                                   style={"flex": "1", "minWidth": "0"},
                                   **{"data-chartcfg": hist_cfg}),
                            ], style={
                                "display": "flex", "gap": "12px",
                                "alignItems": "flex-start",
                            }),
                        ], style={"marginTop": "16px", "borderTop": "1px solid var(--border)",
                                  "paddingTop": "12px"}))
        except Exception:
            pass  # route matching is best-effort

    result = children if children else [html.P("No GPS data.", style={"color": TEXT_MUTED})]
    if len(_route_cache) >= _ROUTE_CACHE_MAX:
        _route_cache.pop(next(iter(_route_cache)))
    _route_cache[filename] = result
    return result
