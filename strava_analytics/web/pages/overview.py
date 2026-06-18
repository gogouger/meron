"""Overview — hybrid landing page modeled on MERON homepage."""

import calendar
from datetime import date, timedelta

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, Output, Input, State
import pandas as pd

from strava_analytics.web import data
from strava_analytics.web.components import charts
from strava_analytics.web.components.layout import (
    hero_section, page_section, statement_section, feature_grid,
    numbered_card, cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, ACCENT_RED,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BG_CARD, BORDER,
    ACTIVITY_TYPE_COLORS, FONT_MONO,
)
from strava_analytics.metrics import format_pace
from strava_analytics.vo2max import compute_athlete_vdot
from strava_analytics.critical_speed import fit_critical_speed, cs_to_vdot
from strava_analytics.lifting_program import END_PRS
from strava_analytics.fitness import compute_trends, detect_prs, year_summary

dash.register_page(__name__, path="/", name="Overview")


_CELL_SIZE = "32px"
_WEEK_GRID = {
    "display": "grid",
    "gridTemplateColumns": f"repeat(7, {_CELL_SIZE}) 40px",
    "gap": "3px",
    "justifyContent": "center",
    "alignItems": "center",
}
_DOW_GRID = {
    "display": "grid",
    "gridTemplateColumns": f"repeat(7, {_CELL_SIZE}) 40px",
    "gap": "3px",
    "justifyContent": "center",
}
_CELL_BASE = {
    "width": _CELL_SIZE, "height": _CELL_SIZE,
    "borderRadius": "50%",
    "display": "flex", "alignItems": "center", "justifyContent": "center",
    "fontSize": "11px", "fontWeight": "500",
    "position": "relative",
}


