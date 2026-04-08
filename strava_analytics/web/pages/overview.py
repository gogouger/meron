"""Overview — hybrid landing page modeled on ozniai.com homepage."""

import calendar
from datetime import date, timedelta

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc
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
    ACTIVITY_TYPE_COLORS,
)
from strava_analytics.metrics import format_pace
from strava_analytics.vo2max import compute_athlete_vdot
from strava_analytics.lifting_program import END_PRS

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


def _week_flame(count: int) -> html.Div:
    """Line-art flame icon sized & coloured by weekly activity count.

    Uses an inline CSS clip-path flame shape on a div — no emoji, no SVG tags.
    1-2 = small teal, 3-4 = medium orange, 5+ = large red. Stroke-style outline.
    """
    t = min(count, 7) / 7  # 0..1
    h = int(14 + t * 10)   # 14..24px
    w = int(10 + t * 6)    # 10..16px

    if count <= 2:
        color = ACCENT_SLATE
    elif count <= 4:
        color = ACCENT_AMBER
    else:
        color = ACCENT

    # Flame shape via clip-path — a stylised teardrop/flame silhouette
    flame_clip = (
        "polygon(50% 0%, 65% 20%, 80% 45%, 85% 65%, "
        "80% 80%, 65% 95%, 50% 100%, 35% 95%, 20% 80%, "
        "15% 65%, 20% 45%, 35% 20%)"
    )

    return html.Div([
        # Outer flame (border effect via slightly larger shape)
        html.Div(
            # Inner cutout (transparent center = outline effect)
            html.Div(style={
                "width": f"{w - 3}px", "height": f"{h - 3}px",
                "clipPath": flame_clip,
                "background": "var(--bg)",
                "margin": "auto",
            }),
            style={
                "width": f"{w}px", "height": f"{h}px",
                "clipPath": flame_clip,
                "background": color,
                "display": "flex", "alignItems": "center",
                "justifyContent": "center",
            },
        ),
        html.Span(str(count), style={
            "fontSize": "9px", "fontWeight": "700",
            "color": color,
            "fontFamily": "'IBM Plex Mono', monospace",
            "lineHeight": "1", "marginTop": "1px",
        }),
    ], style={
        "display": "flex", "flexDirection": "column",
        "alignItems": "center", "justifyContent": "center",
        "gap": "1px",
        "width": "40px", "height": "32px",
        "margin": "0 auto",
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
            meta = _week_flame(week_activity_count)
        else:
            meta = html.Div(style={"width": "40px", "height": "28px"})
        cells.append(meta)

        week_rows.append(html.Div(cells, style={**_WEEK_GRID, "marginBottom": "3px"}))

    return html.Div([month_label, dow_header, *week_rows], style={
        "flex": "1", "minWidth": "280px", "maxWidth": "320px",
    })


def _activity_calendar(df: pd.DataFrame, months: int = 3) -> html.Div:
    """Strava-style HTML/CSS activity calendar — outlined circles with accent dots."""
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

    # Collect month starts (most recent N)
    month_starts = []
    d = date(latest.year, latest.month, 1)
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

    # VDOT
    try:
        vdot = compute_athlete_vdot(df)
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
            label="STRAVA ANALYTICS",
            headline="Your body is a machine. Here's the telemetry.",
            subtext=(
                f"{total_activities} activities. {total_miles:,.0f} miles. "
                f"Since {start_date:%B %Y}."
            ),
            cta_buttons=[
                dcc.Link("Start Running \u2192", href="/running",
                         className="btn-accent"),
                dcc.Link("View Plan", href="/plan",
                         className="btn-ghost"),
            ],
        ),

        # What We Track — ozniai.com "What We Build" pattern
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
                    f"VDOT {vdot:.1f}. Next up: Boulder Bolder 10K (May 25) "
                    "and Spartan Beast (May 31).",
                    link_text="Learn more", link_href="/races",
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

        # Activity calendar
        page_section("ACTIVITY", [
            _activity_calendar(df),
        ]),

        # CTA
        cta_section(
            "Ready to dig deeper?",
            "Your running, lifting, and race data \u2014 broken down.",
            "Explore Running \u2192", "/running",
        ),

        # Footer
        footer(),
    ])


charts.register_chart_callback("fatigue")
