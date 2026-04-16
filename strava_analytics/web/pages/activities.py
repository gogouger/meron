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


# (The mini-map helpers live in components/routes.py so pages/activities.py
# can be imported safely during page-render callbacks without re-invoking
# dash.register_page inside a callback context.)
from strava_analytics.web.components.routes import _mini_map  # noqa: E402,F401


_hr_chart_counter = 0

dash.register_page(__name__, path="/activities", name="Activities")

_PAGE_SIZE = 15


# ── Card builders ─────────────────────────────────────────────────────

def _activity_card(row, idx: int, default_open: bool = False) -> html.Details:
    """Build a single expandable activity card using the shared builder."""
    from strava_analytics.web.components.cards import activity_card_body

    parts = activity_card_body(row, route_mode="lazy", card_id_prefix="act", idx=idx)

    return html.Details([
        html.Summary([
            parts["header"],
            html.Div(parts["primary"], style={
                "display": "flex", "gap": "24px", "flexWrap": "wrap",
            }) if parts["primary"] else None,
            parts["extra"],
        ], style={"listStyle": "none", "cursor": "pointer"}),
        html.Div(parts["detail"], style={
            "padding": "12px 0 0 0",
        }) if parts["detail"] else None,
    ], id=f"activity-card-{parts['date_id']}-{idx}",
       open=default_open,
       style={
        "backgroundColor": BG_CARD,
        "border": f"1px solid {BORDER}",
        "padding": "20px 24px", "marginBottom": "8px",
        "borderLeft": f"3px solid {parts['color']}",
    })


# ── Layout ────────────────────────────────────────────────────────────

def layout(**_kwargs):
    df = data.get_df()
    if df.empty:
        return html.P("No activity data available.")

    sorted_df = df.sort_values("date", ascending=False)
    total = len(sorted_df)
    types = sorted(df["type"].dropna().unique())

    # Build only the first N visible cards server-side. The rest are
    # built lazily in expand_all_activities() when the user clicks
    # "Show All" — keeps initial page load fast on large activity feeds.
    visible_rows = sorted_df.head(_PAGE_SIZE)
    cards = []
    filenames_dict = {}
    for idx, (_, row) in enumerate(visible_rows.iterrows()):
        cards.append(_activity_card(row, idx, default_open=False))
        fn = row.get("filename", "")
        if fn:
            date_id = row["date"].strftime("%Y-%m-%d")
            filenames_dict[f"{date_id}-{idx}"] = fn

    # Pre-populate the filename mapping for ALL activities so the lazy
    # route-loader can resolve filenames for cards added later.
    for idx, (_, row) in enumerate(sorted_df.iloc[_PAGE_SIZE:].iterrows(),
                                    start=_PAGE_SIZE):
        fn = row.get("filename", "")
        if fn:
            date_id = row["date"].strftime("%Y-%m-%d")
            filenames_dict[f"{date_id}-{idx}"] = fn

    hidden_count = max(0, total - _PAGE_SIZE)

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

        # Activity feed — visible cards up front, hidden cards injected lazily
        page_section("ALL ACTIVITIES", [
            html.Div(cards, id="visible-activity-cards"),
            # Placeholder filled in by expand_all_activities callback,
            # wrapped in MERON pulse spinner so the big render has feedback.
            dcc.Loading(
                html.Div(id="hidden-activity-cards"),
                type="default",
                className="meron-loading",
                color=ACCENT,
            ),
            html.Button(
                f"Show All ({hidden_count} more)",
                id="show-all-activities-btn",
                n_clicks=0,
                className="btn-ghost",
                style={
                    "display": "block" if hidden_count else "none",
                    "margin": "20px auto",
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

# Expand the full activity feed lazily — builds the remaining cards
# only when the user clicks "Show All", keeping initial render fast.
@callback(
    Output("hidden-activity-cards", "children"),
    Output("show-all-activities-btn", "style"),
    Input("show-all-activities-btn", "n_clicks"),
    prevent_initial_call=True,
)
def expand_all_activities(n_clicks):
    if not n_clicks:
        return no_update, no_update
    df = data.get_df()
    sorted_df = df.sort_values("date", ascending=False)
    hidden_rows = sorted_df.iloc[_PAGE_SIZE:]
    cards = []
    for idx, (_, row) in enumerate(hidden_rows.iterrows(), start=_PAGE_SIZE):
        cards.append(_activity_card(row, idx, default_open=False))
    return cards, {"display": "none"}


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
