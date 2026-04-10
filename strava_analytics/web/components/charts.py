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
    LIFT_COLORS, RUN_TYPE_COLORS, WORKOUT_TYPE_COLORS,
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
            ds_idx = len(datasets)
            datasets.append({
                "label": rtype.title(),
                "data": [
                    {"x": _ts(row["date"]), "y": round(row["pace_min_per_mi"], 2)}
                    for _, row in subset.iterrows()
                ],
                "backgroundColor": _hex_to_rgba(color, 0.4),
                "borderColor": color,
                "borderWidth": 1,
                "pointRadius": _PT,
                "pointHoverRadius": _PT_HOVER,
                "showLine": False,
            })
            date_strings[ds_idx] = subset["date_str"].tolist()
    else:
        datasets.append({
            "label": "Runs",
            "data": [
                {"x": _ts(row["date"]), "y": round(row["pace_min_per_mi"], 2)}
                for _, row in df.iterrows()
            ],
            "backgroundColor": _hex_to_rgba(ACCENT, 0.4),
            "borderColor": ACCENT,
            "borderWidth": 1,
            "pointRadius": _PT,
            "pointHoverRadius": _PT_HOVER,
            "showLine": False,
        })
        date_strings[0] = df["date_str"].tolist()

    # 30-day rolling average (recalculated dynamically by JS when legend items toggled)
    trend_idx = len(datasets)
    df_sorted = df.sort_values("date")
    rolling = df_sorted.set_index("date")["pace_min_per_mi"].rolling("30D").mean()
    datasets.append({
        "label": "30-day avg",
        "data": [
            {"x": _ts(d), "y": round(v, 2)}
            for d, v in zip(rolling.index, rolling.values)
            if pd.notna(v)
        ],
        "borderColor": ACCENT,
        "borderWidth": 2.5,
        "pointRadius": 0,
        "showLine": True,
        "fill": False,
        "tension": 0.3,
    })

    y_lim = _val_limits(df["pace_min_per_mi"], pad_frac=0.05)

    cfg: dict[str, Any] = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Pace Trend"),
                "legend": {
                    "position": "right",
                    "labels": {"boxWidth": 12, "padding": 10},
                },
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "month"},
                    "ticks": {"maxRotation": 0, "maxTicksLimit": 10},
                    **_time_limits(df["date"]),
                },
                "y": {
                    "reverse": True,
                    "title": {"display": True, "text": "Pace (min/mi)"},
                    "ticks": {"stepSize": 0.5},
                    **y_lim,
                },
            },
        },
        "_meta": {
            "clickToScroll": True,
            "runHoverCard": True,
            "runMeta": run_meta or {},
            "dateStrings": date_strings,
            "dynamicTrendLine": True,
            "trendLineIndex": trend_idx,
        },
    }
    return _chart_wrap(chart_id, cfg, height=400)


