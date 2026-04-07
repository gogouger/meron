"""Chart builder functions for the dashboard."""

from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from strava_analytics.web.theme import (
    STRAVA_ORANGE, ACCENT_TEAL, ACCENT_GREEN, ACCENT_RED, ACCENT_YELLOW,
    ACCENT_PURPLE, BG_CARD, TEXT_SECONDARY, GRIDLINE,
    LIFT_COLORS, RUN_TYPE_COLORS, FATIGUE_COLORS,
    PHASE_COLORS, WORKOUT_TYPE_COLORS,
)
from strava_analytics.metrics import format_pace


def _hex_to_rgba(hex_color: str, alpha: float = 0.3) -> str:
    """Convert hex color to rgba string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# No Plotly logo, no modebar
CHART_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "staticPlot": False,
}


def _clean_layout(fig: go.Figure, **kwargs) -> go.Figure:
    """Apply clean layout defaults to every chart."""
    fig.update_layout(
        legend=dict(
            orientation="h", y=-0.15, x=0.5, xanchor="center",
            font=dict(size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=50, r=20, t=45, b=60),
        dragmode="zoom",
        **kwargs,
    )


    return fig


def _empty_chart(message: str = "No data available") -> go.Figure:
    """Return a styled empty chart with a centered message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=14, color=TEXT_SECONDARY),
    )
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        height=200,
    )
    return fig


def _apply_range_limits(
    fig: go.Figure,
    x_min=None, x_max=None,
    y_min=None, y_max=None,
    y_reversed: bool = False,
) -> go.Figure:
    """Constrain zoom/pan so the user cannot scroll beyond the data.

    Sets explicit range (for correct initial view) and minallowed/maxallowed
    (to prevent zooming/panning past the data). For reversed y-axes (pace,
    5K time), pass y_reversed=True — the range order is flipped automatically
    and autorange="reversed" should NOT be used on the chart.
    """
    if x_min is not None and x_max is not None:
        fig.update_xaxes(
            range=[x_min, x_max], autorange=False,
            minallowed=x_min, maxallowed=x_max,
        )
    if y_min is not None and y_max is not None:
        y_range = [y_max, y_min] if y_reversed else [y_min, y_max]
        fig.update_yaxes(
            range=y_range, autorange=False,
            minallowed=y_min, maxallowed=y_max,
        )
    return fig


# ---------------------------------------------------------------------------
# Running charts
# ---------------------------------------------------------------------------

def pace_trend_chart(runs: pd.DataFrame) -> go.Figure:
    """Scatter plot of pace over time, color-coded by run type."""
    if runs.empty:
        return _empty_chart("No runs to display")

    df = runs.copy()
    # Filter out extreme paces (walks miscategorized as runs, GPS errors)
    df = df[(df["pace_min_per_mi"] >= 6) & (df["pace_min_per_mi"] <= 15)]
    if df.empty:
        return _empty_chart("No runs with valid pace data")
    df["pace_str"] = df["pace_min_per_mi"].apply(format_pace)

    fig = go.Figure()

    # Include date string in customdata for click-to-scroll
    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")

    # Plot by run type with clean legend
    if "run_type" in df.columns:
        for rtype in sorted(df["run_type"].unique()):
            subset = df[df["run_type"] == rtype]
            color = RUN_TYPE_COLORS.get(rtype, TEXT_SECONDARY)
            fig.add_trace(go.Scatter(
                x=subset["date"], y=subset["pace_min_per_mi"],
                mode="markers", name=rtype.title(),
                marker=dict(color=color, size=10, opacity=0.85),
                customdata=subset[["name", "distance_mi", "pace_str", "date_str"]].values,
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:.1f} mi @ %{customdata[2]}<extra></extra>",
            ))
    else:
        df["_name"] = df.get("name", "Run")
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["pace_min_per_mi"],
            mode="markers", name="Runs",
            marker=dict(color=STRAVA_ORANGE, size=7, opacity=0.7),
            customdata=df[["_name", "distance_mi", "pace_str", "date_str"]].values,
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:.1f} mi @ %{customdata[2]}<extra></extra>",
        ))

    # 30-day rolling average
    df_sorted = df.sort_values("date")
    rolling = df_sorted.set_index("date")["pace_min_per_mi"].rolling("30D").mean()
    fig.add_trace(go.Scatter(
        x=rolling.index, y=rolling.values,
        mode="lines", name="30-day avg",
        line=dict(color=STRAVA_ORANGE, width=3),
        hoverinfo="skip",
    ))

    fig.update_yaxes(title="Pace (min/mi)")
    fig.update_xaxes(title="")
    _apply_range_limits(
        fig,
        x_min=df["date"].min() - timedelta(days=7),
        x_max=df["date"].max() + timedelta(days=7),
        y_min=df["pace_min_per_mi"].min() - 0.5,
        y_max=df["pace_min_per_mi"].max() + 0.5,
        y_reversed=True,
    )
    return _clean_layout(fig, title="Pace Trend", height=400)


