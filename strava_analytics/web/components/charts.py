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
    SLATE_60, AMBER_60, TEXT_SECONDARY, TEXT_MUTED,
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
                "backgroundColor": color,
                "borderColor": color,
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
            "backgroundColor": ACCENT,
            "borderColor": ACCENT,
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
                    "type": "time", "time": {"unit": "week"},
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
                "x": {"ticks": {"maxRotation": 45}},
                "y": {
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Miles"},
                    "max": round(float(weekly["distance_mi"].max()) * 1.05, 1),
                },
            },
        },
    }
    return _chart_wrap(chart_id, cfg, height=320)


def aerobic_efficiency_chart(runs: pd.DataFrame, chart_id: str = "hr-vs-pace") -> html.Div:
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
        "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.5),
        "borderColor": ACCENT_SLATE,
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
        },
    }
    return _chart_wrap(chart_id, cfg, height=320)


# ── HR analysis charts ───────────────────────────────────────────────

_HR_ZONE_COLORS = {
    1: SLATE_60,        # Recovery
    2: ACCENT_SLATE,    # Easy
    3: ACCENT_AMBER,    # Moderate
    4: ACCENT,          # Threshold
    5: ACCENT_RED,      # Max
}
_HR_ZONE_LABELS = ["Z1 Recovery", "Z2 Easy", "Z3 Moderate", "Z4 Threshold", "Z5 Max"]