def weekly_mileage_chart(runs: pd.DataFrame, chart_id: str = "weekly-miles") -> html.Div:
    """Bar chart of weekly miles."""
    if runs.empty:
        return _empty_chart("No runs for weekly mileage")

    df = runs.copy()
    df["week_start"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time)
    weekly = df.groupby("week_start")["distance_mi"].sum().reset_index()
    weekly = weekly.sort_values("week_start")

    cfg: dict[str, Any] = {
        "type": "bar",
        "data": {
            "labels": [d.strftime("%b %d") for d in weekly["week_start"]],
            "datasets": [{
                "label": "Miles",
                "data": [round(v, 1) for v in weekly["distance_mi"]],
                "backgroundColor": ACCENT,
                "borderRadius": 2,
            }],
        },
        "options": {
            "plugins": {
                "title": _title_cfg("Weekly Mileage"),
                "legend": {"display": False},
            },
            "scales": {
                "x": {"ticks": {"maxRotation": 0}},
                "y": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Miles"},
                    "max": round(float(weekly["distance_mi"].max()) * 1.05, 1),
                },
            },
        },
    }
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

    datasets = []
    date_strings: dict[int, list[str]] = {}

    datasets.append({
        "label": "_runs",
        "data": [
            {"x": _ts(row["date"]), "y": round(row["efficiency"], 2)}
            for _, row in df.iterrows()
        ],
        "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.4),
        "borderColor": ACCENT_SLATE,
        "borderWidth": 1,
        "pointRadius": _PT,
        "pointHoverRadius": _PT_HOVER,
        "showLine": False,
    })
    date_strings[0] = df["date_str"].tolist()

    # 30-day rolling average trend line
    trend_idx = len(datasets)
    rolling = df.set_index("date")["efficiency"].rolling("30D").mean()
    datasets.append({
        "label": "30-day avg",
        "data": [
            {"x": _ts(d), "y": round(v, 2)}
            for d, v in zip(rolling.index, rolling.values)
            if pd.notna(v)
        ],
        "borderColor": ACCENT,
        "borderWidth": 2.5,
        "pointRadius": 0,
        "showLine": True,
        "fill": False,
        "tension": 0.3,
    })

    y_lim = _val_limits(df["efficiency"], pad_frac=0.05)

    cfg: dict[str, Any] = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg(f"Aerobic Efficiency (pace @ {ref_hr} bpm)"),
                "legend": {"display": False},
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "month"},
                    "ticks": {"maxRotation": 0, "maxTicksLimit": 10},
                    **_time_limits(df["date"]),
                },
                "y": {
                    "reverse": True,
                    "title": {"display": True, "text": f"Pace @ {ref_hr} bpm (min/mi)"},
                    "ticks": {"stepSize": 0.5},
                    **y_lim,
                },
            },
        },
        "_meta": {
            "clickToScroll": True,
            "dateStrings": date_strings,
            "runHoverCard": True,
            "runMeta": run_meta or {},
        },
    }
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

    cfg: dict[str, Any] = {
        "type": "bar",
        "data": {
            "labels": _HR_ZONE_LABELS,
            "datasets": [{
                "label": "Hours",
                "data": hours,
                "backgroundColor": colors,
                "borderRadius": 2,
            }],
        },
        "options": {
            "indexAxis": "y",
            "plugins": {
                "title": _title_cfg("Time in HR Zones"),
                "legend": {"display": False},
            },
            "scales": {
                "x": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Hours"},
                    "max": round(max(hours) * 1.15, 1) if hours and max(hours) > 0 else 10,
                },
                "y": {},
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=250)


def hr_over_time_chart(runs: pd.DataFrame, chart_id: str = "hr-trend") -> html.Div:
    """Scatter of adjusted HR over time with 30-day rolling avg."""
    if "adjusted_hr" not in runs.columns:
        return _empty_chart("No HR data")

    df = runs[runs["adjusted_hr"].notna()].copy()
    df = df[(df["adjusted_hr"] > 100) & (df["adjusted_hr"] < 220)]
    if df.empty:
        return _empty_chart("No valid HR data")

    df = df.sort_values("date")

    datasets = [{
        "label": "_runs",
        "data": [
            {"x": _ts(row["date"]), "y": round(row["adjusted_hr"], 1)}
            for _, row in df.iterrows()
        ],
        "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.4),
        "borderColor": ACCENT_SLATE,
        "borderWidth": 1,
        "pointRadius": _PT,
        "pointHoverRadius": _PT_HOVER,
        "showLine": False,
    }]

    trend_idx = len(datasets)
    rolling = df.set_index("date")["adjusted_hr"].rolling("30D").mean()
    datasets.append({
        "label": "30-day avg",
        "data": [
            {"x": _ts(d), "y": round(v, 1)}
            for d, v in zip(rolling.index, rolling.values)
            if pd.notna(v)
        ],
        "borderColor": ACCENT,
        "borderWidth": 2.5,
        "pointRadius": 0,
        "showLine": True,
        "fill": False,
        "tension": 0.3,
    })

    y_lim = _val_limits(df["adjusted_hr"], pad_frac=0.05)

    cfg: dict[str, Any] = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Adjusted HR Over Time"),
                "legend": {"display": False},
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "month"},
                    "ticks": {"maxRotation": 0, "maxTicksLimit": 10},
                    **_time_limits(df["date"]),
                },
                "y": {
                    "title": {"display": True, "text": "Adjusted HR (bpm)"},
                    **y_lim,
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=280)


# ── stroller chart ───────────────────────────────────────────────────