def _hover_card(activities_list, date_str: str):
    """Build a hover tooltip showing clickable activity cards for a day."""
    if not activities_list:
        return None
    cards = []
    for act in activities_list:
        color = ACTIVITY_TYPE_COLORS.get(act["type"], "var(--text-muted)")
        dist = act.get("distance_mi", 0)
        pace = act.get("pace_min_per_mi", None)
        time_s = act.get("moving_time_s", 0)

        if time_s and time_s > 0:
            h, m = int(time_s // 3600), int((time_s % 3600) // 60)
            dur = f"{h}:{m:02d}:{int(time_s%60):02d}" if h else f"{m}:{int(time_s%60):02d}"
        else:
            dur = ""

        pace_str = ""
        if pace and not pd.isna(pace) and pace > 0:
            pm, ps = int(pace), int((pace - int(pace)) * 60)
            pace_str = f"{pm}:{ps:02d}/mi"

        stats = []
        if dist and dist > 0:
            stats.append(f"{dist:.1f} mi")
        if pace_str:
            stats.append(pace_str)
        if dur:
            stats.append(dur)

        # Determine target page based on activity type
        target = "/running" if act["type"] in ("Run", "Walk", "Hike") else "/lifting" if act["type"] == "Weight Training" else None

        row = html.Div([
            html.Div([
                html.Span(style={
                    "width": "8px", "height": "8px", "borderRadius": "50%",
                    "background": color, "display": "inline-block",
                    "marginRight": "6px", "flexShrink": "0",
                }),
                html.Span(act.get("name", act["type"]), className="cal-hover-name", style={
                    "fontSize": "11px", "fontWeight": "600",
                    "overflow": "hidden", "textOverflow": "ellipsis",
                    "whiteSpace": "nowrap",
                }),
            ], style={"display": "flex", "alignItems": "center"}),
            html.Div(" \u00b7 ".join(stats), className="cal-hover-stats", style={
                "fontSize": "10px", "marginTop": "2px",
                "paddingLeft": "14px",
            }) if stats else None,
        ], className="cal-activity-link",
           style={"marginBottom": "4px", "cursor": "pointer" if target else "default",
                   "padding": "2px 4px", "borderRadius": "4px"},
           **{"data-date": date_str, "data-target": target or ""})

        cards.append(row)

    return html.Div(cards, className="cal-hover-card", style={
        "display": "none",
        "position": "absolute", "bottom": "110%", "left": "50%",
        "transform": "translateX(-50%)",
        "zIndex": "100",
        "padding": "8px 10px",
        "borderRadius": "6px",
        "borderColor": "var(--border)",
        "minWidth": "180px", "maxWidth": "240px",
    })


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a hex color to rgba() string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _week_badge(count: int) -> html.Div:
    """Simple pill badge coloured by weekly activity count."""
    if count <= 2:
        color = ACCENT_SLATE
    elif count <= 4:
        color = ACCENT_AMBER
    else:
        color = ACCENT

    return html.Div(str(count), style={
        "fontSize": "10px", "fontWeight": "700",
        "color": color,
        "backgroundColor": _hex_to_rgba(color, 0.12),
        "borderRadius": "8px", "padding": "2px 6px",
        "textAlign": "center", "lineHeight": "1.2",
        "fontFamily": FONT_MONO,
    })


def _build_month(year: int, month: int, daily: dict, latest, month_label_text: str):
    """Build a single month block for the calendar."""

    month_label = html.Div(month_label_text, className="cal-month-label", style={
        "fontSize": "13px", "fontWeight": "700", "textAlign": "center",
        "marginBottom": "6px",
    })

    dow_header = html.Div(
        [html.Div(d, className="cal-dow-label", style={
            "textAlign": "center", "fontSize": "10px", "fontWeight": "600",
        }) for d in ["M", "T", "W", "T", "F", "S", "S"]]
        + [html.Div()],  # empty cell for the meta column
        style={**_DOW_GRID, "marginBottom": "2px"},
    )

    cal = calendar.monthcalendar(year, month)
    week_rows = []
    for week in cal:
        cells = []
        week_activity_count = 0
        for day_num in week:
            if day_num == 0:
                cells.append(html.Div(style={"width": _CELL_SIZE, "height": _CELL_SIZE}))
                continue

            d = date(year, month, day_num)
            activities = daily.get(d, [])
            is_future = d > latest

            if is_future:
                cell = html.Div(str(day_num), className="cal-day-future",
                                style=_CELL_BASE)
            elif activities:
                week_activity_count += len(activities)
                primary_color = ACTIVITY_TYPE_COLORS.get(activities[0]["type"], ACCENT)

                # Dot indicators per unique activity type
                seen = []
                for act in activities:
                    c = ACTIVITY_TYPE_COLORS.get(act["type"], ACCENT)
                    if c not in seen:
                        seen.append(c)
                dots_row = html.Div(
                    [html.Span(style={
                        "width": "5px", "height": "5px", "borderRadius": "50%",
                        "background": c, "display": "inline-block",
                    }) for c in seen[:3]],
                    style={
                        "position": "absolute", "bottom": "2px",
                        "display": "flex", "gap": "2px",
                        "justifyContent": "center", "width": "100%",
                    },
                )

                hover = _hover_card(activities, d.strftime("%Y-%m-%d"))

                cell = html.Div(
                    [
                        html.Span(str(day_num), className="cal-day-num"),
                        dots_row,
                        hover,
                    ],
                    className="cal-day-active",
                    style={
                        **_CELL_BASE,
                        "border": f"2px solid {primary_color}",
                        "flexDirection": "column",
                        "cursor": "pointer",
                    },
                )
            else:
                cell = html.Div(str(day_num), className="cal-day-inactive",
                                style=_CELL_BASE)

            cells.append(cell)

        # Weekly meta column — flame icon that heats up with activity count
        if week_activity_count > 0:
            meta = _week_badge(week_activity_count)
        else:
            meta = html.Div(style={"width": "40px", "height": "28px"})
        cells.append(meta)

        week_rows.append(html.Div(cells, style={**_WEEK_GRID, "marginBottom": "3px"}))

    return html.Div([month_label, dow_header, *week_rows], style={
        "flex": "1", "minWidth": "280px", "maxWidth": "320px",
    })


def _activity_calendar(df: pd.DataFrame, months: int = 3, offset: int = 0) -> html.Div:
    """Strava-style HTML/CSS activity calendar — outlined circles with accent dots.

    offset: number of months to shift back from the latest month (0 = current).
    """
    if df.empty:
        return html.P("No activity data.", style={"color": TEXT_MUTED})

    daily = {}
    for _, row in df.iterrows():
        d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
        daily.setdefault(d, []).append({
            "type": row["type"],
            "name": row.get("name", ""),
            "distance_mi": row.get("distance_mi", 0),
            "pace_min_per_mi": row.get("pace_min_per_mi", None),
            "moving_time_s": row.get("moving_time_s", 0),
        })

    latest = df["date"].max().date() if hasattr(df["date"].max(), "date") else df["date"].max()

    # Collect month starts (most recent N, shifted by offset)
    month_starts = []
    d = date(latest.year, latest.month, 1)
    # Shift back by offset months
    for _ in range(offset):
        d = (d - timedelta(days=1)).replace(day=1)
    for _ in range(months):
        month_starts.append(d)
        d = (d - timedelta(days=1)).replace(day=1)
    month_starts.reverse()

    month_blocks = [
        _build_month(ms.year, ms.month, daily, latest, ms.strftime("%b %Y"))
        for ms in month_starts
    ]

    # Legend
    legend_items = []
    for atype, color in ACTIVITY_TYPE_COLORS.items():
        legend_items.append(html.Span([
            html.Span(style={
                "display": "inline-block", "width": "8px", "height": "8px",
                "borderRadius": "50%", "border": f"2px solid {color}",
                "marginRight": "4px", "verticalAlign": "middle",
            }),
            html.Span(atype, className="cal-legend-text", style={"fontSize": "10px"}),
        ], style={"marginRight": "14px"}))

    legend = html.Div(legend_items, style={
        "display": "flex", "flexWrap": "wrap", "gap": "4px",
        "marginTop": "16px", "justifyContent": "center",
    })

    return html.Div([
        # Months in a horizontal row on desktop, wrapping on mobile
        html.Div(month_blocks, style={
            "display": "flex", "gap": "24px",
            "justifyContent": "center", "flexWrap": "wrap",
        }),
        legend,
    ])


def _trends_section(df: pd.DataFrame) -> html.Div:
    """90-day vs 365-day trend comparison (Apple Fitness style)."""
    trends = compute_trends(df)
    if not trends:
        return html.Div()

    cards = []
    for t in trends:
        is_improving = t["direction"] == "improving"
        arrow = "\u2191" if (t["delta_pct"] > 0) else "\u2193"
        arrow_color = ACCENT_SLATE if is_improving else ACCENT_RED
        delta_str = f"{arrow} {abs(t['delta_pct']):.0f}%"

        cards.append(html.Div([
            html.Div(t["metric"], style={
                "fontSize": "10px", "fontWeight": "500",
                "textTransform": "uppercase", "letterSpacing": "0.1em",
                "color": TEXT_MUTED, "marginBottom": "4px",
            }),
            html.Div(f"{t['recent']}", style={
                "fontFamily": FONT_MONO,
                "fontSize": "20px", "fontWeight": "600",
                "color": TEXT_PRIMARY,
            }),
            html.Div([
                html.Span(delta_str, style={
                    "color": arrow_color, "fontWeight": "600",
                    "fontSize": "12px",
                }),
                html.Span(f" vs {t['baseline']}", style={
                    "color": TEXT_MUTED, "fontSize": "11px",
                }),
            ], style={"marginTop": "4px"}),
            html.Div(t["unit"], style={
                "fontSize": "10px", "color": TEXT_MUTED, "marginTop": "2px",
            }),
        ], style={
            "padding": "16px", "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER}",
        }))

    return page_section("TRENDS", [
        html.P("Last 90 days vs prior year baseline.",
               style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                      "marginBottom": "16px"}),
        html.Div(cards, style={
            "display": "grid",
            "gridTemplateColumns": f"repeat({min(len(cards), 5)}, 1fr)",
            "gap": "12px",
        }),
    ], alt_bg=True)


