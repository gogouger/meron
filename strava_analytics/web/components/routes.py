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
    TEXT_PRIMARY, TEXT_MUTED, BORDER,
)
from strava_analytics.metrics import format_pace


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


def build_route_charts(filename: str) -> list:
    """Build route map + stream charts for a run. Returns list of Dash components."""
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
                    "label": "Elevation", "data": [round(e, 0) for e in elev_smooth[:len(x_labels)]],
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
                "x": {"title": {"display": True, "text": "mi"}, "grid": {"display": False}},
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
                    "plugins": {"legend": {"display": False}},
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

    result = children if children else [html.P("No GPS data.", style={"color": TEXT_MUTED})]
    if len(_route_cache) >= _ROUTE_CACHE_MAX:
        _route_cache.pop(next(iter(_route_cache)))
    _route_cache[filename] = result
    return result