def stroller_pace_chart(runs: pd.DataFrame, chart_id: str = "stroller-pace") -> html.Div:
    """Scatter: stroller vs solo pace over time with trend lines."""
    if "with_kid" not in runs.columns:
        return _empty_chart("No stroller data")

    stroller = runs[runs["with_kid"] == True].copy()
    solo = runs[runs["with_kid"] == False].copy()
    if stroller.empty or len(stroller) < 3:
        return _empty_chart("Not enough stroller runs")

    both = pd.concat([stroller, solo])
    both = both[(both["pace_min_per_mi"] >= 6) & (both["pace_min_per_mi"] <= 15)]
    stroller = both[both["with_kid"] == True].sort_values("date")
    solo = both[both["with_kid"] == False].sort_values("date")

    datasets = [
        {
            "label": "Solo",
            "data": [{"x": _ts(r["date"]), "y": round(r["pace_min_per_mi"], 2)} for _, r in solo.iterrows()],
            "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.4),
            "borderColor": ACCENT_SLATE,
            "borderWidth": 1,
            "pointRadius": _PT,
            "pointHoverRadius": _PT_HOVER,
            "showLine": False,
        },
        {
            "label": "Stroller",
            "data": [{"x": _ts(r["date"]), "y": round(r["pace_min_per_mi"], 2)} for _, r in stroller.iterrows()],
            "backgroundColor": _hex_to_rgba(ACCENT, 0.4),
            "borderColor": ACCENT,
            "borderWidth": 1,
            "pointRadius": _PT,
            "pointHoverRadius": _PT_HOVER,
            "showLine": False,
        },
    ]

    # Trend lines
    if len(solo) >= 3:
        solo_roll = solo.set_index("date")["pace_min_per_mi"].rolling("30D").mean()
        datasets.append({
            "label": "_solo_trend",
            "data": [{"x": _ts(d), "y": round(v, 2)} for d, v in zip(solo_roll.index, solo_roll.values) if pd.notna(v)],
            "borderColor": ACCENT_SLATE,
            "borderWidth": 2,
            "borderDash": [6, 3],
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.3,
        })
    if len(stroller) >= 3:
        str_roll = stroller.set_index("date")["pace_min_per_mi"].rolling("60D").mean()
        datasets.append({
            "label": "_stroller_trend",
            "data": [{"x": _ts(d), "y": round(v, 2)} for d, v in zip(str_roll.index, str_roll.values) if pd.notna(v)],
            "borderColor": ACCENT,
            "borderWidth": 2,
            "borderDash": [6, 3],
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.3,
        })

    y_lim = _val_limits(both["pace_min_per_mi"], pad_frac=0.05)

    cfg: dict[str, Any] = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Stroller vs Solo Pace Over Time"),
                "legend": {"position": "bottom", "labels": {"boxWidth": 12}},
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "month"},
                    "ticks": {"maxRotation": 0, "maxTicksLimit": 10},
                    **_time_limits(both["date"]),
                },
                "y": {
                    "reverse": True,
                    "title": {"display": True, "text": "Pace (min/mi)"},
                    "ticks": {"stepSize": 0.5},
                    **y_lim,
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=350)


# ── heat vs pace chart ───────────────────────────────────────────────

