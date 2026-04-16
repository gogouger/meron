"""Activities — unified chronological feed of all activity types."""

from datetime import datetime, timezone

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, clientside_callback, Output, Input, State, MATCH, no_update
import pandas as pd

from strava_analytics.db import session_scope
from strava_analytics.db.repository import (
    create_manual_activity,
    patch_activity,
    soft_delete_activity,
)
from strava_analytics.services.enrichment_service import invalidate_cache
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

    # Row actions (edit/delete) anchored to this activity's DB id.
    db_id = int(row["_id"]) if "_id" in row and pd.notna(row.get("_id")) else None
    is_manual = row.get("_source") == "manual"
    actions = None
    if db_id is not None:
        manual_pill = html.Span("manual", style={
            "fontSize": "10px", "padding": "2px 8px",
            "background": ACCENT_AMBER, "color": "#000",
            "marginLeft": "8px", "fontWeight": "600",
            "letterSpacing": "0.08em", "textTransform": "uppercase",
        }) if is_manual else None

        actions = html.Div([
            manual_pill,
            html.Button("Edit", id={"type": "act-edit-btn", "index": db_id},
                        n_clicks=0, className="btn-ghost",
                        style={"padding": "4px 10px", "fontSize": "11px",
                               "marginLeft": "8px"}),
            html.Button("Delete", id={"type": "act-delete-btn", "index": db_id},
                        n_clicks=0, className="btn-ghost",
                        style={"padding": "4px 10px", "fontSize": "11px",
                               "marginLeft": "6px", "color": ACCENT_RED}),
        ], style={
            "display": "flex", "alignItems": "center",
            "justifyContent": "flex-end", "marginTop": "8px",
        })

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
        actions,
    ], id=f"activity-card-{parts['date_id']}-{idx}",
       open=default_open,
       style={
        "backgroundColor": BG_CARD,
        "border": f"1px solid {BORDER}",
        "padding": "20px 24px", "marginBottom": "8px",
        "borderLeft": f"3px solid {parts['color']}",
    })


# ── Add / Edit modal ──────────────────────────────────────────────────

_ACTIVITY_TYPE_OPTIONS = [
    "Run", "Ride", "Walk", "Hike", "Weight Training",
    "Swim", "Yoga", "Workout", "Rowing", "Other",
]


def _modal(title_id: str = "activity-modal-title") -> dbc.Modal:
    """Reusable Add/Edit modal."""
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Add Activity", id=title_id)),
        dbc.ModalBody([
            # Hidden id input — empty for Add, set to id for Edit
            dcc.Store(id="activity-form-id", data=None),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Type"),
                    dcc.Dropdown(
                        id="activity-form-type",
                        options=[{"label": t, "value": t} for t in _ACTIVITY_TYPE_OPTIONS],
                        value="Run",
                        clearable=False,
                    ),
                ], md=6),
                dbc.Col([
                    dbc.Label("Date & time"),
                    dbc.Input(id="activity-form-datetime", type="datetime-local"),
                ], md=6),
            ], class_name="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Duration (min)"),
                    dbc.Input(id="activity-form-duration", type="number", step="0.1"),
                ], md=4),
                dbc.Col([
                    dbc.Label("Distance (mi)"),
                    dbc.Input(id="activity-form-distance", type="number", step="0.01"),
                ], md=4),
                dbc.Col([
                    dbc.Label("Elev gain (ft)"),
                    dbc.Input(id="activity-form-elev", type="number", step="1"),
                ], md=4),
            ], class_name="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Avg HR"),
                    dbc.Input(id="activity-form-avghr", type="number"),
                ], md=4),
                dbc.Col([
                    dbc.Label("Max HR"),
                    dbc.Input(id="activity-form-maxhr", type="number"),
                ], md=4),
                dbc.Col([
                    dbc.Label("Calories"),
                    dbc.Input(id="activity-form-calories", type="number"),
                ], md=4),
            ], class_name="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Name"),
                    dbc.Input(id="activity-form-name", type="text"),
                ], md=12),
            ], class_name="mb-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Description"),
                    dbc.Textarea(id="activity-form-desc"),
                ], md=12),
            ]),
            html.Div(id="activity-form-error", style={
                "color": ACCENT_RED, "fontSize": "13px", "marginTop": "10px",
            }),
        ]),
        dbc.ModalFooter([
            dbc.Button("Cancel", id="activity-form-cancel", className="btn-ghost"),
            dbc.Button("Save", id="activity-form-save", className="btn-accent",
                       color=None),
        ]),
    ], id="activity-form-modal", is_open=False, size="lg")


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

        # Add activity CTA
        html.Div([
            html.Button("+ Add activity",
                        id="activity-add-btn",
                        n_clicks=0,
                        className="btn-accent",
                        style={"padding": "10px 20px", "fontSize": "13px"}),
        ], style={
            "display": "flex", "justifyContent": "flex-end",
            "padding": "0 24px", "marginTop": "12px",
        }),

        _modal(),
        dcc.ConfirmDialog(
            id="activity-delete-confirm",
            message="Delete this activity? This can be reverted in the database.",
        ),
        dcc.Store(id="activity-delete-target", data=None),
        dcc.Store(id="activity-ops-counter", data=0),

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


