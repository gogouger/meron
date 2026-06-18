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
    HR_ZONE_COLORS, HR_ZONE_LABELS, FONT_MONO,
)
from strava_analytics.metrics import format_pace


_route_cache: dict = {}
_ROUTE_CACHE_MAX = 32
_route_map_counter = 0


# ── SVG Mini-map from cached route fingerprints ─────────────────────
# (Moved out of pages/activities.py so it can be used without triggering
# dash.register_page() during a page-render callback.)

_route_fingerprints: dict | None = None
_mini_map_counter = 0


def _load_route_fingerprints() -> dict:
    """Load cached route fingerprints (50-point GPS coords per route)."""
    global _route_fingerprints
    if _route_fingerprints is not None:
        return _route_fingerprints

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


def _mini_map(filename: str, height: int = 140, source_id: str | None = None):
    """Render a Leaflet tile map with route overlay from cached fingerprints.

    Tries two lookup keys in order: ``filename`` (bulk-import FIT files)
    then ``strava:<source_id>`` (API-synced activities whose polyline
    came from the summary endpoint — no FIT on disk).
    """
    global _mini_map_counter
    fps = _load_route_fingerprints()
    fp = None
    if filename:
        fp = fps.get(filename)
    if (not fp or not fp.get("points")) and source_id:
        fp = fps.get(f"strava:{source_id}")
    if not fp or not fp.get("points"):
        return None

    pts = fp["points"]  # [[lat, lon], ...]
    if len(pts) < 3:
        return None

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


def _polyline_only_route_charts(coords: list) -> html.Div:
    """Render just a Leaflet map (no stream charts) from a polyline.

    Used for activities that came in via the Strava API (no FIT file on
    disk, so no per-second streams — but the encoded summary_polyline
    is enough to draw the route).
    """
    global _route_map_counter
    _route_map_counter += 1
    map_id = f"route-map-{_route_map_counter}"
    map_cfg = json.dumps({
        "coords": [[c[0], c[1]] for c in coords],
        "color": ACCENT,
        "height": 300,
    })
    return html.Div([
        html.Div(
            html.Div(id=f"{map_id}-map", className="leaflet-map-box"),
            className="leaflet-map-wrap",
            **{"data-mapcfg": map_cfg, "data-mapid": f"{map_id}-map"},
        ),
        html.P(
            "Splits / pace / HR streams require a FIT file — import the "
            "Strava bulk export to see them. Map only for now.",
            style={"color": TEXT_MUTED, "fontSize": "12px",
                   "marginTop": "10px", "fontStyle": "italic"},
        ),
    ])