def weekly_mileage_chart(runs: pd.DataFrame) -> go.Figure:
    """Bar chart of weekly miles using date-based labels."""
    if runs.empty:
        return _empty_chart("No runs for weekly mileage")

    df = runs.copy()
    # Use the Monday of each week as label to avoid period serialization issues
    df["week_start"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time)
    weekly = df.groupby("week_start")["distance_mi"].sum().reset_index()
    weekly["label"] = weekly["week_start"].dt.strftime("%b %d")

    fig = go.Figure(go.Bar(
        x=weekly["week_start"], y=weekly["distance_mi"],
        marker_color=STRAVA_ORANGE,
        hovertemplate="%{x|%b %d}: %{y:.1f} mi<extra></extra>",
    ))
    fig.update_xaxes(title="", tickangle=-45, nticks=15)
    fig.update_yaxes(title="Miles")
    _apply_range_limits(
        fig,
        x_min=weekly["week_start"].min() - timedelta(days=7),
        x_max=weekly["week_start"].max() + timedelta(days=7),
        y_min=0,
        y_max=weekly["distance_mi"].max() * 1.05,
    )
    return _clean_layout(fig, title="Weekly Mileage", height=320, showlegend=False)


def hr_vs_pace_chart(runs: pd.DataFrame) -> go.Figure:
    """Scatter: avg HR vs pace. Single color, no per-type legend clutter."""
    if runs.empty:
        return _empty_chart("No runs with heart rate data")

    df = runs[runs["avg_hr"].notna()].copy()
    # Filter to reasonable paces
    df = df[(df["pace_min_per_mi"] >= 6) & (df["pace_min_per_mi"] <= 15)]
    if df.empty:
        return _empty_chart("No runs with valid HR and pace data")

    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")

    fig = go.Figure(go.Scatter(
        x=df["pace_min_per_mi"], y=df["avg_hr"],
        mode="markers",
        marker=dict(color=ACCENT_TEAL, size=9, opacity=0.75),
        customdata=df[["name", "distance_mi", "date_str"]].values,
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:.1f} mi<br>Pace: %{x:.1f} | HR: %{y:.0f}<extra></extra>",
    ))

    fig.update_xaxes(title="Pace (min/mi)")
    fig.update_yaxes(title="Avg HR (bpm)")
    x_pad = (df["pace_min_per_mi"].max() - df["pace_min_per_mi"].min()) * 0.05
    y_pad = (df["avg_hr"].max() - df["avg_hr"].min()) * 0.05
    _apply_range_limits(
        fig,
        x_min=df["pace_min_per_mi"].min() - x_pad,
        x_max=df["pace_min_per_mi"].max() + x_pad,
        y_min=df["avg_hr"].min() - y_pad,
        y_max=df["avg_hr"].max() + y_pad,
    )
    return _clean_layout(fig, title="Heart Rate vs Pace", height=320, showlegend=False)