# ── CRUD callbacks ───────────────────────────────────────────────────

def _default_modal_values():
    return {
        "type": "Run",
        "datetime": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "duration": None,
        "distance": None,
        "elev": None,
        "avghr": None,
        "maxhr": None,
        "calories": None,
        "name": "",
        "desc": "",
        "title": "Add Activity",
        "open": True,
        "activity_id": None,
    }


def _row_to_form(act_id: int) -> dict:
    """Pull current values from DB for an Edit."""
    from strava_analytics.db.models import Activity
    with session_scope() as session:
        act = session.get(Activity, act_id)
        if act is None:
            return _default_modal_values()
        overrides = act.manual_overrides or {}
        def pick(field, default=None):
            return overrides.get(field, getattr(act, field, default))
        dt = pick("start_time") or act.start_time
        distance_m = pick("distance_m") or 0
        moving_time_s = pick("moving_time_s") or 0
        elev_m = pick("elevation_gain_m") or 0
        return {
            "type": pick("type") or "Run",
            "datetime": dt.strftime("%Y-%m-%dT%H:%M") if dt else datetime.now().strftime("%Y-%m-%dT%H:%M"),
            "duration": round(moving_time_s / 60.0, 2) if moving_time_s else None,
            "distance": round(distance_m / 1609.344, 3) if distance_m else None,
            "elev": round(elev_m * 3.28084, 0) if elev_m else None,
            "avghr": pick("avg_hr"),
            "maxhr": pick("max_hr"),
            "calories": pick("calories"),
            "name": pick("name") or "",
            "desc": pick("description") or "",
            "title": "Edit Activity",
            "open": True,
            "activity_id": act_id,
        }


@callback(
    Output("activity-form-modal", "is_open"),
    Output("activity-modal-title", "children"),
    Output("activity-form-id", "data"),
    Output("activity-form-type", "value"),
    Output("activity-form-datetime", "value"),
    Output("activity-form-duration", "value"),
    Output("activity-form-distance", "value"),
    Output("activity-form-elev", "value"),
    Output("activity-form-avghr", "value"),
    Output("activity-form-maxhr", "value"),
    Output("activity-form-calories", "value"),
    Output("activity-form-name", "value"),
    Output("activity-form-desc", "value"),
    Output("activity-form-error", "children"),
    Input("activity-add-btn", "n_clicks"),
    Input({"type": "act-edit-btn", "index": dash.ALL}, "n_clicks"),
    Input("activity-form-cancel", "n_clicks"),
    State({"type": "act-edit-btn", "index": dash.ALL}, "id"),
    prevent_initial_call=True,
)
def open_activity_modal(add_clicks, edit_clicks_list, cancel_clicks, edit_ids):
    ctx = dash.callback_context
    if not ctx.triggered:
        return tuple([no_update] * 14)
    trig = ctx.triggered[0]["prop_id"]

    if trig.startswith("activity-form-cancel"):
        return (False, no_update, no_update, no_update, no_update, no_update,
                no_update, no_update, no_update, no_update, no_update,
                no_update, no_update, "")

    if trig.startswith("activity-add-btn"):
        v = _default_modal_values()
    else:
        # An edit button — extract db id from the pattern-matching id
        # The triggered prop_id has the JSON id as prefix.
        import json
        try:
            js = trig.split(".")[0]
            obj = json.loads(js)
            db_id = int(obj["index"])
        except Exception:
            return tuple([no_update] * 14)
        v = _row_to_form(db_id)

    return (
        v["open"], v["title"], v["activity_id"],
        v["type"], v["datetime"],
        v["duration"], v["distance"], v["elev"],
        v["avghr"], v["maxhr"], v["calories"],
        v["name"], v["desc"], "",
    )


