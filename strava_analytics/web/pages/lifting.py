"""Lifting / strength training page — ozniai.com subpage pattern."""

import pandas as pd
import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table

from strava_analytics.web import data
from strava_analytics.web.components.cards import metric_cell, metric_grid
from strava_analytics.web.components import charts
from strava_analytics.web.components.layout import (
    hero_section, page_section, statement_section, feature_grid,
    numbered_card, cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, ACCENT_RED,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, LIFT_COLORS,
    BG_CARD, BORDER, FONT_MONO,
)
from strava_analytics.predictions import extract_1rm_progression
from strava_analytics.lifting_program import BASELINE, END_PRS
from strava_analytics.strength_model import fit_all_lifts, project_1rm, compute_interference

dash.register_page(__name__, path="/lifting", name="Lifting")



def _strength_projections_section(df: pd.DataFrame) -> html.Div:
    """Build a Strength Projections section using the log-curve model."""
    fits = fit_all_lifts(df)
    if not fits or all(f.get("current_1rm", 0) <= 0 for f in fits.values()):
        return html.Div()

    # Compute weekly run miles for interference
    runs = df[df["type"] == "Run"].copy()
    weekly_run_miles = 0.0
    if not runs.empty:
        recent = runs[runs["date"] >= runs["date"].max() - pd.Timedelta(weeks=8)]
        if not recent.empty:
            weeks = max((recent["date"].max() - recent["date"].min()).days / 7.0, 1.0)
            weekly_run_miles = recent["distance_mi"].sum() / weeks

    interference = compute_interference(weekly_run_miles)
    weeks_ahead = 8

    projection_cards = []
    for i, (lift, params) in enumerate(fits.items(), 1):
        current = params.get("current_1rm", 0)
        if current <= 0:
            continue
        projected = project_1rm(params, weeks_ahead, interference)
        delta = projected - current
        delta_pct = (delta / current) * 100 if current > 0 else 0
        sign = "+" if delta >= 0 else ""
        color_map = {"bench": ACCENT, "squat": ACCENT_SLATE,
                     "deadlift": ACCENT_AMBER, "ohp": ACCENT_SLATE}
        lift_display = {"bench": "Bench", "squat": "Squat",
                        "deadlift": "Deadlift", "ohp": "OHP"}.get(lift, lift.title())
        projection_cards.append(numbered_card(
            i, lift_display,
            f"{current:.0f} \u2192 {projected:.0f} lbs ({sign}{delta_pct:.1f}%)",
            value=f"{projected:.0f} lbs",
            color=color_map.get(lift, ACCENT),
        ))

    interference_note = html.P(
        f"Interference factor: {interference:.2f} "
        f"(~{weekly_run_miles:.0f} mi/week running). "
        f"Projecting {weeks_ahead} weeks ahead.",
        style={"color": TEXT_MUTED, "fontSize": "12px", "marginTop": "16px"},
    )

    return page_section("STRENGTH PROJECTIONS", [
        feature_grid(projection_cards, columns=min(len(projection_cards), 4)),
        interference_note,
    ])