def fatigue_chart(df: pd.DataFrame) -> go.Figure:
    """Fatigue/freshness chart with ATL, CTL, and TSB."""
    if "acute_load_7d" not in df.columns:
        return _empty_chart("No training load data available")
    has_fatigue = df[df["acute_load_7d"].notna()].copy()
    if has_fatigue.empty:
        return _empty_chart("No training load data available")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=has_fatigue["date"], y=has_fatigue["chronic_load_28d"],
        mode="lines", name="Fitness (CTL)",
        line=dict(color=ACCENT_TEAL, width=2),
        hovertemplate="Fitness: %{y:.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=has_fatigue["date"], y=has_fatigue["acute_load_7d"],
        mode="lines", name="Fatigue (ATL)",
        line=dict(color=ACCENT_RED, width=2),
        hovertemplate="Fatigue: %{y:.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=has_fatigue["date"], y=has_fatigue["freshness"],
        mode="lines", name="Form (TSB)",
        line=dict(color=ACCENT_GREEN, width=2),
        fill="tozeroy", fillcolor=_hex_to_rgba(ACCENT_GREEN, 0.1),
        hovertemplate="Form: %{y:.0f}<extra></extra>",
    ))

    fig.update_xaxes(title="")
    fig.update_yaxes(title="Load / Freshness")
    all_y = pd.concat([
        has_fatigue["chronic_load_28d"], has_fatigue["acute_load_7d"],
        has_fatigue["freshness"],
    ]).dropna()
    y_pad = (all_y.max() - all_y.min()) * 0.1 if len(all_y) else 5
    _apply_range_limits(
        fig,
        x_min=has_fatigue["date"].min() - timedelta(days=7),
        x_max=has_fatigue["date"].max() + timedelta(days=7),
        y_min=all_y.min() - y_pad,
        y_max=all_y.max() + y_pad,
    )
    return _clean_layout(fig, title="Training Load & Freshness", height=400)


# ---------------------------------------------------------------------------
# Lifting charts
# ---------------------------------------------------------------------------

def lift_progression_chart(df: pd.DataFrame) -> go.Figure:
    """Line chart of working weights over time for primary lifts."""
    lifts_data = df[df["type"] == "Weight Training"].copy()
    if lifts_data.empty:
        return _empty_chart("No weight training sessions found")

    fig = go.Figure()

    for lift, color in LIFT_COLORS.items():
        col = f"{lift}_weight"
        if col not in lifts_data.columns:
            continue
        subset = lifts_data[lifts_data[col].notna() & (lifts_data[col] > 0)]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["date"], y=subset[col],
            mode="lines+markers", name=lift.title(),
            line=dict(color=color, width=2),
            marker=dict(size=6),
            hovertemplate=f"{lift.title()}: %{{y:.0f}} lbs<extra></extra>",
        ))

    fig.update_xaxes(title="")
    fig.update_yaxes(title="Weight (lbs)")
    weight_cols = [f"{l}_weight" for l in LIFT_COLORS if f"{l}_weight" in lifts_data.columns]
    all_weights = lifts_data[weight_cols].stack().dropna()
    if not all_weights.empty:
        y_pad = (all_weights.max() - all_weights.min()) * 0.05
        _apply_range_limits(
            fig,
            x_min=lifts_data["date"].min() - timedelta(days=7),
            x_max=lifts_data["date"].max() + timedelta(days=7),
            y_min=all_weights.min() - y_pad,
            y_max=all_weights.max() + y_pad,
        )
    return _clean_layout(fig, title="Working Weight Progression", height=400)


def volume_chart(df: pd.DataFrame) -> go.Figure:
    """Bar chart of volume per lift over time (stacked area was buggy)."""
    lifts_data = df[df["type"] == "Weight Training"].copy()
    if lifts_data.empty:
        return _empty_chart("No training volume data")

    fig = go.Figure()

    for lift, color in LIFT_COLORS.items():
        col = f"{lift}_volume"
        if col not in lifts_data.columns:
            continue
        subset = lifts_data[lifts_data[col].notna() & (lifts_data[col] > 0)]
        if subset.empty:
            continue
        fig.add_trace(go.Bar(
            x=subset["date"], y=subset[col],
            name=lift.title(),
            marker_color=color,
            opacity=0.8,
            hovertemplate=f"{lift.title()}: %{{y:,.0f}}<extra></extra>",
        ))

    fig.update_xaxes(title="")
    fig.update_yaxes(title="Volume (sets x reps x weight)")
    vol_cols = [f"{l}_volume" for l in LIFT_COLORS if f"{l}_volume" in lifts_data.columns]
    all_vol = lifts_data[vol_cols].stack().dropna()
    if not all_vol.empty:
        _apply_range_limits(
            fig,
            x_min=lifts_data["date"].min() - timedelta(days=7),
            x_max=lifts_data["date"].max() + timedelta(days=7),
            y_min=0,
            y_max=all_vol.max() * 1.05,
        )
    return _clean_layout(fig, title="Training Volume", height=350, barmode="stack")