@callback(
    Output("activity-form-modal", "is_open", allow_duplicate=True),
    Output("activity-form-error", "children", allow_duplicate=True),
    Output("activity-ops-counter", "data"),
    Input("activity-form-save", "n_clicks"),
    State("activity-form-id", "data"),
    State("activity-form-type", "value"),
    State("activity-form-datetime", "value"),
    State("activity-form-duration", "value"),
    State("activity-form-distance", "value"),
    State("activity-form-elev", "value"),
    State("activity-form-avghr", "value"),
    State("activity-form-maxhr", "value"),
    State("activity-form-calories", "value"),
    State("activity-form-name", "value"),
    State("activity-form-desc", "value"),
    State("activity-ops-counter", "data"),
    prevent_initial_call=True,
)
def save_activity(
    n_clicks, act_id, atype, dt_str, duration_min, distance_mi, elev_ft,
    avg_hr, max_hr, calories, name, desc, ops_count,
):
    if not n_clicks:
        return no_update, no_update, no_update
    if not atype or not dt_str:
        return True, "Type and date are required.", no_update
    try:
        dt = datetime.fromisoformat(dt_str)
    except Exception:
        return True, "Invalid datetime.", no_update

    payload = {
        "type": atype,
        "start_time": dt,
        "name": name or None,
        "description": desc or None,
        "moving_time_s": float(duration_min) * 60.0 if duration_min else None,
        "elapsed_time_s": float(duration_min) * 60.0 if duration_min else None,
        "distance_m": float(distance_mi) * 1609.344 if distance_mi is not None else None,
        "elevation_gain_m": float(elev_ft) / 3.28084 if elev_ft is not None else None,
        "avg_hr": float(avg_hr) if avg_hr is not None else None,
        "max_hr": float(max_hr) if max_hr is not None else None,
        "calories": float(calories) if calories is not None else None,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        with session_scope() as session:
            if act_id:
                row = patch_activity(session, activity_id=int(act_id), patch=payload)
                if row is None:
                    return True, "Activity not found.", no_update
            else:
                create_manual_activity(session, user_id=1, payload=payload)
    except Exception as e:
        return True, f"Save failed: {e}", no_update

    invalidate_cache()
    data.reload()
    return False, "", (ops_count or 0) + 1


@callback(
    Output("activity-delete-confirm", "displayed"),
    Output("activity-delete-target", "data"),
    Input({"type": "act-delete-btn", "index": dash.ALL}, "n_clicks"),
    State({"type": "act-delete-btn", "index": dash.ALL}, "id"),
    prevent_initial_call=True,
)
def prompt_delete(clicks_list, ids):
    if not any(clicks_list or []):
        return no_update, no_update
    # Find which button triggered via the latest n_clicks change.
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, no_update
    import json
    try:
        js = ctx.triggered[0]["prop_id"].split(".")[0]
        obj = json.loads(js)
        db_id = int(obj["index"])
    except Exception:
        return no_update, no_update
    return True, db_id


@callback(
    Output("activity-ops-counter", "data", allow_duplicate=True),
    Input("activity-delete-confirm", "submit_n_clicks"),
    State("activity-delete-target", "data"),
    State("activity-ops-counter", "data"),
    prevent_initial_call=True,
)
def confirm_delete(submit_clicks, db_id, ops_count):
    if not submit_clicks or not db_id:
        return no_update
    with session_scope() as session:
        soft_delete_activity(session, activity_id=int(db_id))
    invalidate_cache()
    data.reload()
    return (ops_count or 0) + 1


# Re-render the visible card list when an op counter bumps.
@callback(
    Output("visible-activity-cards", "children"),
    Output("hidden-activity-cards", "children", allow_duplicate=True),
    Output("show-all-activities-btn", "style", allow_duplicate=True),
    Input("activity-ops-counter", "data"),
    prevent_initial_call=True,
)
def rebuild_feed(_ops_count):
    df = data.get_df()
    if df.empty:
        return [], [], {"display": "none"}
    sorted_df = df.sort_values("date", ascending=False)
    total = len(sorted_df)
    visible_rows = sorted_df.head(_PAGE_SIZE)
    cards = []
    for idx, (_, row) in enumerate(visible_rows.iterrows()):
        cards.append(_activity_card(row, idx, default_open=False))
    hidden_count = max(0, total - _PAGE_SIZE)
    btn_style = {"display": "block" if hidden_count else "none",
                 "margin": "20px auto"}
    return cards, [], btn_style