def hr_zone_distribution_chart(runs: pd.DataFrame, chart_id: str = "hr-zones") -> html.Div:
    """Horizontal bar chart of total time spent in each HR zone across all runs."""
    if "hr_zone" not in runs.columns or "moving_time_s" not in runs.columns:
        return _empty_chart("No HR zone data")

    df = runs[runs["hr_zone"].notna()].copy()
    if df.empty:
        return _empty_chart("No HR zone data")

    # Sum moving time per zone, convert to hours
    zone_hours = df.groupby("hr_zone")["moving_time_s"].sum().reindex(range(1, 6), fill_value=0) / 3600
    hours = [round(zone_hours.get(z, 0), 1) for z in range(1, 6)]
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
            "backgroundColor": _hex_to_rgba(ACCENT_SLATE, 0.25),
            "borderColor": ACCENT_SLATE,
            "pointRadius": 2,
            "pointHoverRadius": 4,
            "showLine": False,
        },
        {
            "label": "Stroller",
            "data": [{"x": _ts(r["date"]), "y": round(r["pace_min_per_mi"], 2)} for _, r in stroller.iterrows()],
            "backgroundColor": ACCENT,
            "borderColor": ACCENT,
            "pointRadius": 4,
            "pointHoverRadius": 6,
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
                "backgroundColor": color,
                "borderColor": color,
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
            "backgroundColor": ACCENT,
            "borderColor": ACCENT,
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
    labels = [d.strftime("%b %d") for d in lifts_data["date"]]

    datasets = []
    all_vol = []
    for lift, color in LIFT_COLORS.items():
        col = f"{lift}_volume"
        if col not in lifts_data.columns:
            continue
        vals = lifts_data[col].fillna(0).tolist()
        if all(v == 0 for v in vals):
            continue
        all_vol.extend(v for v in vals if v > 0)
        datasets.append({
            "label": lift.title(),
            "data": [round(v, 0) for v in vals],
            "backgroundColor": _hex_to_rgba(color, 0.8),
            "borderColor": color,
            "borderWidth": 1,
        })

    if not datasets:
        return _empty_chart("No volume data for primary lifts")

    cfg: dict[str, Any] = {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg("Training Volume"),
                "legend": {"position": "bottom"},
            },
            "scales": {
                "x": {"stacked": True, "ticks": {"maxRotation": 45}},
                "y": {
                    "stacked": True,
                    "beginAtZero": True, "min": 0,
                    "title": {"display": True, "text": "Volume (sets x reps x weight)"},
                    "max": round(max(all_vol) * 1.05) if all_vol else None,
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
    """Estimated 1RM with Kalman filter smoothing and confidence band."""
    from strava_analytics.kalman import kalman_1rm

    if chart_id is None:
        chart_id = f"onerm-{lift_name.lower().replace(' ', '-')}"

    if progression_df.empty:
        return _empty_chart(f"No 1RM data for {lift_name}")

    kdf = kalman_1rm(progression_df)
    if kdf.empty:
        return _empty_chart(f"No 1RM data for {lift_name}")

    labels = [_ts(d) for d in kdf["date"]]

    datasets = [
        # Raw estimates as light dots
        {
            "label": "Estimates",
            "data": [round(float(v), 1) for v in kdf["estimated_1rm"]],
            "borderColor": _hex_to_rgba(color, 0.4),
            "backgroundColor": _hex_to_rgba(color, 0.4),
            "borderWidth": 0,
            "pointRadius": _PT,
            "pointHoverRadius": _PT_HOVER,
        },
        # Kalman smoothed line
        {
            "label": "Kalman",
            "data": [round(float(v), 1) for v in kdf["kalman_1rm"]],
            "borderColor": color,
            "backgroundColor": color,
            "borderWidth": 3,
            "pointRadius": 0,
            "fill": False,
            "tension": 0.3,
        },
        # Confidence band (upper)
        {
            "label": "Upper",
            "data": [round(float(v), 1) for v in kdf["kalman_upper"]],
            "borderColor": "transparent",
            "backgroundColor": _hex_to_rgba(color, 0.12),
            "pointRadius": 0,
            "fill": "+1",
            "tension": 0.3,
        },
        # Confidence band (lower)
        {
            "label": "_lower",
            "data": [round(float(v), 1) for v in kdf["kalman_lower"]],
            "borderColor": "transparent",
            "pointRadius": 0,
            "fill": False,
            "tension": 0.3,
        },
    ]

    # Highlight tested maxes
    if "is_test" in kdf.columns:
        tests = kdf[kdf["is_test"] == True]
        if not tests.empty:
            # Create sparse array with None for non-test points
            test_data = [None] * len(kdf)
            for idx in tests.index:
                pos = kdf.index.get_loc(idx)
                test_data[pos] = round(float(tests.loc[idx, "estimated_1rm"]), 1)
            datasets.append({
                "label": "Tested max",
                "data": test_data,
                "backgroundColor": "#ffffff",
                "borderColor": color,
                "borderWidth": 2,
                "pointRadius": 6,
                "pointHoverRadius": 8,
                "pointStyle": "rectRot",
                "showLine": False,
            })

    all_vals = pd.concat([kdf["kalman_upper"], kdf["kalman_lower"], kdf["estimated_1rm"]])
    y_lim = _val_limits(all_vals)

    cfg: dict[str, Any] = {
        "type": "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg(f"{lift_name} — Estimated 1RM (Kalman)"),
                "legend": {"display": False},
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "week"},
                    **_time_limits(kdf["date"]),
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
) -> html.Div:
    """Build one Kalman-filtered race prediction chart for a single distance."""
    from strava_analytics.kalman import kalman_race

    kdf = kalman_race(runs, target_m)
    if kdf.empty:
        return _empty_chart(f"Not enough data for {label}", height=280)

    type_colors = {
        "race": ACCENT, "long": ACCENT_SLATE,
        "moderate": ACCENT_AMBER, "easy": SLATE_60,
    }

    datasets = []
    date_strings: dict[int, list[str]] = {}

    for rtype, color in type_colors.items():
        subset = kdf[kdf["run_type"] == rtype]
        if subset.empty:
            continue
        ds_idx = len(datasets)
        datasets.append({
            "label": rtype.title(),
            "data": [
                {"x": _ts(row["date"]), "y": round(row["est_time_min"], 2)}
                for _, row in subset.iterrows()
            ],
            "backgroundColor": color,
            "borderColor": color,
            "pointRadius": 2,
            "pointHoverRadius": 4,
            "showLine": False,
        })
        date_strings[ds_idx] = subset["date_str"].tolist()

    # Kalman smoothed line
    datasets.append({
        "label": "Predicted",
        "data": [
            {"x": _ts(row["date"]), "y": row["kalman_min"]}
            for _, row in kdf.iterrows()
        ],
        "borderColor": ACCENT,
        "borderWidth": 2,
        "pointRadius": 0,
        "showLine": True,
        "fill": False,
        "tension": 0.3,
    })

    # Confidence band
    datasets.append({
        "label": "_upper",
        "data": [{"x": _ts(row["date"]), "y": row["kalman_upper"]}
                 for _, row in kdf.iterrows()],
        "borderColor": "transparent",
        "backgroundColor": _hex_to_rgba(ACCENT, 0.1),
        "pointRadius": 0, "showLine": True, "fill": "+1", "tension": 0.3,
    })
    datasets.append({
        "label": "_lower",
        "data": [{"x": _ts(row["date"]), "y": row["kalman_lower"]}
                 for _, row in kdf.iterrows()],
        "borderColor": "transparent",
        "pointRadius": 0, "showLine": True, "fill": False, "tension": 0.3,
    })

    # Ground truth race markers
    gt = kdf[kdf["R"] < 0]
    if not gt.empty:
        datasets.append({
            "label": "Race result",
            "data": [{"x": _ts(row["date"]), "y": round(row["est_time_min"], 2)}
                     for _, row in gt.iterrows()],
            "backgroundColor": ACCENT_SLATE,
            "borderColor": "#ffffff",
            "borderWidth": 1,
            "pointRadius": 6,
            "pointHoverRadius": 8,
            "pointStyle": "star",
            "showLine": False,
        })

    y_lim = _val_limits(kdf["est_time_min"], pad_frac=0.05)

    # Y-axis label: MM:SS for shorter, H:MM for longer
    y_label = f"{label} Time (min)" if target_m <= 10_000 else f"{label} Time (min)"

    cfg: dict[str, Any] = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "plugins": {
                "title": _title_cfg(label),
                "legend": {"display": False},
            },
            "scales": {
                "x": {
                    "type": "time", "time": {"unit": "month"},
                    **_time_limits(kdf["date"]),
                },
                "y": {
                    "reverse": True,
                    "title": {"display": True, "text": y_label},
                    **y_lim,
                },
            },
        },
        "_meta": {
            "clickToScroll": True,
            "dateStrings": date_strings,
        },
    }
    return _chart_wrap(chart_id, cfg, height=280)


def race_predictions_chart(runs: pd.DataFrame, chart_id: str = "race-pred") -> html.Div:
    """Tabbed race predictions — one Kalman-filtered chart per distance."""
    if runs.empty:
        return _empty_chart("No runs for race prediction")

    # Build all 4 charts (hidden by default, JS tabs switch visibility)
    panels = []
    tab_buttons = []
    for i, (target_m, label) in enumerate(_RACE_DISTANCES):
        sub_id = f"{chart_id}-{label.lower().replace(' ', '-')}"
        is_default = (i == 0)
        panels.append(html.Div(
            _single_race_chart(runs, target_m, label, sub_id),
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
                "x": {"ticks": {"maxRotation": 45}},
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
