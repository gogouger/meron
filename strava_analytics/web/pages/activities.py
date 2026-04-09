"""Activities — unified chronological feed of all activity types."""

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, clientside_callback, Output, Input, State, MATCH, no_update
import pandas as pd

from strava_analytics.web import data
from strava_analytics.web.components.cards import stat_cell, duration_str, activity_type_badge
from strava_analytics.web.components.routes import build_route_charts
from strava_analytics.web.components.layout import (
    hero_section, page_section, cta_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, ACCENT_RED,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BG_CARD, BORDER, ACTIVITY_TYPE_COLORS, LIFT_COLORS,
    HR_ZONE_COLORS, HR_ZONE_LABELS, FONT_MONO,
)
from strava_analytics.metrics import format_pace


# ── SVG lift icons (minimal line-art) ────────────────────────────────

_LIFT_ICONS = {
    "bench": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="24" x2="42" y2="24"/><rect x="10" y="18" width="4" height="12" rx="1"/><rect x="34" y="18" width="4" height="12" rx="1"/><circle cx="6" cy="24" r="3"/><circle cx="42" cy="24" r="3"/></svg>',
    "squat": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="8" y1="14" x2="40" y2="14"/><rect x="12" y="8" width="3" height="12" rx="1"/><rect x="33" y="8" width="3" height="12" rx="1"/><circle cx="8" cy="14" r="2.5"/><circle cx="40" cy="14" r="2.5"/><path d="M18 20 L18 30 Q18 36 24 38 Q30 36 30 30 L30 20"/></svg>',
    "deadlift": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="34" x2="42" y2="34"/><rect x="10" y="28" width="4" height="12" rx="1"/><rect x="34" y="28" width="4" height="12" rx="1"/><circle cx="6" cy="34" r="3"/><circle cx="42" cy="34" r="3"/><path d="M20 34 L20 18 M28 34 L28 18"/><line x1="18" y1="18" x2="30" y2="18"/></svg>',
    "ohp": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="8" y1="10" x2="40" y2="10"/><rect x="12" y="4" width="3" height="12" rx="1"/><rect x="33" y="4" width="3" height="12" rx="1"/><circle cx="8" cy="10" r="2.5"/><circle cx="40" cy="10" r="2.5"/><path d="M20 16 L20 34 M28 16 L28 34"/></svg>',
}


def _lift_icon(lift_name: str, size: int = 28) -> html.Div:
    """Return an inline SVG icon for a lift type."""
    key = lift_name.lower().split()[0] if lift_name else ""
    # Map common exercise names to icon keys
    for k in _LIFT_ICONS:
        if k in key:
            svg = _LIFT_ICONS[k]
            break
    else:
        svg = _LIFT_ICONS.get("bench", "")  # fallback

    from dash import html as _html
    return _html.Div(
        dangerously_allow_html=True,
        children="",
        style={
            "width": f"{size}px", "height": f"{size}px",
            "color": TEXT_MUTED, "flexShrink": "0",
        },
        **{"data-svg-icon": svg},
    )


def _inline_hr_zone_bar(row) -> html.Div | None:
    """Inline horizontal stacked bar showing HR zone distribution for one activity."""
    zone_secs = []
    has_data = False
    for z in range(1, 6):
        val = row.get(f"zone_{z}_s", 0)
        if pd.notna(val) and val > 0:
            has_data = True
        zone_secs.append(float(val) if pd.notna(val) else 0)

    if not has_data:
        return None

    total = sum(zone_secs)
    if total <= 0:
        return None

    segments = []
    for z in range(5):
        pct = zone_secs[z] / total * 100
        if pct < 0.5:
            continue
        color = HR_ZONE_COLORS.get(z + 1, TEXT_MUTED)
        mins = int(zone_secs[z] / 60)
        segments.append(html.Div(
            title=f"{HR_ZONE_LABELS[z]}: {mins}m",
            style={
                "width": f"{pct}%", "height": "100%",
                "backgroundColor": color, "display": "inline-block",
            },
        ))

    return html.Div([
        html.Div("HR ZONES", style={
            "fontSize": "10px", "fontWeight": "600",
            "textTransform": "uppercase", "letterSpacing": "0.1em",
            "color": TEXT_MUTED, "marginBottom": "4px",
        }),
        html.Div(segments, style={
            "height": "8px", "display": "flex",
            "borderRadius": "4px", "overflow": "hidden",
            "backgroundColor": BORDER,
        }),
    ], style={"marginTop": "12px", "paddingTop": "12px",
              "borderTop": f"1px solid {BORDER}"})

dash.register_page(__name__, path="/activities", name="Activities")

_PAGE_SIZE = 50


# ── Card builders ─────────────────────────────────────────────────────