def onerm_progression_chart(progression_df: pd.DataFrame,
                             lift_name: str, color: str) -> go.Figure:
    """Line chart of estimated 1RM from the predictions module."""
    if progression_df.empty:
        return _empty_chart(f"No 1RM data for {lift_name}")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=progression_df["date"], y=progression_df["estimated_1rm"],
        mode="lines+markers", name="Ensemble",
        line=dict(color=color, width=3),
        marker=dict(size=6),
        hovertemplate="Est. 1RM: %{y:.0f} lbs<extra></extra>",
    ))

    # Show range band instead of cluttered individual method lines
    method_cols = [c for c in progression_df.columns if c.startswith("1rm_")]
    if method_cols:
        progression_df = progression_df.copy()
        progression_df["_min"] = progression_df[method_cols].min(axis=1)
        progression_df["_max"] = progression_df[method_cols].max(axis=1)

        fig.add_trace(go.Scatter(
            x=progression_df["date"], y=progression_df["_max"],
            mode="lines", line=dict(width=0), showlegend=False,
            hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=progression_df["date"], y=progression_df["_min"],
            mode="lines", line=dict(width=0), showlegend=False,
            fill="tonexty", fillcolor=_hex_to_rgba(color, 0.15),
            name="Model range",
            hoverinfo="skip",
        ))

    fig.update_xaxes(title="")
    fig.update_yaxes(title="Est. 1RM (lbs)")
    y_pad = (progression_df["estimated_1rm"].max() - progression_df["estimated_1rm"].min()) * 0.05
    _apply_range_limits(
        fig,
        x_min=progression_df["date"].min() - timedelta(days=7),
        x_max=progression_df["date"].max() + timedelta(days=7),
        y_min=progression_df["estimated_1rm"].min() - y_pad,
        y_max=progression_df["estimated_1rm"].max() + y_pad,
    )
    return _clean_layout(fig, title=f"{lift_name} — Estimated 1RM", height=350)


# ---------------------------------------------------------------------------
# Estimated 5K time progression
# ---------------------------------------------------------------------------