def _prs_section(df: pd.DataFrame) -> html.Div:
    """Personal records across standard race distances (best effort within any run)."""
    efforts_df = data.get_best_efforts()
    prs = detect_prs(df, efforts_df=efforts_df)
    if not prs:
        return html.Div()

    year = df["date"].max().year

    # Build expandable PR cards per distance
    pr_cards = []
    for pr in prs:
        # All-time best header
        time_str = pr["best_time"]
        pace_str = pr["best_pace"]
        display_val = f"{time_str}  ({pace_str} /mi)" if time_str else f"{pace_str} /mi"

        # Year best
        year_row = None
        if pr["year_best"]:
            yb = pr["year_best"]
            yr_val = f"{yb['time']}  ({yb['pace']} /mi)" if yb.get("time") else f"{yb['pace']} /mi"
            year_row = html.Div([
                html.Span(f"{year} best: ", style={
                    "color": TEXT_MUTED, "fontSize": "11px",
                }),
                html.Span(yr_val, style={
                    "fontFamily": FONT_MONO,
                    "fontSize": "12px", "fontWeight": "600",
                }),
                html.Span(f" — {yb['date']}", style={
                    "color": TEXT_MUTED, "fontSize": "11px",
                }),
            ], style={"marginTop": "4px"})

        # Top 3 as compact rows with date and link
        top3_rows = []
        for eff in pr.get("top3", []):
            time_str = eff.get("time", "")
            pace_str = eff.get("pace", "")
            rank_color = ACCENT if eff["rank"] == 1 else (
                ACCENT_SLATE if eff["rank"] == 2 else TEXT_MUTED)
            top3_rows.append(html.Div([
                html.Span(f"#{eff['rank']}", style={
                    "fontWeight": "700", "fontSize": "11px",
                    "color": rank_color,
                    "minWidth": "24px", "display": "inline-block",
                }),
                html.Span(time_str if time_str else pace_str, style={
                    "fontFamily": FONT_MONO, "fontSize": "12px",
                    "fontWeight": "600", "minWidth": "55px",
                    "display": "inline-block",
                }),
                html.Span(f"{pace_str} /mi", style={
                    "fontFamily": FONT_MONO, "fontSize": "11px",
                    "color": TEXT_SECONDARY, "minWidth": "65px",
                    "display": "inline-block",
                }) if time_str else None,
                html.Span(eff["date"], style={
                    "fontSize": "11px", "color": TEXT_MUTED,
                    "minWidth": "85px", "display": "inline-block",
                }),
                html.A(eff["name"] or "View run", href="/activities", style={
                    "fontSize": "11px", "color": ACCENT,
                    "textDecoration": "none",
                }),
            ], style={"padding": "4px 0", "display": "flex",
                      "alignItems": "baseline", "gap": "8px"}))

        # Detail: year best + top 3
        detail_children = []
        if year_row:
            detail_children.append(year_row)
        if top3_rows:
            detail_children.append(html.Div(top3_rows, style={
                "marginTop": "8px", "paddingTop": "8px",
                "borderTop": f"1px solid {BORDER}",
            }))

        # Summary: just distance + time/pace, clean and minimal
        card = html.Details([
            html.Summary([
                html.Div([
                    html.Span(pr["distance"], style={
                        "fontWeight": "700", "fontSize": "14px",
                        "minWidth": "120px", "display": "inline-block",
                    }),
                    html.Span(display_val, style={
                        "fontFamily": FONT_MONO,
                        "fontSize": "16px", "fontWeight": "600",
                        "color": ACCENT,
                    }),
                ], style={"display": "flex", "alignItems": "baseline",
                          "gap": "8px"}),
            ], style={"listStyle": "none", "cursor": "pointer",
                      "padding": "12px 16px"}),
            html.Div(detail_children, style={
                "padding": "0 16px 12px",
            }) if detail_children else None,
        ], style={
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER}",
            "marginBottom": "4px",
        })
        pr_cards.append(card)

    return page_section("PERSONAL RECORDS", [
        html.P("Best efforts within any run — fastest segment at each distance.",
               style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                      "marginBottom": "16px"}),
        html.Div(pr_cards),
    ])