def _activity_card(row, idx: int, default_open: bool = False) -> html.Details:
    """Build a single expandable activity card. Dispatches by type."""
    act_type = row.get("type", "")
    color = ACTIVITY_TYPE_COLORS.get(act_type, TEXT_MUTED)
    date_str = row["date"].strftime("%b %d, %Y")
    day_str = row["date"].strftime("%A")
    name = row.get("name", act_type or "Activity")
    date_id = row["date"].strftime("%Y-%m-%d")

    badge = activity_type_badge(act_type, color)

    # Primary stats — type-dependent
    primary = []
    detail_content = []

    dist = row.get("distance_mi", 0)
    dur = row.get("moving_time_s", 0)

    if act_type in ("Run", "Walk", "Hike", "Ride"):
        if dist and not pd.isna(dist) and dist > 0:
            primary.append(stat_cell("Distance", f"{dist:.1f} mi"))
        pace = row.get("pace_min_per_mi", None)
        if pace and not pd.isna(pace) and pace > 0:
            primary.append(stat_cell("Pace", f"{format_pace(pace)} /mi"))
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))
        hr = row.get("avg_hr", 0)
        if hr and not pd.isna(hr):
            primary.append(stat_cell("Avg HR", f"{hr:.0f} bpm"))
        rel_effort = row.get("relative_effort", None)
        if rel_effort and not pd.isna(rel_effort):
            primary.append(stat_cell("Effort", f"{rel_effort:.0f}"))
        elev = row.get("elevation_gain_ft", 0) or 0
        if elev > 0:
            primary.append(stat_cell("Elevation", f"\u2191{elev:.0f} ft"))

        # Detail: secondary stats
        secondary = []
        max_hr = row.get("max_hr", 0)
        if max_hr and not pd.isna(max_hr):
            secondary.append(stat_cell("Max HR", f"{max_hr:.0f} bpm"))
        cals = row.get("calories", 0)
        if cals and not pd.isna(cals) and cals > 0:
            secondary.append(stat_cell("Calories", f"{cals:.0f}"))
        temp = row.get("weather_temp_f", None)
        if temp is not None and not pd.isna(temp):
            secondary.append(stat_cell("Temp", f"{temp:.0f}\u00b0F"))
        weather = row.get("weather_condition", "")
        if weather and isinstance(weather, str) and weather.strip():
            secondary.append(stat_cell("Weather", weather[:20]))

        if secondary:
            detail_content.append(html.Div(secondary, style={
                "display": "flex", "gap": "24px", "flexWrap": "wrap",
                "marginTop": "12px", "paddingTop": "12px",
                "borderTop": f"1px solid {BORDER}",
            }))

        desc = row.get("description", "")
        if desc and isinstance(desc, str) and desc.strip():
            detail_content.append(html.P(desc.strip(), style={
                "color": TEXT_SECONDARY, "fontSize": "13px",
                "marginTop": "12px", "fontStyle": "italic",
            }))

        # Inline HR zone bar for this run
        zone_bar = _inline_hr_zone_bar(row)
        if zone_bar:
            detail_content.append(zone_bar)

        # Lazy route loading
        filename = row.get("filename", "")
        if filename:
            route_key = f"{date_id}-{idx}"
            detail_content.append(html.Button(
                "", id={"type": "act-route-btn", "index": route_key},
                n_clicks=0, style={"display": "none"},
            ))
            detail_content.append(
                dcc.Loading(
                    html.Div(id={"type": "act-route-container", "index": route_key}),
                    type="dot",
                )
            )

    elif act_type == "Weight Training":
        # Primary stats: duration, HR, calories
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))
        hr = row.get("avg_hr", 0)
        if hr and not pd.isna(hr):
            primary.append(stat_cell("Avg HR", f"{hr:.0f} bpm"))
        max_hr_val = row.get("max_hr", 0)
        if max_hr_val and not pd.isna(max_hr_val):
            primary.append(stat_cell("Max HR", f"{max_hr_val:.0f} bpm"))
        cals = row.get("calories", 0)
        if cals and not pd.isna(cals) and cals > 0:
            primary.append(stat_cell("Calories", f"{cals:.0f}"))
        rel_effort = row.get("relative_effort", None)
        if rel_effort and not pd.isna(rel_effort):
            primary.append(stat_cell("Effort", f"{rel_effort:.0f}"))

        # Detail: lift cards grid with SVG icons
        _lift_grid_items = []
        for label, wt_col, sets_col, reps_col, icon_key in [
            ("Bench Press", "bench_weight", "bench_sets", "bench_reps", "bench"),
            ("Squat", "squat_weight", "squat_sets", "squat_reps", "squat"),
            ("Deadlift", "deadlift_weight", "deadlift_sets", "deadlift_reps", "deadlift"),
            ("OHP", "ohp_weight", "ohp_sets", "ohp_reps", "ohp"),
        ]:
            wt = row.get(wt_col, None)
            if wt is None or pd.isna(wt):
                continue
            sets = row.get(sets_col, None)
            reps = row.get(reps_col, None)
            scheme = ""
            if sets and not pd.isna(sets) and reps and not pd.isna(reps):
                scheme = f"{int(sets)}x{int(reps)}"

            svg = _LIFT_ICONS.get(icon_key, "")
            icon_div = html.Div(
                style={
                    "width": "32px", "height": "32px",
                    "color": LIFT_COLORS.get(icon_key, TEXT_MUTED),
                    "flexShrink": "0",
                },
                **{"data-svg-icon": svg},
            ) if svg else html.Div()

            _lift_grid_items.append(html.Div([
                icon_div,
                html.Div([
                    html.Div(label, style={
                        "fontSize": "11px", "fontWeight": "600",
                        "color": TEXT_SECONDARY,
                    }),
                    html.Div(f"{wt:.0f} lbs", style={
                        "fontFamily": FONT_MONO,
                        "fontSize": "16px", "fontWeight": "700",
                        "color": TEXT_PRIMARY,
                    }),
                    html.Div(scheme, style={
                        "fontSize": "11px", "color": TEXT_MUTED,
                    }) if scheme else None,
                ]),
            ], style={
                "display": "flex", "gap": "10px", "alignItems": "center",
                "padding": "10px 12px",
                "backgroundColor": "var(--surface, #f5f5f4)",
                "border": f"1px solid {BORDER}",
                "borderRadius": "4px",
            }))

        if _lift_grid_items:
            primary.append(html.Div(_lift_grid_items, style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fill, minmax(160px, 1fr))",
                "gap": "8px", "marginTop": "12px",
            }))

        # Additional exercises (non-primary)
        exercises_str = row.get("lift_exercises", "")
        if exercises_str and not pd.isna(exercises_str):
            exercises = [e.strip() for e in str(exercises_str).split(";") if e.strip()]
            # Filter out primary lifts already shown
            primary_names = {"bench", "squat", "deadlift", "ohp", "overhead"}
            extras = [e for e in exercises
                      if not any(p in e.lower() for p in primary_names)]
            if extras:
                detail_content.append(html.Div([
                    html.Div("ACCESSORIES", style={
                        "fontSize": "10px", "fontWeight": "600",
                        "textTransform": "uppercase", "letterSpacing": "0.1em",
                        "color": TEXT_MUTED, "marginBottom": "4px",
                    }),
                    html.Div(
                        " · ".join(extras),
                        style={"fontSize": "12px", "color": TEXT_SECONDARY},
                    ),
                ], style={"marginTop": "8px"}))

        # Pullup stats
        pullup_sets = row.get("pullup_sets", None)
        pullup_reps = row.get("pullup_reps", None)
        parts = []
        if pullup_sets and not pd.isna(pullup_sets):
            parts.append(f"{int(pullup_sets)} sets")
        if pullup_reps and not pd.isna(pullup_reps):
            parts.append(f"{int(pullup_reps)} reps")
        if parts:
            detail_content.append(stat_cell("Pull-ups", " / ".join(parts)))

        # HR zone bar for lifts too
        zone_bar = _inline_hr_zone_bar(row)
        if zone_bar:
            detail_content.append(zone_bar)

    else:
        # Swim, Yoga, Other
        if dur and not pd.isna(dur) and dur > 0:
            primary.append(stat_cell("Duration", duration_str(dur)))
        if dist and not pd.isna(dist) and dist > 0:
            primary.append(stat_cell("Distance", f"{dist:.1f} mi"))
        cals = row.get("calories", 0)
        if cals and not pd.isna(cals) and cals > 0:
            primary.append(stat_cell("Calories", f"{cals:.0f}"))

    # Run type sub-badge for runs
    run_type = row.get("run_type", "")
    run_badge = ""
    if act_type == "Run" and run_type:
        from strava_analytics.web.theme import RUN_TYPE_COLORS
        rt_color = RUN_TYPE_COLORS.get(run_type, TEXT_MUTED)
        run_badge = html.Span(
            run_type,
            style={
                "backgroundColor": rt_color, "color": "white",
                "fontSize": "9px", "fontWeight": "600",
                "textTransform": "uppercase", "letterSpacing": "0.05em",
                "padding": "1px 6px", "marginLeft": "6px",
                "display": "inline-block",
            },
        )

    return html.Details([
        html.Summary([
            html.Div([
                html.Div([
                    html.Span(date_str, style={
                        "fontWeight": "600", "fontSize": "14px", "color": TEXT_PRIMARY,
                    }),
                    html.Span(f" {day_str}", style={
                        "color": TEXT_MUTED, "fontSize": "13px",
                    }),
                    badge,
                    run_badge if run_badge else None,
                ]),
                html.Div(name, style={
                    "fontSize": "13px", "color": TEXT_SECONDARY, "marginTop": "2px",
                }),
            ], style={"marginBottom": "12px"}),
            html.Div(primary, style={
                "display": "flex", "gap": "24px", "flexWrap": "wrap",
            }) if primary else None,
        ], style={"listStyle": "none", "cursor": "pointer"}),
        html.Div(detail_content, style={
            "padding": "12px 0 0 0",
        }) if detail_content else None,
    ], id=f"activity-card-{date_id}-{idx}",
       open=default_open,
       style={
        "backgroundColor": BG_CARD,
        "border": f"1px solid {BORDER}",
        "padding": "20px 24px", "marginBottom": "8px",
        "borderLeft": f"3px solid {color}",
    })