def layout(**_kwargs):
    df = data.get_df()
    lifts = data.get_lifts()
    baseline = BASELINE
    end_prs = END_PRS

    if lifts.empty:
        return html.P("No weight training data available.")

    # Gains
    bench_gain = ((end_prs.get("bench_1rm", 0) / max(baseline.get("bench_1rm", 1), 1)) - 1) * 100
    squat_gain = ((end_prs.get("squat_1rm", 0) / max(baseline.get("squat_1rm", 1), 1)) - 1) * 100
    dl_gain = ((end_prs.get("deadlift_1rm", 0) / max(baseline.get("deadlift_1rm", 1), 1)) - 1) * 100

    # 1RM progression charts
    onerm_charts = []
    onerm_ids = []
    for lift_name, color in LIFT_COLORS.items():
        prog = extract_1rm_progression(df, lift_name)
        if not prog.empty:
            chart_id = f"onerm-{lift_name}"
            onerm_ids.append(chart_id)
            onerm_charts.append(
                dbc.Col(
                    charts.onerm_progression_chart(prog, lift_name.title(), color, chart_id=chart_id),
                    md=6,
                )
            )

    return html.Div([
        # Hero
        hero_section(
            label="STRENGTH",
            headline="Heavy things don't lift themselves.",
            subtext=(
                f"{len(lifts)} sessions. {baseline.get('weight_lbs', 175)} lbs. "
                f"Program: Jan 9 \u2014 Apr 3, 2026."
            ),
        ),

        # Current Maxes
        page_section("CURRENT MAXES", [
            feature_grid([
                numbered_card(1, "Bench Press",
                              f"+{bench_gain:.0f}% from {baseline.get('bench_1rm', '?')}",
                              value=f"{end_prs.get('bench_1rm', '?')} lbs",
                              color=LIFT_COLORS["bench"]),
                numbered_card(2, "Squat",
                              f"+{squat_gain:.0f}% from {baseline.get('squat_1rm', '?')}",
                              value=f"{end_prs.get('squat_1rm', '?')} lbs",
                              color=LIFT_COLORS["squat"]),
                numbered_card(3, "Deadlift",
                              f"+{dl_gain:.0f}% from {baseline.get('deadlift_1rm', '?')}",
                              value=f"{end_prs.get('deadlift_1rm', '?')} lbs",
                              color=LIFT_COLORS["deadlift"]),
                numbered_card(4, "Program Days", "completed",
                              value=str(len(lifts)),
                              color=ACCENT),
            ], columns=4),
        ]),

        # Statement
        statement_section(
            "PROGRESS",
            f"Bench up {bench_gain:.0f}%. Squat up {squat_gain:.0f}%. "
            "The barbell doesn\u2019t lie.",
        ),

        # Working Weight Progression
        page_section("WORKING WEIGHT PROGRESSION", [
            charts.lift_progression_chart(df),
        ], alt_bg=True),

        # Estimated 1RM
        page_section("ESTIMATED 1RM \u2014 5-FORMULA ENSEMBLE", [
            dbc.Row(onerm_charts, className="g-3"),
        ]),

        # Baseline vs Current
        page_section("BASELINE VS CURRENT", [
            dbc.Row([
                dbc.Col([
                    html.Div("START (JAN 2026)", className="metric-label",
                             style={"marginBottom": "12px", "fontSize": "0.65rem"}),
                    _baseline_grid(baseline),
                ], md=6),
                dbc.Col([
                    html.Div("CURRENT", className="metric-label",
                             style={"marginBottom": "12px", "fontSize": "0.65rem"}),
                    _current_grid(baseline, end_prs),
                ], md=6),
            ]),
        ], alt_bg=True),

        # Volume
        page_section("TRAINING VOLUME", [
            charts.volume_chart(df),
        ]),

        # Strength Projections
        _strength_projections_section(df),

        # CTA
        cta_section(
            "Want every session?",
            "All activities in one feed.",
            "View Activities \u2192", "/activities",
        ),

        # Footer
        footer(),
    ])


def _baseline_grid(baseline: dict) -> html.Div:
    cells = []
    metrics = [
        ("Body Weight", f"{baseline.get('weight_lbs', '')} lbs"),
        ("Bench 1RM", f"{baseline.get('bench_1rm', '')} lbs"),
        ("Squat 1RM", f"{baseline.get('squat_1rm', '')} lbs"),
        ("Deadlift 1RM", f"{baseline.get('deadlift_1rm', '')} lbs"),
        ("OHP 1RM", f"{baseline.get('ohp_1rm', '')} lbs"),
        ("Max Pull-ups", str(baseline.get('max_pullups', ''))),
    ]
    for label, val in metrics:
        cells.append(metric_cell(label, val))
    return metric_grid(cells)


