"""Chart builder functions — Chart.js via data-chartcfg + MutationObserver.

Each public function takes the same DataFrame as before but returns an
html.Div with a ``data-chartcfg`` JSON attribute.  ``chartjs-bridge.js``
auto-detects these and renders Chart.js instances.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
import json as _json

from dash import html, dcc

from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, ACCENT_RED,
    SLATE_60, AMBER_60, TEXT_SECONDARY, TEXT_MUTED, BG_CARD,
    LIFT_COLORS, RUN_TYPE_COLORS, WORKOUT_TYPE_COLORS, FONT_MONO,
)
from strava_analytics.metrics import format_pace


# ── helpers ───────────────────────────────────────────────────────────

def _hex_to_rgba(color: str, alpha: float = 0.3) -> str:
    """Convert a hex color to rgba, or re-alpha an existing rgba string."""
    if color.startswith("rgba("):
        # Already rgba — replace the alpha value
        inner = color[5:].rstrip(")")
        parts = inner.split(",")
        return f"rgba({parts[0]},{parts[1]},{parts[2]},{alpha})"
    h = color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _chart_wrap(chart_id: str, cfg: dict, height: int = 400) -> html.Div:
    """Wrapper that stores the Chart.js config in a data attribute.

    ``chartjs-bridge.js`` uses a MutationObserver to detect elements with
    a ``data-chartcfg`` attribute and renders them automatically.
    """
    cfg_json = _json.dumps(cfg, default=str)
    return html.Div([
        html.Div(className="cjs-canvas-box",
                 style={"height": f"{height}px"}),
    ], id=f"{chart_id}-wrap", className="cjs-chart-wrap",
       **{"data-chartcfg": cfg_json})


def _empty_chart(message: str = "No data available", height: int = 200) -> html.Div:
    return html.Div(message, className="cjs-empty", style={"height": f"{height}px"})


def register_chart_callback(chart_id: str) -> None:
    """No-op — rendering is handled by MutationObserver in chartjs-bridge.js."""


def _ts(dt) -> str:
    """Datetime → ISO string for JSON serialisation."""
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _title_cfg(text: str) -> dict:
    return {"display": True, "text": text, "padding": {"bottom": 12}}


def _time_limits(dates: pd.Series, pad_days: int = 7) -> dict:
    """Return min/max for a time axis with padding."""
    return {
        "min": _ts(dates.min() - timedelta(days=pad_days)),
        "max": _ts(dates.max() + timedelta(days=pad_days)),
    }


def _val_limits(vals, pad_frac: float = 0.05, floor=None, ceil=None) -> dict:
    """Return min/max for a value axis with fractional padding."""
    vmin, vmax = float(vals.min()), float(vals.max())
    pad = (vmax - vmin) * pad_frac if vmax != vmin else 1
    lo = vmin - pad if floor is None else max(floor, vmin - pad)
    hi = vmax + pad if ceil is None else min(ceil, vmax + pad)
    return {"min": round(lo, 2), "max": round(hi, 2)}


# ── point size constants ──────────────────────────────────────────────
_PT = 3          # default scatter point radius
_PT_HOVER = 5    # hover radius
_PT_LINE = 3     # point radius on line charts with markers
_PT_LINE_H = 5   # hover radius on line charts


# ── dataset builders ─────────────────────────────────────────────────

def _scatter_ds(data: list[dict], color: str, label: str, **kw) -> dict:
    """Standard scatter-point dataset."""
    d: dict[str, Any] = {
        "label": label,
        "data": data,
        "backgroundColor": _hex_to_rgba(color, 0.4),
        "borderColor": color,
        "borderWidth": 1,
        "pointRadius": _PT,
        "pointHoverRadius": _PT_HOVER,
        "showLine": False,
    }
    d.update(kw)
    return d


def _trend_ds(data: list[dict], color: str, label: str = "30-day avg", **kw) -> dict:
    """Solid trend / rolling-average line."""
    d: dict[str, Any] = {
        "label": label,
        "data": data,
        "borderColor": color,
        "borderWidth": 2.5,
        "pointRadius": 0,
        "showLine": True,
        "fill": False,
        "tension": 0.3,
    }
    d.update(kw)
    return d


def _dashed_ds(data: list[dict], color: str, label: str, **kw) -> dict:
    """Dashed projection / secondary trend line."""
    d: dict[str, Any] = {
        "label": label,
        "data": data,
        "borderColor": color,
        "borderWidth": 2,
        "borderDash": [6, 3],
        "pointRadius": 0,
        "showLine": True,
        "fill": False,
        "tension": 0.3,
    }
    d.update(kw)
    return d


# ── axis builders ────────────────────────────────────────────────────

def _time_x(dates: pd.Series, unit: str = "month", **kw) -> dict:
    """Time x-axis with standard tick config + padding."""
    d: dict[str, Any] = {
        "type": "time",
        "time": {"unit": unit},
        "ticks": {"maxRotation": 0, "maxTicksLimit": 10},
        **_time_limits(dates),
    }
    d.update(kw)
    return d


def _val_y(values: pd.Series | None, label: str, **kw) -> dict:
    """Value y-axis with title + optional auto-padding."""
    d: dict[str, Any] = {"title": {"display": True, "text": label}}
    if values is not None:
        d.update(_val_limits(values))
    d.update(kw)
    return d


# ── config builder ───────────────────────────────────────────────────

def _build_cfg(
    chart_type: str,
    datasets: list[dict],
    title: str,
    x_axis: dict,
    y_axis: dict,
    *,
    meta: dict | None = None,
    legend: bool | dict = True,
    labels: list | None = None,
    extra_scales: dict | None = None,
) -> dict:
    """Assemble a full Chart.js config dict."""
    if legend is True:
        legend_cfg = {"position": "bottom", "labels": {"boxWidth": 12, "padding": 10}}
    elif legend is False:
        legend_cfg = {"display": False}
    else:
        legend_cfg = legend

    data_dict: dict[str, Any] = {"datasets": datasets}
    if labels is not None:
        data_dict["labels"] = labels

    scales: dict[str, Any] = {"x": x_axis, "y": y_axis}
    if extra_scales:
        scales.update(extra_scales)

    cfg: dict[str, Any] = {
        "type": chart_type,
        "data": data_dict,
        "options": {
            "plugins": {
                "title": _title_cfg(title),
                "legend": legend_cfg,
            },
            "scales": scales,
        },
    }
    if meta:
        cfg["_meta"] = meta
    return cfg


def _activity_meta(
    date_strings: dict[int, list[str]],
    *,
    hover_type: str = "run",
    run_meta: dict | None = None,
    lift_meta: dict | None = None,
    dynamic_trend: bool = False,
    trend_idx: int | None = None,
) -> dict:
    """Standard _meta for per-activity charts (click + hover)."""
    m: dict[str, Any] = {
        "clickToScroll": True,
        "hoverCard": True,
        "hoverType": hover_type,
        "dateStrings": date_strings,
    }
    if run_meta is not None:
        m["runMeta"] = run_meta
    if lift_meta is not None:
        m["liftMeta"] = lift_meta
    if dynamic_trend and trend_idx is not None:
        m["dynamicTrendLine"] = True
        m["trendLineIndex"] = trend_idx
    return m


# ── running charts ────────────────────────────────────────────────────

def pace_trend_chart(runs: pd.DataFrame, chart_id: str = "pace-trend", run_meta: dict | None = None) -> html.Div:
    """Scatter of pace over time, colour-coded by run type + 30-day avg."""
    if runs.empty:
        return _empty_chart("No runs to display")

    df = runs.copy()
    df = df[(df["pace_min_per_mi"] >= 6) & (df["pace_min_per_mi"] <= 15)]
    if df.empty:
        return _empty_chart("No runs with valid pace data")

    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")

    datasets = []
    date_strings: dict[int, list[str]] = {}

    if "run_type" in df.columns:
        for rtype in sorted(df["run_type"].unique()):
            subset = df[df["run_type"] == rtype].sort_values("date")
            color = RUN_TYPE_COLORS.get(rtype, TEXT_SECONDARY)
            pts = [{"x": _ts(r["date"]), "y": round(r["pace_min_per_mi"], 2)} for _, r in subset.iterrows()]
            date_strings[len(datasets)] = subset["date_str"].tolist()
            datasets.append(_scatter_ds(pts, color, rtype.title()))
    else:
        pts = [{"x": _ts(r["date"]), "y": round(r["pace_min_per_mi"], 2)} for _, r in df.iterrows()]
        datasets.append(_scatter_ds(pts, ACCENT, "Runs"))
        date_strings[0] = df["date_str"].tolist()

    # 30-day rolling average (recalculated dynamically by JS when legend items toggled)
    trend_idx = len(datasets)
    df_sorted = df.sort_values("date")
    rolling = df_sorted.set_index("date")["pace_min_per_mi"].rolling("30D").mean()
    trend_pts = [{"x": _ts(d), "y": round(v, 2)} for d, v in zip(rolling.index, rolling.values) if pd.notna(v)]
    datasets.append(_trend_ds(trend_pts, ACCENT))

    cfg = _build_cfg(
        "scatter", datasets, "Pace Trend",
        _time_x(df["date"]),
        _val_y(df["pace_min_per_mi"], "Pace (min/mi)", reverse=True, ticks={"stepSize": 0.5}),
        meta=_activity_meta(date_strings, run_meta=run_meta or {},
                            dynamic_trend=True, trend_idx=trend_idx),
        legend={"position": "right", "labels": {"boxWidth": 12, "padding": 10}},
    )
    return _chart_wrap(chart_id, cfg, height=400)


def weekly_mileage_chart(runs: pd.DataFrame, chart_id: str = "weekly-miles") -> html.Div:
    """Bar chart of weekly miles."""
    if runs.empty:
        return _empty_chart("No runs for weekly mileage")

    df = runs.copy()
    df["week_start"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time)
    weekly = df.groupby("week_start")["distance_mi"].sum().reset_index()
    weekly = weekly.sort_values("week_start")

    cfg = _build_cfg(
        "bar",
        [{"label": "Miles", "data": [round(v, 1) for v in weekly["distance_mi"]],
          "backgroundColor": ACCENT, "borderRadius": 2}],
        "Weekly Mileage",
        {"ticks": {"maxRotation": 0}},
        _val_y(None, "Miles", beginAtZero=True, min=0,
               max=round(float(weekly["distance_mi"].max()) * 1.05, 1)),
        legend=False,
        labels=[d.strftime("%b %d") for d in weekly["week_start"]],
    )
    return _chart_wrap(chart_id, cfg, height=320)


def aerobic_efficiency_chart(runs: pd.DataFrame, chart_id: str = "hr-vs-pace",
                              run_meta: dict | None = None) -> html.Div:
    """Aerobic efficiency: estimated pace at a fixed reference HR over time.

    For each run, computes what pace you'd hold at 140 bpm (Z2 ceiling for
    max_hr=200) by normalizing: efficiency = pace × (ref_hr / adjusted_hr).
    Lower = faster at the same HR = better aerobic fitness.
    Includes a 30-day rolling average trend line.
    """
    if runs.empty:
        return _empty_chart("No runs with heart rate data")

    df = runs[runs["adjusted_hr"].notna()].copy()
    df = df[(df["pace_min_per_mi"] >= 6) & (df["pace_min_per_mi"] <= 15)]
    df = df[df["adjusted_hr"] > 100]  # filter out sensor glitches
    if df.empty:
        return _empty_chart("No runs with valid HR data")

    # Reference HR = 70% of max (Z2 ceiling). Use estimated_max_hr if available.
    ref_hr = 140
    if "estimated_max_hr" in df.columns:
        max_hr = df["estimated_max_hr"].iloc[0]
        ref_hr = int(max_hr * 0.70)

    # Efficiency: what pace would this run be at reference HR?
    # Linear approximation: pace_at_ref = pace × (ref_hr / actual_hr)
    df["efficiency"] = df["pace_min_per_mi"] * (ref_hr / df["adjusted_hr"])
    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.sort_values("date")

    # Filter extreme outliers
    q01, q99 = df["efficiency"].quantile(0.01), df["efficiency"].quantile(0.99)
    df = df[(df["efficiency"] >= q01) & (df["efficiency"] <= q99)]

    pts = [{"x": _ts(r["date"]), "y": round(r["efficiency"], 2)} for _, r in df.iterrows()]
    date_strings: dict[int, list[str]] = {0: df["date_str"].tolist()}
    datasets = [_scatter_ds(pts, ACCENT_SLATE, "_runs")]

    # 30-day rolling average trend line
    trend_idx = len(datasets)
    rolling = df.set_index("date")["efficiency"].rolling("30D").mean()
    trend_pts = [{"x": _ts(d), "y": round(v, 2)} for d, v in zip(rolling.index, rolling.values) if pd.notna(v)]
    datasets.append(_trend_ds(trend_pts, ACCENT))

    cfg = _build_cfg(
        "scatter", datasets, f"Aerobic Efficiency (pace @ {ref_hr} bpm)",
        _time_x(df["date"]),
        _val_y(df["efficiency"], f"Pace @ {ref_hr} bpm (min/mi)", reverse=True, ticks={"stepSize": 0.5}),
        meta=_activity_meta(date_strings, run_meta=run_meta or {}),
        legend=False,
    )
    return _chart_wrap(chart_id, cfg, height=320)


# ── HR analysis charts ───────────────────────────────────────────────

from strava_analytics.web.theme import HR_ZONE_COLORS as _HR_ZONE_COLORS
from strava_analytics.web.theme import HR_ZONE_LABELS as _HR_ZONE_LABELS


def hr_zone_distribution_chart(runs: pd.DataFrame, chart_id: str = "hr-zones") -> html.Div:
    """Horizontal bar chart of total time spent in each HR zone across all runs."""
    zone_cols = [f"zone_{z}_s" for z in range(1, 6)]
    has_zone_times = all(c in runs.columns for c in zone_cols)

    if not has_zone_times:
        return _empty_chart("No HR zone data")

    df = runs[runs[zone_cols[0]].notna()].copy()
    if df.empty:
        return _empty_chart("No HR zone data")

    # Sum per-second zone times across all activities, convert to hours
    hours = [round(df[col].sum() / 3600, 1) for col in zone_cols]
    colors = [_HR_ZONE_COLORS.get(z, TEXT_MUTED) for z in range(1, 6)]

    max_val = max(hours) if hours else 0
    cfg = _build_cfg(
        "bar",
        [{"label": "Hours", "data": hours, "backgroundColor": colors, "borderRadius": 2}],
        "Time in HR Zones",
        _val_y(None, "Hours", beginAtZero=True, min=0,
               max=round(max_val * 1.15, 1) if max_val > 0 else 10),
        {},
        legend=False,
        labels=_HR_ZONE_LABELS,
    )
    cfg["options"]["indexAxis"] = "y"
    return _chart_wrap(chart_id, cfg, height=250)


def hr_over_time_chart(runs: pd.DataFrame, chart_id: str = "hr-trend",
                       run_meta: dict | None = None) -> html.Div:
    """Scatter of adjusted HR over time with 30-day rolling avg."""
    if "adjusted_hr" not in runs.columns:
        return _empty_chart("No HR data")

    df = runs[runs["adjusted_hr"].notna()].copy()
    df = df[(df["adjusted_hr"] > 100) & (df["adjusted_hr"] < 220)]
    if df.empty:
        return _empty_chart("No valid HR data")

    df = df.sort_values("date")
    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")

    pts = [{"x": _ts(r["date"]), "y": round(r["adjusted_hr"], 1)} for _, r in df.iterrows()]
    date_strings: dict[int, list[str]] = {0: df["date_str"].tolist()}
    datasets = [_scatter_ds(pts, ACCENT_SLATE, "_runs")]

    rolling = df.set_index("date")["adjusted_hr"].rolling("30D").mean()
    trend_pts = [{"x": _ts(d), "y": round(v, 1)} for d, v in zip(rolling.index, rolling.values) if pd.notna(v)]
    datasets.append(_trend_ds(trend_pts, ACCENT))

    cfg = _build_cfg(
        "scatter", datasets, "Adjusted HR Over Time",
        _time_x(df["date"]),
        _val_y(df["adjusted_hr"], "Adjusted HR (bpm)"),
        meta=_activity_meta(date_strings, run_meta=run_meta),
        legend=False,
    )
    return _chart_wrap(chart_id, cfg, height=280)


# ── stroller chart ───────────────────────────────────────────────────

def stroller_pace_chart(runs: pd.DataFrame, chart_id: str = "stroller-pace",
                        run_meta: dict | None = None) -> html.Div:
    """Scatter: stroller vs solo pace over time with trend lines."""
    if "with_kid" not in runs.columns:
        return _empty_chart("No stroller data")

    stroller = runs[runs["with_kid"] == True].copy()
    solo = runs[runs["with_kid"] == False].copy()
    if stroller.empty or len(stroller) < 3:
        return _empty_chart("Not enough stroller runs")

    both = pd.concat([stroller, solo])
    both = both[(both["pace_min_per_mi"] >= 6) & (both["pace_min_per_mi"] <= 15)]
    both["date_str"] = both["date"].dt.strftime("%Y-%m-%d")
    stroller = both[both["with_kid"] == True].sort_values("date")
    solo = both[both["with_kid"] == False].sort_values("date")

    solo_pts = [{"x": _ts(r["date"]), "y": round(r["pace_min_per_mi"], 2)} for _, r in solo.iterrows()]
    str_pts = [{"x": _ts(r["date"]), "y": round(r["pace_min_per_mi"], 2)} for _, r in stroller.iterrows()]
    date_strings: dict[int, list[str]] = {
        0: solo["date_str"].tolist(),
        1: stroller["date_str"].tolist(),
    }

    datasets = [
        _scatter_ds(solo_pts, ACCENT_SLATE, "Solo"),
        _scatter_ds(str_pts, ACCENT, "Stroller"),
    ]

    # Trend lines
    if len(solo) >= 3:
        solo_roll = solo.set_index("date")["pace_min_per_mi"].rolling("30D").mean()
        roll_pts = [{"x": _ts(d), "y": round(v, 2)} for d, v in zip(solo_roll.index, solo_roll.values) if pd.notna(v)]
        datasets.append(_dashed_ds(roll_pts, ACCENT_SLATE, "_solo_trend"))
    if len(stroller) >= 3:
        str_roll = stroller.set_index("date")["pace_min_per_mi"].rolling("60D").mean()
        roll_pts = [{"x": _ts(d), "y": round(v, 2)} for d, v in zip(str_roll.index, str_roll.values) if pd.notna(v)]
        datasets.append(_dashed_ds(roll_pts, ACCENT, "_stroller_trend"))

    cfg = _build_cfg(
        "scatter", datasets, "Stroller vs Solo Pace Over Time",
        _time_x(both["date"]),
        _val_y(both["pace_min_per_mi"], "Pace (min/mi)", reverse=True, ticks={"stepSize": 0.5}),
        meta=_activity_meta(date_strings, run_meta=run_meta),
    )
    return _chart_wrap(chart_id, cfg, height=350)


# ── heat vs pace chart ───────────────────────────────────────────────

def heat_vs_pace_chart(runs: pd.DataFrame, chart_id: str = "heat-pace",
                       run_meta: dict | None = None) -> html.Div:
    """Scatter of temperature vs pace, color-coded by run type."""
    if "weather_temp_f" not in runs.columns:
        return _empty_chart("No temperature data")

    df = runs[
        runs["weather_temp_f"].notna()
        & runs["pace_min_per_mi"].between(6, 15)
    ].copy()
    if len(df) < 10:
        return _empty_chart("Not enough runs with temperature data")

    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")

    datasets = []
    date_strings: dict[int, list[str]] = {}
    if "run_type" in df.columns:
        for rtype in sorted(df["run_type"].unique()):
            subset = df[df["run_type"] == rtype]
            color = RUN_TYPE_COLORS.get(rtype, TEXT_SECONDARY)
            # Embed _dateStr in each point for click-to-modal (x-axis is temp, not time)
            pts = [{"x": round(r["weather_temp_f"], 1), "y": round(r["pace_min_per_mi"], 2),
                    "_dateStr": r["date_str"]} for _, r in subset.iterrows()]
            datasets.append(_scatter_ds(pts, color, rtype.title()))
    else:
        pts = [{"x": round(r["weather_temp_f"], 1), "y": round(r["pace_min_per_mi"], 2),
                "_dateStr": r["date_str"]} for _, r in df.iterrows()]
        datasets.append(_scatter_ds(pts, ACCENT, "Runs"))

    # Linear trend line
    import numpy as np
    valid = df[["weather_temp_f", "pace_min_per_mi"]].dropna()
    if len(valid) >= 10:
        coeffs = np.polyfit(valid["weather_temp_f"], valid["pace_min_per_mi"], 1)
        x_min, x_max = float(valid["weather_temp_f"].min()), float(valid["weather_temp_f"].max())
        trend_pts = [
            {"x": round(x_min, 1), "y": round(coeffs[0] * x_min + coeffs[1], 2)},
            {"x": round(x_max, 1), "y": round(coeffs[0] * x_max + coeffs[1], 2)},
        ]
        datasets.append(_dashed_ds(trend_pts, ACCENT, "_trend"))

    meta: dict[str, Any] = {"clickToScroll": True, "hoverCard": True, "hoverType": "run",
                             "runMeta": run_meta or {}, "dateStrings": date_strings}

    cfg = _build_cfg(
        "scatter", datasets, "Temperature vs Pace",
        _val_y(df["weather_temp_f"], "Temperature (\u00b0F)"),
        _val_y(df["pace_min_per_mi"], "Pace (min/mi)", reverse=True, ticks={"stepSize": 0.5}),
        meta=meta,
    )
    return _chart_wrap(chart_id, cfg, height=350)


def fatigue_chart(df: pd.DataFrame, chart_id: str = "fatigue") -> html.Div:
    """Training load: ATL, CTL, TSB with area fill."""
    if "acute_load_7d" not in df.columns:
        return _empty_chart("No training load data available")
    has = df[df["acute_load_7d"].notna()].copy()
    if has.empty:
        return _empty_chart("No training load data available")

    labels = [_ts(d) for d in has["date"]]

    ctl_data = [round(v, 1) if pd.notna(v) else None for v in has["chronic_load_28d"]]
    atl_data = [round(v, 1) if pd.notna(v) else None for v in has["acute_load_7d"]]
    tsb_data = [round(v, 1) if pd.notna(v) else None for v in has["freshness"]]

    datasets = [
        _trend_ds(ctl_data, ACCENT, "Fitness (CTL)", borderWidth=2.5),
        _trend_ds(atl_data, ACCENT_RED, "Fatigue (ATL)", borderWidth=2.5),
        _trend_ds(tsb_data, ACCENT_AMBER, "Form (TSB)", borderWidth=2.5,
                  fill="origin", backgroundColor=_hex_to_rgba(ACCENT_AMBER, 0.1)),
    ]

    all_y = pd.concat([has["chronic_load_28d"], has["acute_load_7d"], has["freshness"]]).dropna()

    cfg = _build_cfg(
        "line", datasets, "Training Load & Freshness",
        _time_x(has["date"], unit="week", ticks={"maxTicksLimit": 8, "autoSkip": True, "maxRotation": 0}),
        _val_y(all_y, "Load / Freshness"),
        labels=labels,
        legend={"position": "bottom"},
    )
    return _chart_wrap(chart_id, cfg, height=400)


# ── lifting charts ────────────────────────────────────────────────────

def lift_progression_chart(df: pd.DataFrame, chart_id: str = "lift-prog",
                           lift_meta: dict | None = None) -> html.Div:
    """Line chart of working weights over time."""
    lifts_data = df[df["type"] == "Weight Training"].copy()
    if lifts_data.empty:
        return _empty_chart("No weight training sessions found")

    lifts_data["date_str"] = lifts_data["date"].dt.strftime("%Y-%m-%d")

    datasets = []
    date_strings: dict[int, list[str]] = {}
    all_weights: list[float] = []
    all_dates: list = []
    for lift, color in LIFT_COLORS.items():
        col = f"{lift}_weight"
        if col not in lifts_data.columns:
            continue
        subset = lifts_data[lifts_data[col].notna() & (lifts_data[col] > 0)].sort_values("date")
        if subset.empty:
            continue
        all_weights.extend(subset[col].tolist())
        all_dates.extend(subset["date"].tolist())
        pts = [{"x": _ts(r["date"]), "y": round(float(r[col]), 1)} for _, r in subset.iterrows()]
        date_strings[len(datasets)] = subset["date_str"].tolist()
        datasets.append(_scatter_ds(pts, color, lift.title(),
                                    borderWidth=2.5, pointRadius=_PT_LINE,
                                    pointHoverRadius=_PT_LINE_H, backgroundColor=color,
                                    showLine=True, tension=0.2, fill=False))

    if not datasets:
        return _empty_chart("No weight data for primary lifts")

    w_series = pd.Series(all_weights)
    date_series = pd.Series(all_dates)

    cfg = _build_cfg(
        "scatter", datasets, "Working Weight Progression",
        _time_x(date_series, unit="week"),
        _val_y(w_series, "Weight (lbs)"),
        meta=_activity_meta(date_strings, hover_type="lift", lift_meta=lift_meta),
    )
    return _chart_wrap(chart_id, cfg, height=400)


def volume_chart(df: pd.DataFrame, chart_id: str = "volume") -> html.Div:
    """Stacked bar chart of volume per lift."""
    lifts_data = df[df["type"] == "Weight Training"].copy()
    if lifts_data.empty:
        return _empty_chart("No training volume data")

    lifts_data = lifts_data.sort_values("date")

    # Filter out sessions with no primary lift volume (accessory-only days)
    vol_cols = [f"{lift}_volume" for lift in LIFT_COLORS if f"{lift}_volume" in lifts_data.columns]
    if vol_cols:
        lifts_data = lifts_data[lifts_data[vol_cols].fillna(0).sum(axis=1) > 0]
    if lifts_data.empty:
        return _empty_chart("No training volume data")

    # Month-based labels: show "Mon 'YY" for first session in each month, blank otherwise
    labels: list[str] = []
    seen_months: set[str] = set()
    for d in lifts_data["date"]:
        key = d.strftime("%Y-%m")
        if key not in seen_months:
            seen_months.add(key)
            labels.append(d.strftime("%b '%y"))
        else:
            labels.append("")

    datasets = []
    stacked_totals: list[float] = [0.0] * len(lifts_data)
    for lift, color in LIFT_COLORS.items():
        col = f"{lift}_volume"
        if col not in lifts_data.columns:
            continue
        vals = lifts_data[col].fillna(0).tolist()
        if all(v == 0 for v in vals):
            continue
        for i, v in enumerate(vals):
            stacked_totals[i] += v
        datasets.append({
            "label": lift.title(),
            "data": [round(v, 0) for v in vals],
            "backgroundColor": _hex_to_rgba(color, 0.8),
            "borderColor": color,
            "borderWidth": 1,
        })

    if not datasets:
        return _empty_chart("No volume data for primary lifts")

    y_max = round(max(stacked_totals) * 1.05) if stacked_totals else None

    cfg = _build_cfg(
        "bar", datasets, "Training Volume",
        {"stacked": True},
        _val_y(None, "Volume (sets x reps x weight)",
               stacked=True, beginAtZero=True, min=0, max=y_max),
        labels=labels,
    )
    return _chart_wrap(chart_id, cfg, height=350)


def onerm_progression_chart(
    progression_df: pd.DataFrame,
    lift_name: str,
    color: str,
    chart_id: str | None = None,
    lift_meta: dict | None = None,
) -> html.Div:
    """Estimated 1RM with log-curve fit trend line."""
    from strava_analytics.strength_model import fit_1rm_curve
    import math

    if chart_id is None:
        chart_id = f"onerm-{lift_name.lower().replace(' ', '-')}"

    if progression_df.empty:
        return _empty_chart(f"No 1RM data for {lift_name}")

    df = progression_df.sort_values("date").copy()
    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    fit = fit_1rm_curve(df)

    labels = [_ts(d) for d in df["date"]]

    # Compute log-curve trend line: 1RM(w) = a * ln(w+1) + b
    first_date = df["date"].min()
    weeks = (df["date"] - first_date).dt.total_seconds() / (7 * 86400)
    trend = [round(fit["a"] * math.log(w + 1) + fit["b"], 1) for w in weeks]

    datasets = [
        _scatter_ds([round(float(v), 1) for v in df["estimated_1rm"]], color,
                    "Session estimate", borderWidth=0),
        _trend_ds(trend, color, "Trend (log fit)", borderWidth=3, backgroundColor=color),
    ]

    # Highlight tested maxes
    if "is_test" in df.columns:
        tests = df[df["is_test"] == True]
        if not tests.empty:
            test_data = [None] * len(df)
            for idx in tests.index:
                pos = df.index.get_loc(idx)
                test_data[pos] = round(float(tests.loc[idx, "estimated_1rm"]), 1)
            datasets.append({
                "label": "Tested max",
                "data": test_data,
                "backgroundColor": BG_CARD,
                "borderColor": color,
                "borderWidth": 2,
                "pointRadius": 6,
                "pointHoverRadius": 8,
                "pointStyle": "rectRot",
                "showLine": False,
            })

    date_strings: dict[int, list[str]] = {0: df["date_str"].tolist()}

    cfg = _build_cfg(
        "line", datasets, f"{lift_name} — Estimated 1RM (R\u00b2={fit['r_squared']:.2f})",
        _time_x(df["date"], unit="week"),
        _val_y(df["estimated_1rm"], "Est. 1RM (lbs)"),
        meta=_activity_meta(date_strings, hover_type="lift", lift_meta=lift_meta),
        legend={"display": True, "position": "bottom",
                "labels": {"boxWidth": 12, "padding": 8, "usePointStyle": True}},
        labels=labels,
    )
    return _chart_wrap(chart_id, cfg, height=350)


# ── race predictions (4 distances) ────────────────────────────────────

_RACE_DISTANCES = [
    (5_000,  "5K"),
    (10_000, "10K"),
    (21_097, "Half Marathon"),
    (42_195, "Marathon"),
]


def _single_race_chart(
    runs: pd.DataFrame, target_m: int, label: str, chart_id: str,
    best_efforts: pd.DataFrame | None = None,
    projected: list | None = None,
) -> html.Div:
    """Build a race prediction chart using Critical Speed model + best efforts.

    projected: optional list of {"date": Timestamp, "time_min": float} for
    future race time projections (rendered as dashed line).
    """
    from strava_analytics.critical_speed import fit_critical_speed, predict_time_cs
    from strava_analytics.vo2max import daniels_vdot, vdot_to_race_time

    if best_efforts is None or best_efforts.empty:
        return _empty_chart(f"Not enough data for {label}", height=280)

    # Fit CS model for the predicted time line
    cs = fit_critical_speed(best_efforts)
    cs_time_min = predict_time_cs(cs["cs_m_per_s"], cs["d_prime_m"], target_m) / 60.0 if cs["cs_m_per_s"] > 0 else 0

    # Build race-equivalent times from effective VDOT (adjusted for conditions)
    # or raw VDOT as fallback. Every run contributes a data point.
    has_ev = "effective_vdot" in runs.columns
    filtered = runs[(runs["distance_mi"] >= 2.0) &
                     (runs["pace_min_per_mi"] >= 6) &
                     (runs["pace_min_per_mi"] <= 14)].copy()

    rows = []
    for _, r in filtered.sort_values("date").iterrows():
        dist_m = r.get("distance_m", 0)
        time_s = r.get("moving_time_s", 0)
        if dist_m <= 0 or time_s <= 0:
            continue

        # Prefer effective VDOT (heat/stroller/elevation adjusted)
        ev = r.get("effective_vdot") if has_ev else None
        if pd.notna(ev) and ev > 0:
            vdot = ev
        else:
            vdot = daniels_vdot(dist_m, time_s / 60.0)

        est_time = vdot_to_race_time(vdot, target_m)
        rows.append({
            "date": r["date"],
            "est_time_min": round(est_time, 2),
            "run_type": r.get("run_type", ""),
            "date_str": r["date"].strftime("%Y-%m-%d"),
        })

    if not rows:
        return _empty_chart(f"Not enough data for {label}", height=280)

    edf = pd.DataFrame(rows)

    # All runs as uniform dots
    run_pts = [{"x": _ts(r["date"]), "y": round(r["est_time_min"], 2)} for _, r in edf.iterrows()]
    date_strings: dict[int, list[str]] = {0: edf["date_str"].tolist()}
    datasets = [_scatter_ds(run_pts, ACCENT_SLATE, "Runs")]

    # Fitness trend: 60-day rolling minimum across all runs
    sorted_edf = edf.sort_values("date").copy()
    sorted_edf["rolling_best"] = (
        sorted_edf.set_index("date")["est_time_min"]
        .rolling("60D", min_periods=3).quantile(0.1)
        .values
    )
    trend = sorted_edf.dropna(subset=["rolling_best"])
    trend = trend.iloc[::max(1, len(trend) // 60)]
    if not trend.empty:
        trend_pts = [{"x": _ts(r["date"]), "y": round(r["rolling_best"], 2)} for _, r in trend.iterrows()]
        datasets.append(_trend_ds(trend_pts, ACCENT, "Fitness trend", borderWidth=2, tension=0.4))

    # Projected dashed line (future race time estimates)
    if projected:
        last_date = edf["date"].max()
        last_trend_val = trend.iloc[-1]["rolling_best"] if not trend.empty else edf["est_time_min"].median()
        proj_pts = [{"x": _ts(last_date), "y": round(last_trend_val, 2)}]
        proj_pts += [{"x": _ts(p["date"]), "y": round(p["time_min"], 2)} for p in projected]
        datasets.append(_dashed_ds(proj_pts, ACCENT, "Projected", borderDash=[6, 4]))

    y_label = f"{label} Time (min)" if target_m <= 10_000 else f"{label} Time (hr:min)"

    # Extend x-axis to include projected dates if present
    all_dates = edf["date"]
    if projected:
        proj_dates = pd.Series([p["date"] for p in projected])
        all_dates = pd.concat([all_dates, proj_dates])

    cfg = _build_cfg(
        "scatter", datasets, label,
        _time_x(all_dates),
        _val_y(edf["est_time_min"], y_label, reverse=True),
        meta=_activity_meta(date_strings),
        legend={"display": True, "position": "bottom",
                "labels": {"boxWidth": 10, "padding": 6, "usePointStyle": True}},
    )
    return _chart_wrap(chart_id, cfg, height=280)


def race_predictions_chart(runs: pd.DataFrame, chart_id: str = "race-pred",
                            best_efforts: pd.DataFrame | None = None,
                            projected_by_distance: dict | None = None) -> html.Div:
    """Tabbed race predictions — one CS-based chart per distance.

    projected_by_distance: optional dict mapping target_m (int) to list of
    {"date": Timestamp, "time_min": float} for dashed projection lines.
    """
    if runs.empty:
        return _empty_chart("No runs for race prediction")

    panels = []
    tab_buttons = []
    for i, (target_m, label) in enumerate(_RACE_DISTANCES):
        sub_id = f"{chart_id}-{label.lower().replace(' ', '-')}"
        is_default = (i == 0)
        proj = projected_by_distance.get(target_m) if projected_by_distance else None
        panels.append(html.Div(
            _single_race_chart(runs, target_m, label, sub_id, best_efforts, projected=proj),
            id=f"{chart_id}-panel-{i}",
            className="race-tab-panel",
            style={"display": "block" if is_default else "none"},
        ))
        tab_buttons.append(html.Button(
            label,
            className="race-tab-btn race-tab-active" if is_default else "race-tab-btn",
            **{"data-tab-index": str(i), "data-chart-id": chart_id},
        ))

    tabs_bar = html.Div(tab_buttons, className="race-tabs-bar",
                         style={"display": "flex", "gap": "0",
                                "marginBottom": "12px"})

    return html.Div([tabs_bar, *panels], id=f"{chart_id}-tabs")


# ── monthly volume ────────────────────────────────────────────────────

def monthly_volume_chart(df: pd.DataFrame, chart_id: str = "monthly-vol") -> html.Div:
    """Dual-axis: monthly distance bars + activity count line."""
    if df.empty:
        return _empty_chart("No data for monthly volume")

    monthly = df.groupby(df["date"].dt.to_period("M")).agg(
        miles=("distance_mi", "sum"),
        count=("activity_id", "count"),
    ).reset_index()
    monthly["label"] = monthly["date"].astype(str)
    monthly = monthly.sort_values("date")

    datasets = [
        {"label": "Miles", "data": [round(v, 1) for v in monthly["miles"]],
         "backgroundColor": ACCENT, "borderRadius": 2, "yAxisID": "y", "order": 2},
        {"label": "Activities", "data": monthly["count"].tolist(),
         "type": "line", "borderColor": ACCENT_SLATE, "backgroundColor": ACCENT_SLATE,
         "borderWidth": 2, "pointRadius": _PT_LINE, "yAxisID": "y1", "fill": False, "order": 1},
    ]

    cfg = _build_cfg(
        "bar", datasets, "Monthly Volume",
        {"ticks": {"maxRotation": 0}},
        _val_y(None, "Miles", beginAtZero=True, min=0, position="left",
               max=round(float(monthly["miles"].max()) * 1.1, 1)),
        labels=monthly["label"].tolist(),
        legend={"position": "bottom"},
        extra_scales={"y1": {
            "beginAtZero": True, "min": 0,
            "title": {"display": True, "text": "Activities"},
            "position": "right", "grid": {"drawOnChartArea": False},
            "max": int(monthly["count"].max() + 2),
        }},
    )
    return _chart_wrap(chart_id, cfg, height=350)


# ── plan calendar (pure CSS grid) ────────────────────────────────────

def plan_calendar_chart(plan_rows: list[dict]) -> html.Div:
    """Calendar grid — pure HTML/CSS, no Chart.js."""
    if not plan_rows:
        return _empty_chart("No training plan data")

    df = pd.DataFrame(plan_rows)
    df["date"] = pd.to_datetime(df["date"])
    df["weekday"] = df["date"].dt.weekday

    weeks = sorted(df["week"].unique())
    n_weeks = len(weeks)

    type_letter = {"lift": "L", "run": "R", "rest": "-", "obstacle": "O", "mobility": "M"}

    header = [html.Div("", className="plan-calendar-header")]
    for w in weeks:
        header.append(html.Div(f"Wk {w}", className="plan-calendar-header"))

    rows = [html.Div(header, style={
        "display": "grid",
        "gridTemplateColumns": f"40px repeat({n_weeks}, 32px)",
        "gap": "4px",
        "justifyContent": "center",
    })]

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for day_idx, day_name in enumerate(day_names):
        row_cells = [html.Div(day_name, className="plan-calendar-header",
                              style={"lineHeight": "32px"})]
        for w in weeks:
            matches = df[(df["week"] == w) & (df["weekday"] == day_idx)]
            if matches.empty:
                row_cells.append(html.Div(style={"width": "32px", "height": "32px"}))
            else:
                first = matches.iloc[0]
                wtype = first["type"]
                color = WORKOUT_TYPE_COLORS.get(wtype, TEXT_MUTED)
                letter = type_letter.get(wtype, wtype[0].upper() if wtype else "?")
                title_text = f"{first['title']} — {first['day_name']}, {first['date'].strftime('%b %d')} — {first['intensity']}"

                if len(matches) > 1:
                    letter = "+".join(
                        type_letter.get(r["type"], "?") for _, r in matches.iterrows()
                    )

                row_cells.append(html.Div(
                    letter,
                    className="plan-calendar-cell",
                    title=title_text,
                    style={"backgroundColor": color},
                ))
        rows.append(html.Div(row_cells, style={
            "display": "grid",
            "gridTemplateColumns": f"40px repeat({n_weeks}, 32px)",
            "gap": "4px",
            "justifyContent": "center",
        }))

    return html.Div(rows, style={"marginBottom": "8px"})


# ── training load (weekly intensity-weighted) ────────────────────────

def weekly_training_load_chart(df: pd.DataFrame, chart_id: str = "weekly-load") -> html.Div:
    """Weekly training load bars with 4-week rolling average trend line."""
    from strava_analytics.fitness import weekly_training_load

    weekly = weekly_training_load(df)
    if weekly.empty:
        return _empty_chart("No training load data")

    # Show quarter labels only (Jan, Apr, Jul, Oct) for clean x-axis
    labels = []
    for w in weekly["week"]:
        dt = w.start_time
        if dt.month in (1, 4, 7, 10) and dt.day <= 7:
            labels.append(dt.strftime("%b '%y"))
        else:
            labels.append("")

    datasets = [
        {"label": "Weekly Load", "data": [round(v, 1) for v in weekly["load"]],
         "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.7), "borderColor": ACCENT_SLATE,
         "borderWidth": 1, "borderRadius": 2, "order": 2},
        {"label": "4-Week Avg", "data": [round(v, 1) if pd.notna(v) else None for v in weekly["trend"]],
         "type": "line", "borderColor": ACCENT, "borderWidth": 2,
         "pointRadius": 0, "fill": False, "tension": 0.3, "order": 1},
    ]

    cfg = _build_cfg(
        "bar", datasets, "Weekly Training Load",
        {"ticks": {"maxRotation": 0, "autoSkip": True}},
        _val_y(None, "Training Stress", beginAtZero=True, min=0),
        labels=labels,
        legend={"position": "bottom"},
    )
    return _chart_wrap(chart_id, cfg, height=350)


# ── year in review monthly breakdown ─────────────────────────────────

def year_monthly_chart(summary: dict, chart_id: str = "year-monthly") -> html.Div:
    """Bar chart of monthly miles for year in review."""
    monthly = summary.get("monthly", [])
    if not monthly:
        return _empty_chart("No monthly data")

    import calendar as _cal
    from datetime import date as _date
    current_month = _date.today().month
    current_year = _date.today().year
    chart_year = summary.get("year", current_year)
    # Only show months up to the current month if viewing the current year
    if chart_year == current_year:
        monthly = [m for m in monthly if m["month"] <= current_month]
    labels = [_cal.month_abbr[m["month"]] for m in monthly]
    miles = [m["miles"] for m in monthly]
    counts = [m["activities"] for m in monthly]

    datasets = [
        {"label": "Miles", "data": miles, "backgroundColor": ACCENT,
         "borderRadius": 2, "yAxisID": "y", "order": 2},
        {"label": "Activities", "data": counts, "type": "line",
         "borderColor": ACCENT_SLATE, "borderWidth": 2,
         "pointRadius": _PT_LINE, "yAxisID": "y1", "fill": False, "order": 1},
    ]

    cfg = _build_cfg(
        "bar", datasets, f"{summary.get('year', '')} Month by Month",
        {}, _val_y(None, "Miles", beginAtZero=True, min=0, position="left"),
        labels=labels,
        legend={"position": "bottom"},
        extra_scales={"y1": {
            "beginAtZero": True, "min": 0,
            "title": {"display": True, "text": "Activities"},
            "position": "right", "grid": {"drawOnChartArea": False},
        }},
    )
    return _chart_wrap(chart_id, cfg, height=300)


# ── plan page charts ─────────────────────────────────────────────────

def fitness_freshness_chart(fitness_df: pd.DataFrame,
                             race_dates: list | None = None,
                             chart_id: str = "fitness-freshness") -> html.Div:
    """CTL/ATL/TSB line chart with optional race date vertical markers."""
    if fitness_df.empty:
        return _empty_chart("No fitness data available")

    projected_mask = fitness_df.get("projected", pd.Series(False, index=fitness_df.index))

    # Historical data
    hist = fitness_df[~projected_mask]
    proj = fitness_df[projected_mask]

    datasets = []

    # Historical: CTL, ATL, TSB
    if not hist.empty:
        ctl_pts = [{"x": _ts(r["date"]), "y": round(r["ctl"], 1)} for _, r in hist.iterrows()]
        atl_pts = [{"x": _ts(r["date"]), "y": round(r["atl"], 1)} for _, r in hist.iterrows()]
        tsb_pts = [{"x": _ts(r["date"]), "y": round(r["tsb"], 1)} for _, r in hist.iterrows()]
        datasets.append(_trend_ds(ctl_pts, ACCENT, "Fitness (CTL)", borderWidth=2.5))
        datasets.append(_trend_ds(atl_pts, ACCENT_RED, "Fatigue (ATL)", borderWidth=2.5))
        datasets.append(_trend_ds(tsb_pts, ACCENT_AMBER, "Form (TSB)", borderWidth=2,
                                  fill=True, backgroundColor=_hex_to_rgba(ACCENT_AMBER, 0.15)))

    # Projected (dashed)
    if not proj.empty:
        pctl = [{"x": _ts(r["date"]), "y": round(r["ctl"], 1)} for _, r in proj.iterrows()]
        patl = [{"x": _ts(r["date"]), "y": round(r["atl"], 1)} for _, r in proj.iterrows()]
        ptsb = [{"x": _ts(r["date"]), "y": round(r["tsb"], 1)} for _, r in proj.iterrows()]
        datasets.append(_dashed_ds(pctl, ACCENT, "Projected CTL"))
        datasets.append(_dashed_ds(patl, ACCENT_RED, "Projected ATL"))
        datasets.append(_dashed_ds(ptsb, ACCENT_AMBER, "Projected TSB", borderWidth=2))

    race_markers = [{"date": _ts(d), "label": ""} for d in race_dates] if race_dates else []

    cfg = _build_cfg(
        "scatter", datasets, "Fitness / Freshness",
        _time_x(fitness_df["date"]),
        _val_y(None, "Load / Form"),
        meta={"raceMarkers": race_markers},
    )
    return _chart_wrap(chart_id, cfg, height=350)


def mileage_progression_chart(mileage_df: pd.DataFrame,
                               chart_id: str = "mileage-progression") -> html.Div:
    """Bar chart of actual vs planned weekly miles."""
    if mileage_df.empty:
        return _empty_chart("No mileage data")

    bar_labels = [f"Wk {r['week_num']}" for _, r in mileage_df.iterrows()]

    datasets = [
        {"label": "Planned", "data": mileage_df["planned_miles"].tolist(),
         "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.3), "borderColor": ACCENT_SLATE,
         "borderWidth": 1, "order": 2},
        {"label": "Actual", "data": mileage_df["actual_miles"].tolist(),
         "backgroundColor": ACCENT_SLATE, "borderColor": ACCENT_SLATE,
         "borderWidth": 1, "order": 1},
    ]

    cfg = _build_cfg(
        "bar", datasets, "Weekly Mileage: Planned vs Actual",
        {}, _val_y(None, "Miles", beginAtZero=True),
        labels=bar_labels,
    )
    return _chart_wrap(chart_id, cfg, height=300)


def strength_progression_chart(lift_name: str,
                                progression_df: pd.DataFrame,
                                chart_id: str | None = None,
                                projected: list | None = None,
                                lift_meta: dict | None = None) -> html.Div:
    """1RM trend line for a single lift, with optional projected dashed line.

    projected: list of {"date": Timestamp, "value": float} for future projections.
    """
    if progression_df.empty:
        return _empty_chart(f"No {lift_name} data")

    cid = chart_id or f"strength-{lift_name}"
    color = LIFT_COLORS.get(lift_name, ACCENT)
    progression_df = progression_df.copy()
    progression_df["date_str"] = progression_df["date"].dt.strftime("%Y-%m-%d")

    # Tested maxes as larger dots
    tested = progression_df[progression_df["is_test"]]

    pts = [{"x": _ts(r["date"]), "y": round(r["estimated_1rm"], 1)} for _, r in progression_df.iterrows()]
    datasets = [_trend_ds(pts, color, "Estimated 1RM",
                          borderWidth=2, fill=True,
                          backgroundColor=_hex_to_rgba(color, 0.1))]

    if not tested.empty:
        test_pts = [{"x": _ts(r["date"]), "y": round(r["estimated_1rm"], 1)} for _, r in tested.iterrows()]
        datasets.append(_scatter_ds(test_pts, color, "Tested Max",
                                    pointRadius=6, pointHoverRadius=8,
                                    pointStyle="triangle"))

    # Projected dashed line (future estimates)
    if projected:
        last_real = progression_df.iloc[-1]
        proj_pts = [{"x": _ts(last_real["date"]), "y": round(last_real["estimated_1rm"], 1)}]
        proj_pts += [{"x": _ts(p["date"]), "y": round(p["value"], 1)} for p in projected]
        datasets.append(_dashed_ds(proj_pts, color, "Projected", borderDash=[6, 4]))

    date_strings: dict[int, list[str]] = {0: progression_df["date_str"].tolist()}

    cfg = _build_cfg(
        "scatter", datasets, f"{lift_name.title()} — Estimated 1RM",
        _time_x(progression_df["date"]),
        _val_y(None, "lbs", beginAtZero=False),
        meta=_activity_meta(date_strings, hover_type="lift", lift_meta=lift_meta),
    )
    return _chart_wrap(cid, cfg, height=280)


def compliance_bar(pct: float, chart_id: str = "compliance-bar") -> html.Div:
    """Simple compliance progress bar (pure HTML/CSS)."""
    fill_color = ACCENT_SLATE if pct >= 70 else ACCENT_AMBER if pct >= 40 else ACCENT
    return html.Div([
        html.Div(f"{pct:.0f}% Complete", style={
            "fontSize": "13px", "fontWeight": "600",
            "marginBottom": "6px", "color": TEXT_SECONDARY,
        }),
        html.Div(
            html.Div(style={
                "width": f"{min(pct, 100):.1f}%",
                "height": "100%",
                "backgroundColor": fill_color,
                "borderRadius": "4px",
                "transition": "width 0.5s ease",
            }),
            style={
                "width": "100%", "height": "8px",
                "backgroundColor": _hex_to_rgba(TEXT_MUTED, 0.2),
                "borderRadius": "4px", "overflow": "hidden",
            },
        ),
    ], style={"marginBottom": "16px"})


def enhanced_plan_calendar(plan_rows: list[dict],
                            compliance_data: dict | None = None) -> html.Div:
    """Month-view calendar with workout cards, phase strips, and compliance."""
    if not plan_rows:
        return _empty_chart("No training plan data")

    from datetime import date as date_type, timedelta
    from calendar import monthrange
    from strava_analytics.web.theme import PHASE_COLORS, BORDER as _BORDER

    df = pd.DataFrame(plan_rows)
    df["date"] = pd.to_datetime(df["date"])
    df["weekday"] = df["date"].dt.weekday

    compliance_map = {}
    if compliance_data and compliance_data.get("by_date"):
        for entry in compliance_data["by_date"]:
            d = entry["date"]
            key = d.isoformat() if hasattr(d, "isoformat") else str(d)
            compliance_map[key] = entry["completed"]

    today = date_type.today()
    day_names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

    # Pre-compute weekly summary data (miles planned + lifts per week)
    week_summary = {}
    for row in plan_rows:
        d = row["date"]
        if hasattr(d, "isocalendar"):
            wk = d.isocalendar()[1]
        else:
            import datetime as _dt
            wk = _dt.date.fromisoformat(str(d)).isocalendar()[1]
        if wk not in week_summary:
            week_summary[wk] = {"miles": 0.0, "lifts": 0}
        if row.get("type") == "lift":
            week_summary[wk]["lifts"] += 1
        # Estimate miles from title (e.g., "Easy Run — 2.5 mi")
        title = row.get("title", "")
        import re as _re
        m = _re.search(r'([\d.]+)\s*mi', title)
        if m and row.get("type") == "run":
            week_summary[wk]["miles"] += float(m.group(1))

    # Get unique months in plan
    df["month_key"] = df["date"].dt.to_period("M")
    months = sorted(df["month_key"].unique())

    month_views = []
    for month in months:
        month_df = df[df["month_key"] == month]
        year = month.year
        mo = month.month
        month_label = month_df["date"].iloc[0].strftime("%B %Y")
        _, days_in_month = monthrange(year, mo)

        # Find the weekday of the 1st (0=Mon)
        first_weekday = date_type(year, mo, 1).weekday()

        # Header — 7-column, clean
        header = html.Div([
            html.Div(day_names[i], style={
                "textAlign": "center", "fontSize": "10px", "fontWeight": "600",
                "color": TEXT_MUTED, "padding": "4px 0",
                "letterSpacing": "0.06em",
            }) for i in range(7)
        ], style={
            "display": "grid", "gridTemplateColumns": "repeat(7, 1fr)",
            "gap": "2px", "borderBottom": f"1px solid {_BORDER}",
            "marginBottom": "4px",
        })

        # Build grid of day cells
        cells = []
        # Empty leading cells — invisible but preserve grid alignment
        for _ in range(first_weekday):
            cells.append(html.Div(style={"minHeight": "48px", "visibility": "hidden"}))

        for day in range(1, days_in_month + 1):
            d = date_type(year, mo, day)
            d_ts = pd.Timestamp(d)
            day_workouts = month_df[month_df["date"].dt.date == d]
            is_today = d == today
            is_plan_day = not day_workouts.empty

            # Cell content
            children = []

            if is_plan_day:
                for _, row in day_workouts.iterrows():
                    wtype = row["type"]
                    color = WORKOUT_TYPE_COLORS.get(wtype, TEXT_MUTED)
                    date_str = d.isoformat()
                    is_past = d <= today
                    is_completed = compliance_map.get(date_str, False)

                    intensity = row.get("intensity", "")

                    # Type abbreviation (small, muted)
                    type_abbr = {
                        "run": "RUN", "lift": "LIFT", "rest": "REST",
                        "obstacle": "OBS", "mobility": "MOB",
                    }.get(wtype, "")

                    # Build a short, scannable label
                    title = row["title"]
                    # Extract the key info: workout name + distance/weight
                    if wtype == "run":
                        # "Easy Run — 2.0 mi" → "Easy 2.0mi"
                        # "RACE: Boulder Bolder 10K" → "RACE 10K"
                        if title.startswith("RACE:"):
                            short = title.replace("RACE: ", "")
                        elif " — " in title:
                            parts = title.split(" — ")
                            name_part = parts[0].replace(" Run", "")
                            dist_part = parts[1].replace(" mi", "mi") if len(parts) > 1 else ""
                            short = f"{name_part} {dist_part}".strip()
                        else:
                            short = title
                    elif wtype == "lift":
                        # "Upper Body" / "Lower Body + Carries" / "Full Body + Obstacle Prep"
                        short = title.replace(" Body", "").replace("Maintenance ", "Maint. ")
                        if "(Light)" in short:
                            short = short.replace(" (Light)", " Lt")
                    elif wtype in ("rest", "mobility"):
                        short = title.split(" +")[0]  # "Rest + Spartan Prep" → "Rest"
                    else:
                        short = title

                    opacity = "1"
                    if is_past and not is_completed and wtype not in ("rest", "mobility"):
                        opacity = "0.4"

                    check = ""
                    if is_past and is_completed and wtype not in ("rest", "mobility"):
                        check = " \u2713"

                    children.append(html.Div([
                        html.Span(short, style={
                            "fontSize": "10px",
                            "color": "var(--text-primary, #fafaf9)",
                            "fontWeight": "500",
                        }),
                        html.Span(check, style={
                            "fontSize": "9px", "color": "rgba(34,197,94,0.9)",
                        }) if check else None,
                    ], style={
                        "whiteSpace": "nowrap",
                        "overflow": "hidden",
                        "textOverflow": "ellipsis",
                        "borderLeft": f"2px solid {color}",
                        "paddingLeft": "4px",
                        "marginBottom": "2px",
                        "opacity": opacity,
                        "lineHeight": "1.5",
                    }))

            # Determine dominant intensity for bottom strip
            intensities = [r.get("intensity", "") for _, r in day_workouts.iterrows()] if is_plan_day else []
            intensity_priority = {"race": 4, "hard": 3, "moderate": 2, "easy": 1}
            dominant_intensity = max(intensities, key=lambda x: intensity_priority.get(x, 0)) if intensities else ""
            strip_color = {
                "easy": ACCENT_SLATE, "moderate": ACCENT_AMBER,
                "hard": ACCENT, "race": ACCENT_RED,
            }.get(dominant_intensity, "transparent")

            cell_style = {
                "minHeight": "48px",
                "padding": "4px 5px 0 5px",
                "borderRadius": "4px",
                "backgroundColor": "var(--bg-card, #1c1917)" if is_plan_day else "transparent",
                "border": f"1px solid {_BORDER}" if is_plan_day else "1px solid transparent",
                "display": "flex", "flexDirection": "column",
            }
            if is_today:
                cell_style["border"] = f"2px solid {ACCENT}"

            date_color = ACCENT if is_today else (TEXT_MUTED if not is_plan_day else "var(--text-secondary, #a8a29e)")

            # Intensity strip at bottom
            strip = html.Div(style={
                "height": "3px", "borderRadius": "0 0 3px 3px",
                "backgroundColor": strip_color,
                "marginTop": "auto",
                "margin": "auto -5px 0 -5px",
            }) if is_plan_day and strip_color != "transparent" else None

            cells.append(html.Div([
                html.Div(str(day), style={
                    "fontSize": "11px", "fontWeight": "600" if is_today else "400",
                    "color": date_color, "marginBottom": "2px",
                }),
                *children,
                strip,
            ], style=cell_style))

        # Trailing empty cells — invisible
        total_cells = first_weekday + days_in_month
        trailing = (7 - total_cells % 7) % 7
        for _ in range(trailing):
            cells.append(html.Div(style={"minHeight": "48px", "visibility": "hidden"}))

        # Build grid with week summary footer rows after each 7-day row
        grid_cells = []
        for i in range(0, len(cells), 7):
            week_row = cells[i:i+7]
            grid_cells.extend(week_row)

            # Compute weekly summary for this row
            wk_miles = 0.0
            wk_lifts = 0
            wk_runs = 0
            for cell_idx in range(i, min(i + 7, len(cells))):
                day_num = cell_idx - first_weekday + 1
                if 1 <= day_num <= days_in_month:
                    d = date_type(year, mo, day_num)
                    day_wk = month_df[month_df["date"].dt.date == d]
                    for _, wr in day_wk.iterrows():
                        if wr["type"] == "lift":
                            wk_lifts += 1
                        if wr["type"] == "run":
                            wk_runs += 1
                            import re as _re2
                            m2 = _re2.search(r'([\d.]+)\s*mi', wr.get("title", ""))
                            if m2:
                                wk_miles += float(m2.group(1))

            # Week footer row spanning all 7 columns
            parts = []
            if wk_miles > 0:
                parts.append(f"{wk_miles:.0f} mi")
            if wk_runs > 0:
                parts.append(f"{wk_runs} runs")
            if wk_lifts > 0:
                parts.append(f"{wk_lifts} lifts")

            if parts:
                grid_cells.append(html.Div(
                    " \u00b7 ".join(parts),
                    style={
                        "gridColumn": "1 / -1",
                        "fontSize": "10px", "color": TEXT_MUTED,
                        "fontFamily": FONT_MONO,
                        "padding": "2px 4px 6px",
                        "borderBottom": f"1px solid {_BORDER}",
                        "marginBottom": "4px",
                    },
                ))

        grid = html.Div(grid_cells, style={
            "display": "grid", "gridTemplateColumns": "repeat(7, 1fr)",
            "gap": "2px",
        })

        month_views.append(html.Div([
            html.H6(month_label, style={
                "fontSize": "14px", "fontWeight": "600",
                "color": "var(--text-primary, #fafaf9)",
                "marginBottom": "8px", "letterSpacing": "0.02em",
            }),
            header,
            grid,
        ], style={"marginBottom": "24px"}))

    return html.Div(month_views, style={"marginBottom": "12px"})


# ---------------------------------------------------------------------------
# Single-activity HR charts (used in activity cards for lifts)
# ---------------------------------------------------------------------------

def activity_hr_zone_chart(zone_secs: list[float], chart_id: str) -> html.Div | None:
    """Horizontal bar chart of HR zone time for a single activity.

    Same style as hr_zone_distribution_chart but for one session (minutes not hours).
    """
    if not zone_secs or sum(zone_secs) < 30:
        return None

    mins = [round(s / 60, 1) for s in zone_secs]
    colors = [_HR_ZONE_COLORS.get(z, TEXT_MUTED) for z in range(1, 6)]
    max_val = max(mins) if mins else 1

    cfg = _build_cfg(
        "bar",
        [{"label": "Minutes", "data": mins, "backgroundColor": colors, "borderRadius": 2}],
        "HR Zones",
        _val_y(None, "Minutes", beginAtZero=True, min=0,
               max=round(max_val * 1.15, 1) if max_val > 0 else 10),
        {},
        legend=False,
        labels=_HR_ZONE_LABELS,
    )
    cfg["options"]["indexAxis"] = "y"
    return _chart_wrap(chart_id, cfg, height=180)


def activity_hr_timeline_chart(
    hr_points: list[tuple],
    chart_id: str,
    max_hr: int = 200,
    zone_pct: list[float] | None = None,
) -> html.Div | None:
    """Line chart of HR over time for a single activity with zone background bands.

    Same Chart.js style as hr_over_time_chart but for one session's FIT HR stream.
    """
    if not hr_points or len(hr_points) < 10:
        return None

    if zone_pct is None:
        zone_pct = [0.60, 0.70, 0.80, 0.90]  # Z1/Z2, Z2/Z3, Z3/Z4, Z4/Z5

    t0 = hr_points[0][0]
    # Downsample to ~150 points for performance
    step = max(1, len(hr_points) // 150)
    sampled = hr_points[::step]

    data_pts = []
    for ts, hr in sampled:
        t_min = (ts - t0).total_seconds() / 60
        data_pts.append({"x": round(t_min, 2), "y": hr})

    hrs = [p[1] for p in sampled]
    min_hr = min(hrs)
    max_hr_val = max(hrs)

    # Zone boundary annotations (horizontal colored bands)
    boundaries = [int(max_hr * p) for p in zone_pct]
    zone_colors = [_HR_ZONE_COLORS.get(z, "#666") for z in range(1, 6)]
    annotations = {}
    prev_bpm = int(max_hr * 0.50)
    for i, bpm in enumerate(boundaries + [max_hr]):
        annotations[f"zone{i+1}"] = {
            "type": "box",
            "yMin": prev_bpm, "yMax": bpm,
            "backgroundColor": zone_colors[i].replace(")", ", 0.06)").replace("rgb", "rgba")
                if zone_colors[i].startswith("rgb") else zone_colors[i] + "10",
            "borderWidth": 0,
        }
        prev_bpm = bpm

    datasets = [_trend_ds(data_pts, ACCENT_RED, "Heart Rate",
                          borderWidth=1.5, fill=True,
                          backgroundColor=_hex_to_rgba(ACCENT_RED, 0.08))]

    cfg = _build_cfg(
        "line", datasets, "Heart Rate",
        {"type": "linear", "title": {"display": True, "text": "Minutes"},
         "ticks": {"maxRotation": 0, "maxTicksLimit": 8}},
        _val_y(None, "BPM", min=max(40, min_hr - 5), max=max_hr_val + 5),
        legend=False,
    )
    cfg["options"]["plugins"]["annotation"] = {"annotations": annotations}
    return _chart_wrap(chart_id, cfg, height=200)