def heat_vs_pace_chart(runs: pd.DataFrame, chart_id: str = "heat-pace") -> html.Div:
    """Scatter of temperature vs pace, color-coded by run type."""
    if "weather_temp_f" not in runs.columns:
        return _empty_chart("No temperature data")

    df = runs[
        runs["weather_temp_f"].notna()
        & runs["pace_min_per_mi"].between(6, 15)
    ].copy()
    if len(df) < 10:
        return _empty_chart("Not enough runs with temperature data")

    datasets = []
    if "run_type" in df.columns:
        for rtype in sorted(df["run_type"].unique()):
            subset = df[df["run_type"] == rtype]
            color = RUN_TYPE_COLORS.get(rtype, TEXT_SECONDARY)
            datasets.append({
                "label": rtype.title(),
                "data": [
                    {"x": round(r["weather_temp_f"], 1), "y": round(r["pace_min_per_mi"], 2)}
                    for _, r in subset.iterrows()
                ],
                "backgroundColor": _hex_to_rgba(color, 0.4),
                "borderColor": color,
                "borderWidth": 1,
                "pointRadius": _PT,
                "pointHoverRadius": _PT_HOVER,
                "showLine": False,
            })
    else:
        datasets.append({
            "label": "Runs",
            "data": [
                {"x": round(r["weather_temp_f"], 1), "y": round(r["pace_min_per_mi"], 2)}
                for _, r in df.iterrows()
            ],
            "backgroundColor": _hex_to_rgba(ACCENT, 0.4),
            "borderColor": ACCENT,
            "borderWidth": 1,
            "pointRadius": _PT,
            "pointHoverRadius": _PT_HOVER,
            "showLine": False,
        })

    # Linear trend line
    import numpy as np
    valid = df[["weather_temp_f", "pace_min_per_mi"]].dropna()
    if len(valid) >= 10:
        coeffs = np.polyfit(valid["weather_temp_f"], valid["pace_min_per_mi"], 1)
        x_min, x_max = float(valid["weather_temp_f"].min()), float(valid["weather_temp_f"].max())
        datasets.append({
            "label": "_trend",
            "data": [
                {"x": round(x_min, 1), "y": round(coeffs[0] * x_min + coeffs[1], 2)},
                {"x": round(x_max, 1), "y": round(coeffs[0] * x_max + coeffs[1], 2)},
            ],
            "borderColor": ACCENT,
            "borderWidth": 2,
            "borderDash": [6, 3],
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
        })

    y_lim = _val_limits(df["pace_min_per_mi"], pad_frac=0.05)

    cfg: dict[str, Any] = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Temperature vs Pace"),
                "legend": {"position": "bottom", "labels": {"boxWidth": 12}},
            },
            "scales": {
                "x": {
                    "title": {"display": True, "text": "Temperature (\u00b0F)"},
                    **_val_limits(df["weather_temp_f"], pad_frac=0.05),
                },
                "y": {
                    "reverse": True,
                    "title": {"display": True, "text": "Pace (min/mi)"},
                    "ticks": {"stepSize": 0.5},
                    **y_lim,
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=350)


def fatigue_chart(df: pd.DataFrame, chart_id: str = "fatigue") -> html.Div:
    """Training load: ATL, CTL, TSB with area fill."""
    if "acute_load_7d" not in df.columns:
        return _empty_chart("No training load data available")
    has = df[df["acute_load_7d"].notna()].copy()
    if has.empty:
        return _empty_chart("No training load data available")

    labels = [_ts(d) for d in has["date"]]

    datasets = [
        {
            "label": "Fitness (CTL)",
            "data": [round(v, 1) if pd.notna(v) else None for v in has["chronic_load_28d"]],
            "borderColor": ACCENT_SLATE,
            "borderWidth": 2,
            "pointRadius": 0,
            "fill": False,
            "tension": 0.3,
        },
        {
            "label": "Fatigue (ATL)",
            "data": [round(v, 1) if pd.notna(v) else None for v in has["acute_load_7d"]],
            "borderColor": ACCENT_RED,
            "borderWidth": 2,
            "pointRadius": 0,
            "fill": False,
            "tension": 0.3,
        },
        {
            "label": "Form (TSB)",
            "data": [round(v, 1) if pd.notna(v) else None for v in has["freshness"]],
            "borderColor": ACCENT_AMBER,
            "borderWidth": 2,
            "pointRadius": 0,
            "fill": "origin",
            "backgroundColor": _hex_to_rgba(ACCENT_AMBER, 0.1),
            "tension": 0.3,
        },
    ]

    all_y = pd.concat([has["chronic_load_28d"], has["acute_load_7d"], has["freshness"]]).dropna()

    cfg: dict[str, Any] = {
        "type": "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Training Load & Freshness"),
                "legend": {"position": "bottom"},
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "week"},
                    "ticks": {"maxTicksLimit": 8, "autoSkip": True, "maxRotation": 0},
                    **_time_limits(has["date"]),
                },
                "y": {
                    "title": {"display": True, "text": "Load / Freshness"},
                    **_val_limits(all_y, pad_frac=0.1),
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=400)


# ── lifting charts ────────────────────────────────────────────────────