def _current_grid(baseline: dict, end_prs: dict) -> html.Div:
    cells = []

    def _delta(key, current_val):
        base = baseline.get(key, 0)
        if base and current_val and isinstance(base, (int, float)):
            pct = ((current_val / base) - 1) * 100
            return f"+{pct:.0f}%" if pct > 0 else f"{pct:.0f}%"
        return ""

    pr_metrics = [
        ("Bench 1RM", end_prs.get("bench_1rm"), "bench_1rm"),
        ("Squat 1RM", end_prs.get("squat_1rm"), "squat_1rm"),
        ("Deadlift 1RM", end_prs.get("deadlift_1rm"), "deadlift_1rm"),
    ]

    for label, val, key in pr_metrics:
        delta = _delta(key, val)
        color = ACCENT_SLATE if delta.startswith("+") else ACCENT_RED
        cells.append(metric_cell(label, f"{val} lbs" if val else "\u2014",
                                  delta, color))

    pullup_val = end_prs.get("max_pullups", "")
    cells.append(metric_cell("Max Pull-ups", str(pullup_val) if pullup_val else "\u2014",
                              _delta("max_pullups", pullup_val) if pullup_val else "",
                              ACCENT_SLATE))

    return metric_grid(cells)


from strava_analytics.web.components.cards import stat_cell as _stat_cell


def _dominant_lift_color(session):
    """Return the LIFT_COLORS color for the heaviest primary lift in a session."""
    lifts_and_colors = [
        ("bench_weight", "bench"),
        ("squat_weight", "squat"),
        ("deadlift_weight", "deadlift"),
        ("ohp_weight", "ohp"),
    ]
    best_weight = 0
    best_color = LIFT_COLORS.get("bench", ACCENT)
    for col, key in lifts_and_colors:
        w = session.get(col, None)
        if w is not None and not pd.isna(w) and w > best_weight:
            best_weight = w
            best_color = LIFT_COLORS.get(key, ACCENT)
    return best_color