def est_5k_chart(runs: pd.DataFrame) -> go.Figure:
    """Estimated 5K race time progression.

    Uses runs >= 3 miles to estimate 5K fitness via VDOT.
    Adjusts for altitude and elevation gain. Shows actual races as stars.
    Color-codes by run type. 30-day rolling best for the trend line.
    """
    from strava_analytics.vo2max import daniels_vdot, vdot_to_race_time
    from strava_analytics.predictions import (
        altitude_adjustment_peronnet, elevation_gain_penalty_s,
    )

    if runs.empty:
        return _empty_chart("No runs for 5K estimation")

    df = runs.copy()
    # Only runs >= 3 miles with reasonable pace — short runs extrapolate poorly
    df = df[(df["distance_mi"] >= 3.0) &
            (df["pace_min_per_mi"] >= 6) & (df["pace_min_per_mi"] <= 14)]
    if df.empty:
        return _empty_chart("Need runs of 3+ miles for 5K estimation")

    # Training altitude for adjustment
    elev_high = df["elevation_high_m"].dropna()
    elev_low = df["elevation_low_m"].dropna()
    if not elev_high.empty and not elev_low.empty:
        training_alt_m = (elev_high.mean() + elev_low.mean()) / 2
    else:
        training_alt_m = 1768  # ~5800ft default
    alt_fraction = altitude_adjustment_peronnet(training_alt_m, acclimatized=True)

    est_5k = []
    actual_races = []

    for _, r in df.sort_values("date").iterrows():
        dist_m = r.get("distance_m", 0)
        time_s = r.get("moving_time_s", 0)
        time_min = time_s / 60.0
        run_type = r.get("run_type", "")
        elev_gain_ft = r.get("elevation_gain_ft", 0) or 0
        dist_mi = r.get("distance_mi", 0)

        if dist_m < 4800 or time_min < 15:
            continue

        # VDOT from the run as-performed
        raw_vdot = daniels_vdot(dist_m, time_min)
        adjusted_vdot = raw_vdot

        # Credit for altitude
        if 0 < alt_fraction < 1.0:
            sl_time_min = time_min * alt_fraction
            adjusted_vdot = daniels_vdot(dist_m, sl_time_min)

        # Credit for elevation gain
        if elev_gain_ft > 0 and dist_mi > 0:
            gain_penalty_s = elevation_gain_penalty_s(elev_gain_ft, dist_mi)
            flat_time_min = time_min - (gain_penalty_s / 60)
            if flat_time_min > 0:
                flat_vdot = daniels_vdot(dist_m, flat_time_min)
                adjusted_vdot = max(adjusted_vdot, flat_vdot)

        t5k = vdot_to_race_time(adjusted_vdot, 5000)

        est_5k.append({
            "date": r["date"],
            "est_5k_min": t5k,
            "name": r.get("name", ""),
            "distance_mi": dist_mi,
            "run_type": run_type,
            "date_str": r["date"].strftime("%Y-%m-%d"),
        })

        # Track actual 5K-ish races as ground truth
        if run_type == "race" and 4500 <= dist_m <= 5500:
            actual_races.append({
                "date": r["date"],
                "actual_5k_min": time_min * (5000 / dist_m),
                "name": r.get("name", ""),
            })

    if not est_5k:
        return _empty_chart("Insufficient data for 5K estimate (need 3+ mile runs)")

    edf = pd.DataFrame(est_5k).sort_values("date")

    def _fmt_5k(mins):
        m, s = int(mins), int((mins % 1) * 60)
        return f"{m}:{s:02d}"

    edf["est_5k_str"] = edf["est_5k_min"].apply(_fmt_5k)

    fig = go.Figure()

    # Color-code dots by run type
    type_colors = {
        "race": STRAVA_ORANGE, "workout": ACCENT_TEAL,
        "long": ACCENT_PURPLE, "moderate": ACCENT_YELLOW,
        "easy": ACCENT_GREEN,
    }
    for rtype, color in type_colors.items():
        subset = edf[edf["run_type"] == rtype]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["date"], y=subset["est_5k_min"],
            mode="markers", name=rtype.title(),
            marker=dict(color=color, size=10, opacity=0.8),
            customdata=subset[["name", "distance_mi", "est_5k_str", "date_str"]].values,
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:.1f} mi<br>Est 5K: %{customdata[2]}<extra></extra>",
        ))
    # Any types not in the map
    other = edf[~edf["run_type"].isin(type_colors)]
    if not other.empty:
        fig.add_trace(go.Scatter(
            x=other["date"], y=other["est_5k_min"],
            mode="markers", name="Other",
            marker=dict(color=TEXT_SECONDARY, size=9, opacity=0.7),
            customdata=other[["name", "distance_mi", "est_5k_str", "date_str"]].values,
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:.1f} mi<br>Est 5K: %{customdata[2]}<extra></extra>",
        ))

    # 30-day rolling best (not average) — fitness is best measured by peaks
    if len(edf) >= 3:
        rolling = edf.set_index("date")["est_5k_min"].rolling("30D", min_periods=2).min()
        fig.add_trace(go.Scatter(
            x=rolling.index, y=rolling.values,
            mode="lines", name="30-day best",
            line=dict(color=STRAVA_ORANGE, width=3),
            hovertemplate="Best: %{y:.1f} min<extra></extra>",
        ))

    # Actual race results as stars
    if actual_races:
        adf = pd.DataFrame(actual_races)
        adf["label"] = adf["actual_5k_min"].apply(_fmt_5k)
        fig.add_trace(go.Scatter(
            x=adf["date"], y=adf["actual_5k_min"],
            mode="markers", name="Actual 5K race",
            marker=dict(color=ACCENT_GREEN, size=14, symbol="star",
                         line=dict(width=1, color="white")),
            customdata=adf[["name", "label"]].values,
            hovertemplate="<b>%{customdata[0]}</b><br>Actual: %{customdata[1]}<extra></extra>",
        ))

    fig.update_yaxes(title="5K Time (min)")
    fig.update_xaxes(title="")
    _apply_range_limits(
        fig,
        x_min=edf["date"].min() - timedelta(days=7),
        x_max=edf["date"].max() + timedelta(days=7),
        y_min=edf["est_5k_min"].min() - 0.5,
        y_max=edf["est_5k_min"].max() + 0.5,
        y_reversed=True,
    )
    return _clean_layout(fig, title="Estimated 5K Race Time (altitude + elevation adjusted)", height=380)