# ── Layout ────────────────────────────────────────────────────────────

def layout(**_kwargs):
    df = data.get_df()
    if df.empty:
        return html.P("No activity data available.")

    sorted_df = df.sort_values("date", ascending=False)
    total = len(sorted_df)
    types = sorted(df["type"].dropna().unique())

    # Build cards + filename mapping
    cards = []
    filenames_dict = {}
    for idx, (_, row) in enumerate(sorted_df.iterrows()):
        cards.append(_activity_card(row, idx, default_open=False))
        fn = row.get("filename", "")
        if fn:
            date_id = row["date"].strftime("%Y-%m-%d")
            filenames_dict[f"{date_id}-{idx}"] = fn

    visible = cards[:_PAGE_SIZE]
    hidden = cards[_PAGE_SIZE:]

    return html.Div([
        hero_section(
            label="ACTIVITIES",
            headline="Everything. One feed.",
            subtext=f"{total} activities across {len(types)} types.",
        ),

        # Filters
        page_section("FILTER", [
            dbc.Row([
                dbc.Col([
                    html.Label("Activity Type",
                               style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
                    dcc.Dropdown(
                        id="activity-type-filter",
                        options=[{"label": t, "value": t} for t in types],
                        multi=True,
                        placeholder="All types",
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Date Range",
                               style={"fontSize": "0.8rem", "color": TEXT_SECONDARY}),
                    dcc.DatePickerRange(
                        id="activity-date-range",
                        start_date=df["date"].min(),
                        end_date=df["date"].max(),
                        style={"fontSize": "0.85rem"},
                    ),
                ], md=6),
            ]),
        ], alt_bg=True),

        # Activity feed
        page_section("ALL ACTIVITIES", [
            html.Div(visible, id="visible-activity-cards"),
            html.Div(hidden, id="hidden-activity-cards",
                      style={"display": "none"}) if hidden else html.Div(
                          id="hidden-activity-cards", style={"display": "none"}),
            html.Button(
                f"Show All ({len(hidden)} more)",
                id="show-all-activities-btn",
                n_clicks=0,
                style={
                    "display": "block" if hidden else "none",
                    "margin": "20px auto",
                    "padding": "10px 24px",
                    "fontSize": "14px", "fontWeight": "600",
                    "color": TEXT_PRIMARY, "backgroundColor": BG_CARD,
                    "border": f"1px solid {BORDER}", "cursor": "pointer",
                },
            ),
        ]),

        # Filename store for lazy route loading
        dcc.Store(id="act-filenames-store", data=filenames_dict),

        cta_section(
            "Back to the numbers?",
            "Charts, predictions, and training plans.",
            "Running \u2192", "/running",
        ),
        footer(),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────

# Show all activities
clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        return [{"display": "block"}, {"display": "none"}];
    }
    """,
    Output("hidden-activity-cards", "style"),
    Output("show-all-activities-btn", "style"),
    Input("show-all-activities-btn", "n_clicks"),
    prevent_initial_call=True,
)


# Lazy route loading
@callback(
    Output({"type": "act-route-container", "index": MATCH}, "children"),
    Input({"type": "act-route-btn", "index": MATCH}, "n_clicks"),
    State({"type": "act-route-btn", "index": MATCH}, "id"),
    State("act-filenames-store", "data"),
    prevent_initial_call=True,
)
def load_activity_route(n_clicks, btn_id, filenames):
    if not n_clicks:
        return no_update
    key = btn_id["index"]
    filename = filenames.get(key, "")
    if not filename:
        return html.P("No GPS data for this activity.", style={"color": TEXT_MUTED})
    return build_route_charts(filename, df=data.get_df())