def _lift_card(session, idx):
    """Build an expandable <details> card for a single lift session."""
    date_str = session["date"].strftime("%b %d, %Y")
    day_str = session["date"].strftime("%A")
    program_day = session.get("program_day", None)

    # -- Summary: lift icon cards in a compact grid --
    _LIFT_ICONS = {
        "bench": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="24" x2="42" y2="24"/><rect x="10" y="18" width="4" height="12" rx="1"/><rect x="34" y="18" width="4" height="12" rx="1"/><circle cx="6" cy="24" r="3"/><circle cx="42" cy="24" r="3"/></svg>',
        "squat": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="8" y1="14" x2="40" y2="14"/><rect x="12" y="8" width="3" height="12" rx="1"/><rect x="33" y="8" width="3" height="12" rx="1"/><circle cx="8" cy="14" r="2.5"/><circle cx="40" cy="14" r="2.5"/><path d="M18 20 L18 30 Q18 36 24 38 Q30 36 30 30 L30 20"/></svg>',
        "deadlift": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="34" x2="42" y2="34"/><rect x="10" y="28" width="4" height="12" rx="1"/><rect x="34" y="28" width="4" height="12" rx="1"/><circle cx="6" cy="34" r="3"/><circle cx="42" cy="34" r="3"/><path d="M20 34 L20 18 M28 34 L28 18"/><line x1="18" y1="18" x2="30" y2="18"/></svg>',
        "ohp": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="8" y1="10" x2="40" y2="10"/><rect x="12" y="4" width="3" height="12" rx="1"/><rect x="33" y="4" width="3" height="12" rx="1"/><circle cx="8" cy="10" r="2.5"/><circle cx="40" cy="10" r="2.5"/><path d="M20 16 L20 34 M28 16 L28 34"/></svg>',
    }

    stat_cells = []
    for label, col, sets_col, reps_col, icon_key in [
        ("Bench", "bench_weight", "bench_sets", "bench_reps", "bench"),
        ("Squat", "squat_weight", "squat_sets", "squat_reps", "squat"),
        ("Deadlift", "deadlift_weight", "deadlift_sets", "deadlift_reps", "deadlift"),
        ("OHP", "ohp_weight", "ohp_sets", "ohp_reps", "ohp"),
    ]:
        val = session.get(col, None)
        if val is None or pd.isna(val):
            continue
        sets = session.get(sets_col, None)
        reps = session.get(reps_col, None)
        scheme = ""
        if sets and not pd.isna(sets) and reps and not pd.isna(reps):
            scheme = f"{int(sets)}x{int(reps)}"

        svg = _LIFT_ICONS.get(icon_key, "")
        icon_div = html.Div(
            style={
                "width": "24px", "height": "24px",
                "color": LIFT_COLORS.get(icon_key, TEXT_MUTED),
                "flexShrink": "0",
            },
            **{"data-svg-icon": svg},
        ) if svg else html.Div()

        stat_cells.append(html.Div([
            icon_div,
            html.Div([
                html.Div(f"{val:.0f}", style={
                    "fontFamily": FONT_MONO,
                    "fontSize": "15px", "fontWeight": "700",
                    "color": TEXT_PRIMARY, "lineHeight": "1",
                }),
                html.Div(scheme, style={
                    "fontSize": "10px", "color": TEXT_MUTED,
                }) if scheme else None,
            ]),
        ], style={
            "display": "flex", "gap": "6px", "alignItems": "center",
        }))

    # Add HR + calories to summary
    avg_hr = session.get("avg_hr", None)
    if avg_hr is not None and not pd.isna(avg_hr):
        stat_cells.append(_stat_cell("HR", f"{avg_hr:.0f} bpm"))
    cals = session.get("calories", None)
    if cals is not None and not pd.isna(cals) and cals > 0:
        stat_cells.append(_stat_cell("Cal", f"{cals:.0f}"))

    # Program day badge
    badge = []
    if program_day is not None and not pd.isna(program_day):
        badge.append(html.Span(
            f"DAY {int(program_day)}",
            style={
                "fontSize": "10px", "fontWeight": "700",
                "letterSpacing": "0.08em", "color": TEXT_MUTED,
                "border": f"1px solid {BORDER}", "borderRadius": "4px",
                "padding": "2px 8px", "marginLeft": "12px",
            },
        ))

    summary_row = html.Summary([
        html.Div([
            html.Div([
                html.Span(date_str, style={
                    "fontFamily": FONT_MONO,
                    "fontSize": "14px", "fontWeight": "600",
                    "color": TEXT_PRIMARY,
                }),
                html.Span(f"  {day_str}", style={
                    "fontSize": "12px", "color": TEXT_MUTED, "marginLeft": "8px",
                }),
                *badge,
            ], style={"marginBottom": "6px"}),
            html.Div(stat_cells, style={
                "display": "flex", "gap": "16px", "flexWrap": "wrap",
            }),
        ]),
    ], style={
        "listStyle": "none", "cursor": "pointer", "padding": "14px 18px",
    })

    # -- Expanded detail content --
    detail_items = []

    # Exercise list — compact inline format instead of bullet list
    exercises_str = session.get("lift_exercises", "")
    if exercises_str and not pd.isna(exercises_str):
        exercises = [e.strip() for e in str(exercises_str).split(";") if e.strip()]
        if exercises:
            detail_items.append(html.Div([
                html.Div("EXERCISES", style={
                    "fontSize": "10px", "fontWeight": "600",
                    "textTransform": "uppercase", "letterSpacing": "0.1em",
                    "color": TEXT_MUTED, "marginBottom": "6px",
                }),
                html.Div(
                    " · ".join(exercises),
                    style={"fontSize": "12px", "color": TEXT_SECONDARY,
                           "lineHeight": "1.6"},
                ),
            ], style={"marginBottom": "12px"}))

    # Pullup stats
    pullup_sets = session.get("pullup_sets", None)
    pullup_reps = session.get("pullup_reps", None)
    has_pullup_sets = pullup_sets is not None and not pd.isna(pullup_sets)
    has_pullup_reps = pullup_reps is not None and not pd.isna(pullup_reps)
    if has_pullup_sets or has_pullup_reps:
        parts = []
        if has_pullup_sets:
            parts.append(f"{int(pullup_sets)} sets")
        if has_pullup_reps:
            parts.append(f"{int(pullup_reps)} reps")
        detail_items.append(html.Div([
            _stat_cell("Pull-ups", " / ".join(parts)),
        ], style={"marginBottom": "8px"}))

    # Total session volume
    volume_cols = [c for c in ["bench_volume", "squat_volume", "deadlift_volume",
                                "ohp_volume"] if c in session.index]
    total_vol = 0
    for vc in volume_cols:
        v = session.get(vc, 0)
        if v is not None and not pd.isna(v):
            total_vol += v
    if total_vol > 0:
        detail_items.append(
            _stat_cell("Session Volume", f"{total_vol:,.0f} lbs")
        )

    detail_div = html.Div(detail_items, style={
        "padding": "0 18px 14px 18px",
        "borderTop": f"1px solid {BORDER}",
        "paddingTop": "12px",
    }) if detail_items else html.Div()

    border_color = _dominant_lift_color(session)

    return html.Details([
        summary_row,
        detail_div,
    ], style={
        "backgroundColor": BG_CARD,
        "borderRadius": "8px",
        "border": f"1px solid {BORDER}",
        "borderLeft": f"3px solid {border_color}",
        "marginBottom": "10px",
    })