def _year_section(df: pd.DataFrame) -> html.Div:
    """Year in Review annual summary."""
    summary = year_summary(df)
    if not summary:
        return html.Div()

    year = summary["year"]

    stat_items = [
        ("Activities", str(summary["total_activities"])),
        ("Miles", f"{summary['total_miles']:,.1f}"),
        ("Hours", f"{summary['total_hours']:,.1f}"),
        ("Elevation", f"{summary['total_elevation_ft']:,} ft"),
        ("Active Days", str(summary["active_days"])),
        ("Runs", str(summary["total_runs"])),
        ("Lifts", str(summary["total_lifts"])),
    ]
    if "avg_pace" in summary:
        stat_items.append(("Avg Pace", f"{summary['avg_pace']} /mi"))
    if "longest_run" in summary:
        stat_items.append(("Longest Run", f"{summary['longest_run']} mi"))

    # Best 1RMs for the year (from weight training data)
    year = summary["year"]
    lifts_df = df[(df["date"].dt.year == year) & (df["type"] == "Weight Training")]
    for col, label in [
        ("bench_weight", "Best Bench"),
        ("squat_weight", "Best Squat"),
        ("deadlift_weight", "Best Deadlift"),
        ("ohp_weight", "Best OHP"),
    ]:
        if col in lifts_df.columns:
            val = lifts_df[col].max()
            if pd.notna(val) and val > 0:
                stat_items.append((label, f"{int(val)} lb"))

    stat_cells = []
    for label, val in stat_items:
        stat_cells.append(html.Div([
            html.Div(label, style={
                "fontSize": "10px", "fontWeight": "500",
                "textTransform": "uppercase", "letterSpacing": "0.1em",
                "color": TEXT_MUTED, "marginBottom": "4px",
            }),
            html.Div(val, style={
                "fontFamily": FONT_MONO,
                "fontSize": "18px", "fontWeight": "600",
                "color": TEXT_PRIMARY,
            }),
        ], style={"padding": "12px 16px"}))

    return page_section(f"{year} IN REVIEW", [
        html.Div(stat_cells, style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fill, minmax(140px, 1fr))",
            "gap": "8px", "marginBottom": "20px",
            "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
            "padding": "8px",
        }),
        charts.year_monthly_chart(summary, chart_id="year-monthly"),
    ], alt_bg=True)