# ---------------------------------------------------------------------------
# Activity heatmap (fixed for multi-year data)
# ---------------------------------------------------------------------------

def activity_heatmap(df: pd.DataFrame) -> go.Figure:
    """GitHub-style contribution calendar — uniform cells, color = activity count."""
    import numpy as np

    if df.empty:
        return _empty_chart("No activity data for heatmap")

    # Build daily counts
    daily = df.groupby(df["date"].dt.date).agg(
        count=("activity_id", "count"),
        types=("type", lambda x: ", ".join(x.unique())),
    ).reset_index()
    daily.columns = ["date", "count", "types"]
    daily["date"] = pd.to_datetime(daily["date"])

    # Fill every day in range so the grid has no gaps
    date_range = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    full = pd.DataFrame({"date": date_range})
    full = full.merge(daily, on="date", how="left")
    full["count"] = full["count"].fillna(0).astype(int)
    full["types"] = full["types"].fillna("")

    # Week number (continuous from start) on x-axis, weekday on y-axis
    start = full["date"].min()
    full["week"] = ((full["date"] - start).dt.days // 7).astype(int)
    full["weekday"] = full["date"].dt.weekday  # 0=Mon, 6=Sun

    # Build the 7 x N_weeks grid
    n_weeks = full["week"].max() + 1
    z = np.zeros((7, n_weeks))
    hover_text = [[" "] * n_weeks for _ in range(7)]

    for _, row in full.iterrows():
        w = int(row["week"])
        wd = int(row["weekday"])
        z[wd][w] = row["count"]
        dt = row["date"].strftime("%b %d, %Y")
        c = int(row["count"])
        t = row["types"]
        if c > 0:
            hover_text[wd][w] = f"<b>{dt}</b><br>{t}<br>{c} activit{'y' if c == 1 else 'ies'}"
        else:
            hover_text[wd][w] = f"{dt}<br>Rest day"

    # Month labels for x-axis
    month_ticks = []
    month_labels = []
    for _, row in full.drop_duplicates("week").iterrows():
        if row["date"].day <= 7:  # first week of month
            month_ticks.append(int(row["week"]))
            month_labels.append(row["date"].strftime("%b '%y"))

    fig = go.Figure(go.Heatmap(
        z=z,
        x=list(range(n_weeks)),
        y=list(range(7)),
        text=hover_text,
        hoverinfo="text",
        colorscale=[
            [0, "#f5f5f4"],       # no activity — light gray
            [0.01, "#fde8e8"],    # just above zero — lightest pink
            [0.35, "#fca5a5"],    # moderate
            [0.65, STRAVA_ORANGE],  # active
            [1, ACCENT_RED],      # very active
        ],
        showscale=False,
        xgap=3,
        ygap=3,
        zmin=0,
        zmax=max(3, full["count"].max()),
    ))

    # Default view: last 6 months; user can pan/scroll to see all
    default_weeks = 26
    x_end = n_weeks - 1
    x_start = max(0, x_end - default_weeks)

    fig.update_yaxes(
        tickvals=[0, 1, 2, 3, 4, 5, 6],
        ticktext=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        title="",
        autorange="reversed",
        showgrid=False,
        tickfont=dict(size=12, color="#57534e"),
        fixedrange=True,
    )
    fig.update_xaxes(
        tickvals=month_ticks,
        ticktext=month_labels,
        title="",
        showgrid=False,
        tickfont=dict(size=12, color="#57534e"),
        range=[x_start - 0.5, x_end + 0.5],
        minallowed=-0.5,
        maxallowed=n_weeks - 0.5,
    )

    fig.update_layout(margin=dict(l=50, r=20, t=10, b=40))
    return _clean_layout(fig, title="", height=250, showlegend=False)


# ---------------------------------------------------------------------------
# Monthly volume
# ---------------------------------------------------------------------------

def monthly_volume_chart(df: pd.DataFrame) -> go.Figure:
    """Monthly distance bar chart with activity count overlay."""
    if df.empty:
        return _empty_chart("No data for monthly volume")

    monthly = df.groupby(df["date"].dt.to_period("M")).agg(
        miles=("distance_mi", "sum"),
        hours=("moving_time_s", lambda x: x.sum() / 3600),
        count=("activity_id", "count"),
    ).reset_index()
    monthly["date"] = monthly["date"].astype(str)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly["date"], y=monthly["miles"],
        name="Miles", marker_color=STRAVA_ORANGE,
        hovertemplate="%{y:.1f} mi<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=monthly["date"], y=monthly["count"],
        name="Activities", yaxis="y2",
        mode="lines+markers",
        line=dict(color=ACCENT_TEAL, width=2),
        marker=dict(size=5),
        hovertemplate="%{y} activities<extra></extra>",
    ))

    fig.update_xaxes(title="", tickangle=-45)
    fig.update_yaxes(title="Miles")
    _apply_range_limits(fig, y_min=0, y_max=monthly["miles"].max() * 1.1)
    return _clean_layout(fig,
        title="Monthly Volume", height=350,
        yaxis2=dict(title="Activities", overlaying="y", side="right",
                     gridcolor="rgba(0,0,0,0)"),
    )