def build_route_charts(
    filename: str,
    df: pd.DataFrame | None = None,
    source_id: str | None = None,
) -> list:
    """Build route map + stream charts for a run. Returns list of Dash components.

    If *df* is provided, ghost overlays for previous runs on the same route
    are included automatically.

    When no FIT file exists on disk (API-synced activities), falls back
    to the cached ``strava:<source_id>`` polyline in ``route_index.json``
    and renders a map-only view — streams / splits aren't available
    without the FIT, so those sections are omitted.
    """
    global _route_map_counter

    cache_key = filename or (f"strava:{source_id}" if source_id else "")
    if cache_key and cache_key in _route_cache:
        return _route_cache[cache_key]

    from strava_analytics.routes import (
        parse_activity, parse_activity_for_row, resolve_activity_path,
    )

    export_dir = data.get_export_dir()

    # Find the row backing this activity in the enriched df so we can pull
    # streams_blob (the API-sync alternative to a FIT file). Match on
    # filename first (CSV-import rows), then activity_id (API rows — which
    # was set to source_id in the repository layer).
    row = None
    if df is not None and not df.empty:
        if filename:
            mask = df.get("filename") == filename if "filename" in df.columns else None
            if mask is not None and mask.any():
                row = df[mask].iloc[0]
        if row is None and source_id:
            try:
                sid_int = int(source_id)
                mask = df.get("activity_id") == sid_int if "activity_id" in df.columns else None
                if mask is not None and mask.any():
                    row = df[mask].iloc[0]
            except (TypeError, ValueError):
                pass

    fit_path = resolve_activity_path(export_dir, filename) if filename else None

    # Pull the streams: prefer streams_blob on the row, then the FIT file.
    stream = None
    if row is not None:
        stream = parse_activity_for_row(row)
        if not stream.coords and not stream.heart_rate and not stream.distance_m:
            stream = None
    if stream is None and fit_path is not None:
        stream = parse_activity(fit_path)

    if stream is None or (
        not stream.coords and not stream.distance_m and not stream.heart_rate
    ):
        # Last resort: cached polyline + the "import to see splits" note.
        fps = _load_route_fingerprints()
        fp = fps.get(filename) if filename else None
        if (not fp or not fp.get("points")) and source_id:
            fp = fps.get(f"strava:{source_id}")
        if fp and fp.get("points") and len(fp["points"]) >= 3:
            result = _polyline_only_route_charts(fp["points"])
            if cache_key:
                _route_cache[cache_key] = result
            return result
        empty = html.Div()
        if cache_key:
            _route_cache[cache_key] = empty
        return empty

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
        _mono = FONT_MONO
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
            x_vals = [round(x, 3) for x in px_vals[:len(pv)]]
            n_pts = len(x_vals)

            def _xy(yvals, n=n_pts):
                return [{"x": x_vals[i], "y": round(yvals[i], 2) if yvals[i] else None}
                        for i in range(min(len(yvals), n))]

            datasets = []

            if elev_ft and dist_mi:
                elev_smooth = _smooth(elev_ft, window=7)
                datasets.append({
                    "label": "_Elevation", "data": _xy(elev_smooth),
                    "borderColor": "transparent", "backgroundColor": "rgba(150,150,150,0.08)",
                    "fill": True, "pointRadius": 0, "yAxisID": "y1", "tension": 0.3, "order": 3,
                })

            datasets.append({
                "label": "Pace", "data": _xy(pv),
                "borderColor": ACCENT_SLATE, "backgroundColor": "rgba(91,155,213,0.12)",
                "borderWidth": 2.5, "fill": True, "pointRadius": 0,
                "yAxisID": "y", "tension": 0.3, "spanGaps": True, "order": 2,
            })

            if gap:
                datasets.append({
                    "label": "GAP", "data": _xy(gap),
                    "borderColor": ACCENT_AMBER, "borderWidth": 1.5, "borderDash": [4, 4],
                    "fill": False, "pointRadius": 0, "yAxisID": "y", "tension": 0.3,
                    "spanGaps": True, "order": 1,
                })

            if has_hr and hr_smooth:
                datasets.append({
                    "label": "HR", "data": _xy(hr_smooth),
                    "borderColor": ACCENT_RED, "borderWidth": 2, "fill": False,
                    "pointRadius": 0, "yAxisID": "y2", "tension": 0.3, "spanGaps": True, "order": 0,
                })

            pace_min_val = min(vp) - 0.5
            pace_max_val = max(vp) + 0.5
            max_dist = x_vals[-1] if x_vals else 1
            hr_vals = [h for h in (stream.heart_rate or []) if h and h > 0]

            scales = {
                "x": {
                    "type": "linear",
                    "min": 0, "max": max_dist,
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
                "data": {"datasets": datasets},
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

    # Dedicated HR line chart with zone background bands
    if has_hr and stream.heart_rate and len(stream.heart_rate) > 10:
        _route_map_counter += 1
        hr_chart_id = f"hr-line-{_route_map_counter}"
        hr_cfg = data.get_athlete_config()
        hr_max = hr_cfg.get("max_hr", 200)
        hr_zone_pct = hr_cfg.get("hr_zones_pct", [60, 70, 80, 90])
        hr_boundaries = [int(hr_max * p / 100) for p in hr_zone_pct]

        hr_smooth_vals = _smooth(stream.heart_rate, window=11)
        hr_x = dist_mi[:len(hr_smooth_vals)] if dist_mi else list(range(len(hr_smooth_vals)))
        hr_x_vals = [round(x, 3) for x in hr_x]

        hr_valid = [h for h in stream.heart_rate if h and h > 0]
        if hr_valid:
            hr_y_min = max(min(hr_valid) - 15, hr_boundaries[0] - 10)
            hr_y_max = min(max(hr_valid) + 10, hr_max + 10)

            # Zone band datasets — stacked filled line pairs (bottom → top)
            # Each zone is a line at the top boundary, filled down to the previous
            zone_bands = []
            all_boundaries = [hr_y_min] + hr_boundaries + [hr_y_max]
            x_range = [hr_x_vals[0], hr_x_vals[-1]]
            for zi in range(5):
                bot = max(all_boundaries[zi], hr_y_min)
                top = min(all_boundaries[zi + 1], hr_y_max)
                if top <= bot:
                    continue
                color = HR_ZONE_COLORS.get(zi + 1, TEXT_MUTED)
                h = color.lstrip("#") if color.startswith("#") else "999999"
                if len(h) >= 6:
                    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                else:
                    r, g, b = 150, 150, 150
                band_color = f"rgba({r},{g},{b},0.18)"
                # Bottom line (hidden)
                zone_bands.append({
                    "label": f"_zbot{zi}",
                    "data": [{"x": x_range[0], "y": bot}, {"x": x_range[1], "y": bot}],
                    "borderColor": "transparent", "borderWidth": 0,
                    "pointRadius": 0, "showLine": True, "fill": False,
                    "order": 20,
                })
                # Top line, filled down to the bottom line
                zone_bands.append({
                    "label": HR_ZONE_LABELS[zi],
                    "data": [{"x": x_range[0], "y": top}, {"x": x_range[1], "y": top}],
                    "borderColor": "transparent", "borderWidth": 0,
                    "backgroundColor": band_color,
                    "pointRadius": 0, "showLine": True,
                    "fill": "-1",  # fill to previous dataset
                    "order": 20,
                })

            # HR line dataset
            hr_line_data = [{"x": hr_x_vals[i], "y": round(hr_smooth_vals[i], 1)
                             if hr_smooth_vals[i] else None}
                            for i in range(min(len(hr_smooth_vals), len(hr_x_vals)))]

            hr_datasets = zone_bands + [{
                "label": "Heart Rate",
                "data": hr_line_data,
                "borderColor": ACCENT_RED,
                "borderWidth": 2,
                "fill": False,
                "pointRadius": 0,
                "tension": 0.3,
                "spanGaps": True,
                "order": 1,
            }]

            hr_line_cfg = json.dumps({
                "type": "line",
                "data": {"datasets": hr_datasets},
                "options": {
                    "responsive": True, "maintainAspectRatio": False,
                    "interaction": {"mode": "index", "intersect": False},
                    "plugins": {
                        "title": {"display": True, "text": "Heart Rate",
                                  "font": {"size": 13, "weight": "500"}},
                        "legend": {
                            "display": True, "position": "bottom",
                            "labels": {"boxWidth": 12, "padding": 6, "usePointStyle": True,
                                       "font": {"size": 10}},
                        },
                    },
                    "scales": {
                        "x": {
                            "type": "linear", "min": 0,
                            "max": hr_x_vals[-1] if hr_x_vals else 1,
                            "title": {"display": True, "text": "mi"},
                            "ticks": {"stepSize": 0.25},
                        },
                        "y": {
                            "min": hr_y_min, "max": hr_y_max,
                            "title": {"display": True, "text": "bpm"},
                        },
                    },
                },
            })

            children.append(html.Div([
                html.Div(className="cjs-canvas-box", style={"height": "200px"}),
            ], id=f"{hr_chart_id}-wrap", className="cjs-chart-wrap",
               style={"marginTop": "12px"},
               **{"data-chartcfg": hr_line_cfg}))

    # Per-run HR zone time bar chart
    if stream.heart_rate and stream.timestamps and len(stream.heart_rate) > 10:
        cfg = data.get_athlete_config()
        max_hr = cfg.get("max_hr", 200)
        zone_pct = cfg.get("hr_zones_pct", [60, 70, 80, 90])
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
            colors = [HR_ZONE_COLORS.get(z, TEXT_MUTED) for z in range(1, 6)]
            zone_cfg = json.dumps({
                "type": "bar",
                "data": {
                    "labels": HR_ZONE_LABELS,
                    "datasets": [{"label": "Minutes", "data": zone_mins,
                                  "backgroundColor": colors, "borderRadius": 2}],
                },
                "options": {
                    "indexAxis": "y",
                    "plugins": {
                        "legend": {"display": False},
                        "title": {"display": True, "text": "HR Zones",
                                  "font": {"size": 13, "weight": "500"}},
                    },
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

                _route_map_counter += 1
                hist_id = f"route-hist-{_route_map_counter}"
                _mono = FONT_MONO
                dot_color = ACCENT_SLATE

                # Find fastest run for highlighting
                valid_paces = [(r.get("pace_min_per_mi", 0) or 0, r["filename"])
                               for _, r in all_rows.iterrows()
                               if (r.get("pace_min_per_mi", 0) or 0) > 0]
                fastest_fn = min(valid_paces, key=lambda x: x[0])[1] if valid_paces else None

                # Build scrollable run list (all runs, newest first)
                run_list_rows = []
                for ri, (_, rrow) in enumerate(all_rows.iterrows()):
                    is_current = rrow["filename"] == filename
                    is_fastest = rrow["filename"] == fastest_fn
                    r_date = rrow["date"].strftime("%b %d, %Y") if hasattr(rrow["date"], "strftime") else str(rrow["date"])
                    avg_pace = rrow.get("pace_min_per_mi", 0) or 0
                    dist = rrow.get("distance_mi", 0) or 0

                    row_dot_style = {
                        "width": "10px", "height": "10px", "borderRadius": "50%",
                        "border": f"2px solid {dot_color}",
                        "background": dot_color if is_fastest else "transparent",
                        "display": "inline-block", "flexShrink": "0",
                    }
                    run_list_rows.append(html.Div([
                        html.Span(style=row_dot_style),
                        html.Span(r_date, style={
                            "fontWeight": "700" if is_current else "500",
                            "fontSize": "12px", "color": "var(--text-primary)",
                            "minWidth": "90px",
                        }),
                        html.Span(format_pace(avg_pace) + "/mi" if avg_pace else "",
                                  style={"fontFamily": _mono, "fontSize": "12px",
                                         "color": ACCENT if is_fastest else "var(--text-primary)",
                                         "fontWeight": "600" if is_fastest else "400",
                                         "minWidth": "55px"}),
                        html.Span(f"{dist:.1f} mi" if dist else "",
                                  style={"fontFamily": _mono, "fontSize": "11px",
                                         "color": "var(--text-muted)", "minWidth": "45px"}),
                    ], style={
                        "display": "flex", "gap": "8px", "alignItems": "center",
                        "padding": "5px 8px", "borderRadius": "4px",
                        "background": "var(--elevated)" if is_current else "transparent",
                    }))

                if run_list_rows and len(run_list_rows) >= 2:
                    # Chart: all runs sorted chronologically, windowed to last 20
                    chart_rows = all_rows.sort_values("date")
                    chart_points = []
                    point_bg = []
                    point_border = []
                    point_radius = []
                    avg_paces = []
                    _max_visible = 20
                    for _, cr in chart_rows.iterrows():
                        ap = cr.get("pace_min_per_mi", 0) or 0
                        if not ap or ap <= 0:
                            continue
                        is_fast = cr["filename"] == fastest_fn
                        is_cur = cr["filename"] == filename
                        avg_hr = cr.get("avg_hr", 0) or 0
                        dist = cr.get("distance_mi", 0) or 0
                        chart_points.append({
                            "x": cr["date"].isoformat() if hasattr(cr["date"], "isoformat") else str(cr["date"]),
                            "y": round(ap, 2),
                            "_dist": round(dist, 1),
                            "_hr": int(avg_hr) if avg_hr else 0,
                            "_pace": format_pace(ap) if ap else "",
                        })
                        point_bg.append(ACCENT if is_fast else "transparent")
                        point_border.append(ACCENT if is_fast else ACCENT_SLATE)
                        point_radius.append(7 if is_fast or is_cur else 5)
                        avg_paces.append(ap)

                    if len(chart_points) >= 2:
                        p_min = min(avg_paces) - 0.3
                        p_max = max(avg_paces) + 0.3

                        _max_visible = 20
                        x_cfg: dict = {
                            "type": "time", "time": {"unit": "month"},
                            "grid": {"display": True},
                        }
                        # Window to last N points; store full range for pan limits
                        x_data_min = chart_points[0]["x"]
                        x_data_max = chart_points[-1]["x"]
                        if len(chart_points) > _max_visible:
                            x_cfg["min"] = chart_points[-_max_visible]["x"]
                        x_cfg["_dataMin"] = x_data_min
                        x_cfg["_dataMax"] = x_data_max

                        hist_cfg_obj = {
                            "type": "scatter",
                            "data": {"datasets": [{
                                "label": "Route History",
                                "data": chart_points,
                                "backgroundColor": point_bg,
                                "pointBorderColor": point_border,
                                "pointBorderWidth": 2,
                                "pointRadius": point_radius,
                                "pointHoverRadius": [r + 2 for r in point_radius],
                                "showLine": True,
                                "borderColor": ACCENT,
                                "borderWidth": 1.5,
                                "borderDash": [4, 4],
                                "fill": False,
                                "tension": 0.3,
                            }]},
                            "options": {
                                "responsive": True, "maintainAspectRatio": False,
                                "interaction": {"mode": "nearest", "intersect": True},
                                "plugins": {"legend": {"display": False}},
                                "scales": {
                                    "x": x_cfg,
                                    "y": {
                                        "reverse": True, "min": p_min, "max": p_max,
                                        "title": {"display": True, "text": "avg pace /mi"},
                                        "grid": {"display": False},
                                    },
                                },
                            },
                            "_meta": {
                                "routeHistoryHover": True,
                                "panOnly": True,
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