def lift_progression_chart(df: pd.DataFrame, chart_id: str = "lift-prog") -> html.Div:
    """Line chart of working weights over time."""
    lifts_data = df[df["type"] == "Weight Training"].copy()
    if lifts_data.empty:
        return _empty_chart("No weight training sessions found")

    datasets = []
    all_weights = []
    all_dates = []
    for lift, color in LIFT_COLORS.items():
        col = f"{lift}_weight"
        if col not in lifts_data.columns:
            continue
        subset = lifts_data[lifts_data[col].notna() & (lifts_data[col] > 0)].sort_values("date")
        if subset.empty:
            continue
        all_weights.extend(subset[col].tolist())
        all_dates.extend(subset["date"].tolist())
        datasets.append({
            "label": lift.title(),
            "data": [
                {"x": _ts(row["date"]), "y": round(float(row[col]), 1)}
                for _, row in subset.iterrows()
            ],
            "borderColor": color,
            "backgroundColor": color,
            "borderWidth": 2,
            "pointRadius": _PT_LINE,
            "pointHoverRadius": _PT_LINE_H,
            "tension": 0.2,
            "fill": False,
        })

    if not datasets:
        return _empty_chart("No weight data for primary lifts")

    w_series = pd.Series(all_weights)
    date_series = pd.Series(all_dates)

    cfg: dict[str, Any] = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Working Weight Progression"),
                "legend": {"position": "bottom"},
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "week"},
                    "ticks": {"maxRotation": 0, "maxTicksLimit": 10},
                    **_time_limits(date_series),
                },
                "y": {
                    "title": {"display": True, "text": "Weight (lbs)"},
                    **_val_limits(w_series),
                },
            },
            "showLine": True,
        },
    }
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

    cfg: dict[str, Any] = {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Training Volume"),
                "legend": {
                    "position": "bottom",
                    "labels": {"boxWidth": 12, "padding": 10},
                },
            },
            "scales": {
                "x": {"stacked": True},
                "y": {
                    "stacked": True,
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Volume (sets x reps x weight)"},
                    "max": y_max,
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=350)


def onerm_progression_chart(
    progression_df: pd.DataFrame,
    lift_name: str,
    color: str,
    chart_id: str | None = None,
) -> html.Div:
    """Estimated 1RM with log-curve fit trend line."""
    from strava_analytics.strength_model import fit_1rm_curve
    import math

    if chart_id is None:
        chart_id = f"onerm-{lift_name.lower().replace(' ', '-')}"

    if progression_df.empty:
        return _empty_chart(f"No 1RM data for {lift_name}")

    df = progression_df.sort_values("date").copy()
    fit = fit_1rm_curve(df)

    labels = [_ts(d) for d in df["date"]]

    # Compute log-curve trend line: 1RM(w) = a * ln(w+1) + b
    first_date = df["date"].min()
    weeks = (df["date"] - first_date).dt.total_seconds() / (7 * 86400)
    trend = [round(fit["a"] * math.log(w + 1) + fit["b"], 1) for w in weeks]

    datasets = [
        # Per-session estimated 1RM as dots
        {
            "label": "Session estimate",
            "data": [round(float(v), 1) for v in df["estimated_1rm"]],
            "borderColor": _hex_to_rgba(color, 0.4),
            "backgroundColor": _hex_to_rgba(color, 0.4),
            "borderWidth": 0,
            "pointRadius": _PT,
            "pointHoverRadius": _PT_HOVER,
        },
        # Log-curve trend line
        {
            "label": "Trend (log fit)",
            "data": trend,
            "borderColor": color,
            "backgroundColor": color,
            "borderWidth": 3,
            "pointRadius": 0,
            "fill": False,
            "tension": 0.3,
        },
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

    y_lim = _val_limits(df["estimated_1rm"])

    cfg: dict[str, Any] = {
        "type": "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg(f"{lift_name} — Estimated 1RM (R²={fit['r_squared']:.2f})"),
                "legend": {
                    "display": True,
                    "position": "bottom",
                    "labels": {
                        "boxWidth": 12, "padding": 8,
                        "usePointStyle": True,
                    },
                },
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "week"},
                    "ticks": {"maxRotation": 0, "maxTicksLimit": 10},
                    **_time_limits(df["date"]),
                },
                "y": {
                    "title": {"display": True, "text": "Est. 1RM (lbs)"},
                    **y_lim,
                },
            },
        },
    }
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
) -> html.Div:
    """Build a race prediction chart using Critical Speed model + best efforts."""
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
    datasets = [{
        "label": "Runs",
        "data": [
            {"x": _ts(row["date"]), "y": round(row["est_time_min"], 2)}
            for _, row in edf.iterrows()
        ],
        "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.4),
        "borderColor": ACCENT_SLATE,
        "borderWidth": 1,
        "pointRadius": _PT,
        "pointHoverRadius": _PT_HOVER,
        "showLine": False,
    }]

    # Fitness trend: 60-day rolling minimum across all runs
    sorted_edf = edf.sort_values("date").copy()
    sorted_edf["rolling_best"] = (
        sorted_edf.set_index("date")["est_time_min"]
        .rolling("60D", min_periods=3).quantile(0.1)  # 10th percentile = near-best
        .values
    )
    trend = sorted_edf.dropna(subset=["rolling_best"])
    # Subsample for clean line
    trend = trend.iloc[::max(1, len(trend) // 60)]
    if not trend.empty:
        datasets.append({
            "label": "Fitness trend",
            "data": [
                {"x": _ts(row["date"]), "y": round(row["rolling_best"], 2)}
                for _, row in trend.iterrows()
            ],
            "borderColor": ACCENT,
            "borderWidth": 2,
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.4,
        })

    y_lim = _val_limits(edf["est_time_min"], pad_frac=0.05)
    y_label = f"{label} Time (min)" if target_m <= 10_000 else f"{label} Time (hr:min)"

    cfg: dict[str, Any] = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg(label),
                "legend": {"display": True, "position": "bottom",
                           "labels": {"boxWidth": 10, "padding": 6, "usePointStyle": True}},
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "month"},
                    "ticks": {"maxRotation": 0, "maxTicksLimit": 10},
                    **_time_limits(edf["date"]),
                },
                "y": {
                    "reverse": True,
                    "title": {"display": True, "text": y_label},
                    **y_lim,
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=280)