# ---------------------------------------------------------------------------
# Training plan calendar
# ---------------------------------------------------------------------------

def plan_calendar_chart(plan_rows: list[dict]) -> go.Figure:
    """Calendar-style view of the training plan.

    Handles multiple workouts on the same day by offsetting vertically.
    """
    if not plan_rows:
        return _empty_chart("No training plan data")

    df = pd.DataFrame(plan_rows)
    df["date"] = pd.to_datetime(df["date"])
    df["weekday"] = df["date"].dt.weekday

    # Offset duplicate day entries so they don't overlap
    # Group by (week, weekday) and add small vertical offset
    df["day_key"] = df["week"].astype(str) + "_" + df["weekday"].astype(str)
    df["offset"] = df.groupby("day_key").cumcount() * 0.4  # shift 2nd workout down
    df["y_pos"] = df["weekday"] + df["offset"]

    colors = [WORKOUT_TYPE_COLORS.get(t, TEXT_SECONDARY) for t in df["type"]]

    # Build labels: first letter of type, or "R+L" for double days
    labels = []
    for _, r in df.iterrows():
        t = r["type"]
        labels.append({"lift": "L", "run": "R", "rest": "-", "obstacle": "O",
                        "mobility": "M"}.get(t, t[0].upper()))

    fig = go.Figure(go.Scatter(
        x=df["week"],
        y=df["y_pos"],
        mode="markers+text",
        marker=dict(size=26, color=colors, symbol="square",
                     line=dict(width=1, color="rgba(255,255,255,0.15)")),
        text=labels,
        textfont=dict(color="white", size=10),
        hovertext=df.apply(
            lambda r: f"<b>{r['title']}</b><br>{r['day_name']}, {r['date'].strftime('%b %d')}<br>{r['intensity']}",
            axis=1,
        ),
        hoverinfo="text",
    ))

    fig.update_yaxes(
        tickvals=[0, 1, 2, 3, 4, 5, 6],
        ticktext=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        autorange="reversed", title="",
        range=[-0.5, 7.2],  # extra room for offset items
    )
    fig.update_xaxes(
        title="Week", dtick=1,
        autorangeoptions=dict(
            minallowed=df["week"].min() - 0.5,
            maxallowed=df["week"].max() + 0.5,
        ),
    )
    return _clean_layout(fig, title="8-Week Training Plan", height=320, showlegend=False)