def layout(**_kwargs):
    df = data.get_df()
    runs = data.get_runs()
    lifts = data.get_lifts()
    profile = data.get_profile()

    # Totals
    total_activities = len(df)
    total_miles = df["distance_mi"].sum()
    total_runs = len(runs)
    total_lifts = len(lifts)
    start_date = df["date"].min()

    # Running stats
    avg_pace = format_pace(runs["pace_min_per_mi"].mean()) if not runs.empty else "--"

    # Current fatigue
    fatigue_now = "Unknown"
    if "fatigue_level" in df.columns:
        recent_fatigue = df[df["fatigue_level"].notna()].tail(1)
        if not recent_fatigue.empty:
            fatigue_now = recent_fatigue.iloc[0]["fatigue_level"]

    # VDOT — prefer best-effort VDOT (true VO2max), fall back to CS-derived
    try:
        vdot = compute_athlete_vdot(df)
        if not vdot or vdot <= 0:
            best_efforts_df = data.get_best_efforts()
            cs = fit_critical_speed(best_efforts_df)
            vdot = cs_to_vdot(cs["cs_m_per_s"]) if cs["cs_m_per_s"] > 0 else 0
    except Exception:
        vdot = 0

    # Lifting maxes
    bench_1rm = END_PRS.get("bench_1rm", "?")
    squat_1rm = END_PRS.get("squat_1rm", "?")
    dl_1rm = END_PRS.get("deadlift_1rm", "?")

    # Fatigue-driven statement
    statements = {
        "Fresh": "Rested and dangerous.",
        "Normal": "Consistent beats heroic. Keep stacking days.",
        "Fatigued": "The body is willing. The legs disagree.",
        "Heavy Load": "Respect the load. Recovery is training too.",
        "Unknown": "The data speaks. You just have to listen.",
    }
    form_text = statements.get(fatigue_now, statements["Unknown"])

    return html.Div([
        # Hero
        hero_section(
            label="MERON \u2014 OVERVIEW",
            headline="Your body is a machine. Here's the telemetry.",
            subtext=(
                f"{total_activities} activities. {total_miles:,.0f} miles. "
                f"Since {start_date:%B %Y}."
            ),
            cta_buttons=[
                # Logged-in CTAs \u2014 00-auth-nav.js swaps these for a "Log in"
                # prompt when <body data-auth="anon">.
                dcc.Link("Start Running \u2192", href="/running",
                         className="btn-accent auth-only"),
                dcc.Link("View Plan", href="/plan",
                         className="btn-ghost auth-only"),
                # Anon prompt \u2014 visible only when not logged in.
                html.A("Log in to view \u2192", href="/login",
                       id="overview-cta-login",
                       className="btn-accent anon-only"),
            ],
        ),

        # What We Track — MERON "What We Build" pattern
        page_section("WHAT WE TRACK", [
            feature_grid([
                numbered_card(
                    1, "Running",
                    f"{total_runs} runs at {avg_pace} avg pace. "
                    "Pace trends, heart rate analysis, and estimated race fitness.",
                    link_text="Learn more", link_href="/running",
                ),
                numbered_card(
                    2, "Strength",
                    f"{total_lifts} sessions logged. "
                    f"Bench {bench_1rm} / Squat {squat_1rm} / Deadlift {dl_1rm}.",
                    link_text="Learn more", link_href="/lifting",
                ),
                numbered_card(
                    3, "Racing",
                    f"VDOT {vdot:.1f}. Rolling 8-week build cycle: peak fitness "
                    "around the perpetual time-trial week.",
                    link_text="Learn more", link_href="/running",
                ),
            ]),
        ]),

        # Statement — current form
        statement_section("CURRENT FORM", form_text),

        # Training Load chart
        page_section("TRAINING LOAD", [
            html.P("Acute vs chronic training load. Green means go.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                          "marginBottom": "20px"}),
            charts.fatigue_chart(df, chart_id="fatigue"),
        ], alt_bg=True),

        # Trends (90d vs 365d)
        _trends_section(df),

        # Personal Records
        _prs_section(df),

        # Year in Review
        _year_section(df),

        # Activity calendar with month navigation
        page_section("ACTIVITY", [
            dcc.Store(id="cal-offset", data=0),
            html.Div(id="cal-container", children=_activity_calendar(df, months=3, offset=0)),
            html.Div([
                html.Button("\u2039", id="cal-prev", n_clicks=0, style={
                    "background": "none", "border": "none",
                    "color": TEXT_MUTED, "padding": "0",
                    "cursor": "pointer", "fontSize": "20px",
                    "lineHeight": "1", "width": "28px", "height": "28px",
                    "display": "flex", "alignItems": "center", "justifyContent": "center",
                    "borderRadius": "50%", "transition": "color 0.15s",
                }),
                html.Button("\u203a", id="cal-next", n_clicks=0, style={
                    "background": "none", "border": "none",
                    "color": TEXT_MUTED, "padding": "0",
                    "cursor": "pointer", "fontSize": "20px",
                    "lineHeight": "1", "width": "28px", "height": "28px",
                    "display": "flex", "alignItems": "center", "justifyContent": "center",
                    "borderRadius": "50%", "transition": "color 0.15s",
                }),
            ], style={"display": "flex", "gap": "4px", "justifyContent": "flex-end",
                      "marginTop": "12px"}),
        ]),

        # CTA \u2014 wrapped so 00-auth-nav.js can swap the link target for anons.
        # The .auth-only / .anon-only versions toggle by body[data-auth] class.
        html.Div(cta_section(
            "Ready to dig deeper?",
            "Your running, lifting, and race data \u2014 broken down.",
            "Explore Running \u2192", "/running",
        ), className="auth-only"),
        html.Div(cta_section(
            "Ready to dig deeper?",
            "Sign in to see runs, lifts, plan, and race fitness.",
            "Log in \u2192", "/login",
        ), className="anon-only"),

        # Footer
        footer(),
    ])


charts.register_chart_callback("fatigue")


# Calendar month navigation
@callback(
    Output("cal-container", "children"),
    Output("cal-offset", "data"),
    Input("cal-prev", "n_clicks"),
    Input("cal-next", "n_clicks"),
    State("cal-offset", "data"),
    prevent_initial_call=True,
)
def navigate_calendar(prev_clicks, next_clicks, current_offset):
    from dash import ctx
    triggered = ctx.triggered_id
    if triggered == "cal-prev":
        new_offset = current_offset + 1
    elif triggered == "cal-next":
        new_offset = max(0, current_offset - 1)
    else:
        new_offset = current_offset
    df = data.get_df()
    return _activity_calendar(df, months=3, offset=new_offset), new_offset