def race_predictions_chart(runs: pd.DataFrame, chart_id: str = "race-pred",
                            best_efforts: pd.DataFrame | None = None) -> html.Div:
    """Tabbed race predictions — one CS-based chart per distance."""
    if runs.empty:
        return _empty_chart("No runs for race prediction")

    panels = []
    tab_buttons = []
    for i, (target_m, label) in enumerate(_RACE_DISTANCES):
        sub_id = f"{chart_id}-{label.lower().replace(' ', '-')}"
        is_default = (i == 0)
        panels.append(html.Div(
            _single_race_chart(runs, target_m, label, sub_id, best_efforts),
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

    cfg: dict[str, Any] = {
        "type": "bar",
        "data": {
            "labels": monthly["label"].tolist(),
            "datasets": [
                {
                    "label": "Miles",
                    "data": [round(v, 1) for v in monthly["miles"]],
                    "backgroundColor": ACCENT,
                    "borderRadius": 2,
                    "yAxisID": "y",
                    "order": 2,
                },
                {
                    "label": "Activities",
                    "data": monthly["count"].tolist(),
                    "type": "line",
                    "borderColor": ACCENT_SLATE,
                    "backgroundColor": ACCENT_SLATE,
                    "borderWidth": 2,
                    "pointRadius": _PT_LINE,
                    "yAxisID": "y1",
                    "fill": False,
                    "order": 1,
                },
            ],
        },
        "options": {
            "plugins": {
                "title": _title_cfg("Monthly Volume"),
                "legend": {"position": "bottom"},
            },
            "scales": {
                "x": {"ticks": {"maxRotation": 0}},
                "y": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Miles"},
                    "position": "left",
                    "max": round(float(monthly["miles"].max()) * 1.1, 1),
                },
                "y1": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Activities"},
                    "position": "right",
                    "grid": {"drawOnChartArea": False},
                    "max": int(monthly["count"].max() + 2),
                },
            },
        },
    }
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

    cfg: dict[str, Any] = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Weekly Load",
                    "data": [round(v, 1) for v in weekly["load"]],
                    "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.7),
                    "borderColor": ACCENT_SLATE,
                    "borderWidth": 1,
                    "borderRadius": 2,
                    "order": 2,
                },
                {
                    "label": "4-Week Avg",
                    "data": [round(v, 1) if pd.notna(v) else None for v in weekly["trend"]],
                    "type": "line",
                    "borderColor": ACCENT,
                    "borderWidth": 2,
                    "pointRadius": 0,
                    "fill": False,
                    "tension": 0.3,
                    "order": 1,
                },
            ],
        },
        "options": {
            "plugins": {
                "title": _title_cfg("Weekly Training Load"),
                "legend": {"position": "bottom"},
            },
            "scales": {
                "x": {
                    "ticks": {"maxRotation": 0, "autoSkip": True},
                },
                "y": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Training Stress"},
                },
            },
        },
    }
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

    cfg: dict[str, Any] = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Miles",
                    "data": miles,
                    "backgroundColor": ACCENT,
                    "borderRadius": 2,
                    "yAxisID": "y",
                    "order": 2,
                },
                {
                    "label": "Activities",
                    "data": counts,
                    "type": "line",
                    "borderColor": ACCENT_SLATE,
                    "borderWidth": 2,
                    "pointRadius": _PT_LINE,
                    "yAxisID": "y1",
                    "fill": False,
                    "order": 1,
                },
            ],
        },
        "options": {
            "plugins": {
                "title": _title_cfg(f"{summary.get('year', '')} Month by Month"),
                "legend": {"position": "bottom"},
            },
            "scales": {
                "x": {},
                "y": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Miles"},
                    "position": "left",
                },
                "y1": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Activities"},
                    "position": "right",
                    "grid": {"drawOnChartArea": False},
                },
            },
        },
    }
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

    # CTL (Fitness) — solid line
    if not hist.empty:
        datasets.append({
            "label": "Fitness (CTL)",
            "data": [{"x": _ts(r["date"]), "y": round(r["ctl"], 1)} for _, r in hist.iterrows()],
            "borderColor": ACCENT_SLATE,
            "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.1),
            "borderWidth": 2,
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.3,
        })

    # ATL (Fatigue) — solid line
    if not hist.empty:
        datasets.append({
            "label": "Fatigue (ATL)",
            "data": [{"x": _ts(r["date"]), "y": round(r["atl"], 1)} for _, r in hist.iterrows()],
            "borderColor": ACCENT,
            "backgroundColor": _hex_to_rgba(ACCENT, 0.1),
            "borderWidth": 2,
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.3,
        })

    # TSB (Form) — filled area
    if not hist.empty:
        datasets.append({
            "label": "Form (TSB)",
            "data": [{"x": _ts(r["date"]), "y": round(r["tsb"], 1)} for _, r in hist.iterrows()],
            "borderColor": ACCENT_AMBER,
            "backgroundColor": _hex_to_rgba(ACCENT_AMBER, 0.15),
            "borderWidth": 1.5,
            "pointRadius": 0,
            "showLine": True,
            "fill": True,
            "tension": 0.3,
        })

    # Projected lines (dashed)
    if not proj.empty:
        datasets.append({
            "label": "Projected CTL",
            "data": [{"x": _ts(r["date"]), "y": round(r["ctl"], 1)} for _, r in proj.iterrows()],
            "borderColor": ACCENT_SLATE,
            "borderWidth": 2,
            "borderDash": [6, 3],
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.3,
        })
        datasets.append({
            "label": "Projected ATL",
            "data": [{"x": _ts(r["date"]), "y": round(r["atl"], 1)} for _, r in proj.iterrows()],
            "borderColor": ACCENT,
            "borderWidth": 2,
            "borderDash": [6, 3],
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.3,
        })
        datasets.append({
            "label": "Projected TSB",
            "data": [{"x": _ts(r["date"]), "y": round(r["tsb"], 1)} for _, r in proj.iterrows()],
            "borderColor": ACCENT_AMBER,
            "borderWidth": 1.5,
            "borderDash": [6, 3],
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.3,
        })

    # Race date markers stored in _meta for JS to draw as vertical lines
    race_markers = []
    if race_dates:
        race_markers = [{"date": _ts(d), "label": ""} for d in race_dates]

    cfg = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Fitness / Freshness"),
                "legend": {"position": "bottom", "labels": {"boxWidth": 12}},
            },
            "scales": {
                "x": {"type": "time", "time": {"unit": "month"},
                      "ticks": {"maxRotation": 0, "maxTicksLimit": 10}},
                "y": {"title": {"display": True, "text": "Load / Form"}},
            },
        },
        "_meta": {"raceMarkers": race_markers},
    }
    return _chart_wrap(chart_id, cfg, height=350)