def _build_session_cards(lifts):
    """Return a list of expandable lift-session cards sorted by date descending."""
    if lifts.empty:
        return []
    sorted_lifts = lifts.sort_values("date", ascending=False)
    return [_lift_card(row, idx) for idx, (_, row) in enumerate(sorted_lifts.iterrows())]


def _build_program_table(lifts):
    if lifts.empty:
        return html.P("No data.", style={"color": TEXT_MUTED})

    display = lifts[lifts["program_day"].notna()].copy()
    if display.empty:
        return html.P("No mapped program days.", style={"color": TEXT_MUTED})

    display = display.sort_values("program_day")
    table_data = []
    for _, row in display.iterrows():
        table_data.append({
            "Day": int(row["program_day"]) if row["program_day"] == row["program_day"] else "",
            "Date": row["date"].strftime("%b %d") if hasattr(row["date"], "strftime") else str(row["date"]),
            "Exercises": row.get("lift_exercises", ""),
        })

    return dash_table.DataTable(
        data=table_data,
        columns=[{"name": c, "id": c} for c in ["Day", "Date", "Exercises"]],
        style_cell={
            "textAlign": "left",
            "backgroundColor": BG_CARD,
            "color": TEXT_PRIMARY,
            "border": "none",
            "borderBottom": f"1px solid {BORDER}",
            "fontSize": "0.8rem",
            "padding": "10px 14px",
            "whiteSpace": "normal",
            "maxWidth": "600px",
        },
        style_header={
            "backgroundColor": BG_CARD,
            "fontWeight": "600",
            "color": TEXT_MUTED,
            "textTransform": "uppercase",
            "fontSize": "0.65rem",
            "letterSpacing": "0.08em",
            "border": "none",
            "borderBottom": f"1px solid {BORDER}",
            "padding": "10px 14px",
        },
        style_data_conditional=[{
            "if": {"column_id": "Day"},
            "fontFamily": FONT_MONO,
            "fontWeight": "600",
            "width": "50px",
        }, {
            "if": {"column_id": "Date"},
            "fontFamily": FONT_MONO,
            "width": "80px",
            "color": TEXT_MUTED,
        }],
        page_size=36,
        style_table={"overflowX": "auto"},
    )


charts.register_chart_callback("lift-prog")
charts.register_chart_callback("volume")
for _lift in LIFT_COLORS:
    charts.register_chart_callback(f"onerm-{_lift}")