def mileage_progression_chart(mileage_df: pd.DataFrame,
                               chart_id: str = "mileage-progression") -> html.Div:
    """Bar chart of actual vs planned weekly miles."""
    if mileage_df.empty:
        return _empty_chart("No mileage data")

    labels = [f"Wk {r['week_num']}" for _, r in mileage_df.iterrows()]

    cfg = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Planned",
                    "data": mileage_df["planned_miles"].tolist(),
                    "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.3),
                    "borderColor": ACCENT_SLATE,
                    "borderWidth": 1,
                    "order": 2,
                },
                {
                    "label": "Actual",
                    "data": mileage_df["actual_miles"].tolist(),
                    "backgroundColor": ACCENT_SLATE,
                    "borderColor": ACCENT_SLATE,
                    "borderWidth": 1,
                    "order": 1,
                },
            ],
        },
        "options": {
            "plugins": {
                "title": _title_cfg("Weekly Mileage: Planned vs Actual"),
                "legend": {"position": "bottom", "labels": {"boxWidth": 12}},
            },
            "scales": {
                "x": {},
                "y": {
                    "beginAtZero": True,
                    "title": {"display": True, "text": "Miles"},
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=300)


def strength_progression_chart(lift_name: str,
                                progression_df: pd.DataFrame,
                                chart_id: str | None = None,
                                projected: list | None = None) -> html.Div:
    """1RM trend line for a single lift, with optional projected dashed line.

    projected: list of {"date": Timestamp, "value": float} for future projections.
    """
    if progression_df.empty:
        return _empty_chart(f"No {lift_name} data")

    cid = chart_id or f"strength-{lift_name}"
    color = {
        "bench": ACCENT, "squat": ACCENT_SLATE,
        "deadlift": ACCENT_AMBER, "ohp": SLATE_60,
    }.get(lift_name, ACCENT)

    # Tested maxes as larger dots
    tested = progression_df[progression_df["is_test"]]

    datasets = [
        {
            "label": "Estimated 1RM",
            "data": [
                {"x": _ts(r["date"]), "y": round(r["estimated_1rm"], 1)}
                for _, r in progression_df.iterrows()
            ],
            "borderColor": color,
            "backgroundColor": _hex_to_rgba(color, 0.1),
            "borderWidth": 2,
            "pointRadius": 0,
            "showLine": True,
            "fill": True,
            "tension": 0.3,
        },
    ]

    if not tested.empty:
        datasets.append({
            "label": "Tested Max",
            "data": [
                {"x": _ts(r["date"]), "y": round(r["estimated_1rm"], 1)}
                for _, r in tested.iterrows()
            ],
            "backgroundColor": color,
            "borderColor": color,
            "pointRadius": 6,
            "pointHoverRadius": 8,
            "showLine": False,
            "pointStyle": "triangle",
        })

    # Projected dashed line (future estimates)
    if projected:
        # Connect from last real data point to projection
        last_real = progression_df.iloc[-1]
        proj_pts = [{"x": _ts(last_real["date"]), "y": round(last_real["estimated_1rm"], 1)}]
        proj_pts += [{"x": _ts(p["date"]), "y": round(p["value"], 1)} for p in projected]
        datasets.append({
            "label": "Projected",
            "data": proj_pts,
            "borderColor": color,
            "borderWidth": 2,
            "borderDash": [6, 4],
            "pointRadius": 0,
            "showLine": True,
            "fill": False,
            "tension": 0.3,
        })

    cfg = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg(f"{lift_name.title()} — Estimated 1RM"),
                "legend": {"position": "bottom", "labels": {"boxWidth": 12}},
            },
            "scales": {
                "x": {"type": "time", "time": {"unit": "month"},
                      "ticks": {"maxRotation": 0, "maxTicksLimit": 10}},
                "y": {
                    "title": {"display": True, "text": "lbs"},
                    "beginAtZero": False,
                },
            },
        },
    }
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
    day_names = ["M", "T", "W", "T", "F", "S", "S"]

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

        # Header
        header = html.Div([
            html.Div(day_names[i], style={
                "textAlign": "center", "fontSize": "10px", "fontWeight": "600",
                "color": TEXT_MUTED, "padding": "6px 0",
                "letterSpacing": "0.08em",
            }) for i in range(7)
        ], style={
            "display": "grid", "gridTemplateColumns": "repeat(7, 1fr)",
            "gap": "3px",
        })

        # Build grid of day cells
        cells = []
        # Empty leading cells
        for _ in range(first_weekday):
            cells.append(html.Div(style={"minHeight": "72px"}))

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
                "minHeight": "72px",
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

        # Trailing empty cells
        total_cells = first_weekday + days_in_month
        trailing = (7 - total_cells % 7) % 7
        for _ in range(trailing):
            cells.append(html.Div(style={"minHeight": "72px"}))

        grid = html.Div(cells, style={
            "display": "grid", "gridTemplateColumns": "repeat(7, 1fr)",
            "gap": "3px",
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

    cfg: dict[str, Any] = {
        "type": "bar",
        "data": {
            "labels": _HR_ZONE_LABELS,
            "datasets": [{
                "label": "Minutes",
                "data": mins,
                "backgroundColor": colors,
                "borderRadius": 2,
            }],
        },
        "options": {
            "indexAxis": "y",
            "plugins": {
                "title": _title_cfg("HR Zones"),
                "legend": {"display": False},
            },
            "scales": {
                "x": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Minutes"},
                    "max": round(max_val * 1.15, 1) if max_val > 0 else 10,
                },
                "y": {},
            },
        },
    }
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

    cfg: dict[str, Any] = {
        "type": "line",
        "data": {
            "datasets": [{
                "label": "Heart Rate",
                "data": data_pts,
                "borderColor": ACCENT_RED,
                "borderWidth": 1.5,
                "pointRadius": 0,
                "fill": True,
                "backgroundColor": _hex_to_rgba(ACCENT_RED, 0.08),
                "tension": 0.3,
            }],
        },
        "options": {
            "plugins": {
                "title": _title_cfg("Heart Rate"),
                "legend": {"display": False},
                "annotation": {"annotations": annotations},
            },
            "scales": {
                "x": {
                    "type": "linear",
                    "title": {"display": True, "text": "Minutes"},
                    "ticks": {"maxRotation": 0, "maxTicksLimit": 8},
                },
                "y": {
                    "title": {"display": True, "text": "BPM"},
                    "min": max(40, min_hr - 5),
                    "max": max_hr_val + 5,
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=200)
