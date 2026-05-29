"""Settings page — theme toggle, HR zones, Data Sources, and app configuration."""

import base64

import dash
from dash import html, dcc, callback, clientside_callback, Output, Input, State, no_update
from sqlalchemy import select

from strava_analytics.api import pairing
from strava_analytics.api.context import current_user_id
from strava_analytics.auth import strava_oauth
from strava_analytics.db import session_scope
from strava_analytics.db.models import SyncState, User
from strava_analytics.services.ingestion.strava_csv import ingest_bulk
from strava_analytics.services.sync import run_strava_sync
from strava_analytics.web import data
from strava_analytics.web.components.layout import (
    hero_section, page_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BG_CARD, BG_SURFACE, BORDER, FONT_MONO,
)

dash.register_page(__name__, path="/settings", name="Settings")


def _theme_option(value: str, label: str, description: str, icon: str) -> html.Button:
    """A clickable card for theme selection."""
    return html.Button([
        html.Div(icon, style={"fontSize": "24px", "marginBottom": "8px"}),
        html.Div(label, style={
            "fontSize": "14px", "fontWeight": "600",
        }),
        html.Div(description, style={
            "fontSize": "12px", "color": TEXT_MUTED, "marginTop": "4px",
        }),
    ], id=f"theme-{value}", n_clicks=0,
       className="theme-option-card")


def _hr_zones_section() -> html.Div:
    """Interactive HR zone bar with draggable boundaries."""
    cfg = data.get_athlete_config()
    max_hr = cfg.get("max_hr", 200)
    zone_pct = cfg.get("hr_zones_pct", [60, 70, 80, 90])
    zone_names = ["Recovery", "Easy", "Moderate", "Threshold", "Max"]
    zone_colors = [ACCENT_SLATE, ACCENT_SLATE, ACCENT_AMBER, ACCENT, ACCENT]
    zone_opacities = [0.4, 0.7, 0.7, 0.7, 1.0]

    # Hidden stores for the zone percentages (updated by JS drag)
    stores = [dcc.Store(id=f"zone-pct-{i}", data=zone_pct[i]) for i in range(4)]

    # The zone bar — segments are laid out by flex with data attributes.
    # JS reads data-zone-pct from the container and renders/updates segments.
    zone_bar = html.Div(
        id="hr-zone-bar",
        **{
            "data-max-hr": str(max_hr),
            "data-zone-pct": ",".join(str(p) for p in zone_pct),
            "data-zone-names": ",".join(zone_names),
            "data-zone-colors": ",".join(zone_colors),
            "data-zone-opacities": ",".join(str(o) for o in zone_opacities),
        },
        style={"position": "relative", "height": "70px", "marginBottom": "24px",
               "userSelect": "none"},
    )

    # Max HR input
    max_hr_input = html.Div([
        html.Label("Max Heart Rate", style={
            "fontSize": "12px", "fontWeight": "600",
            "color": TEXT_SECONDARY, "marginBottom": "4px",
            "display": "block",
        }),
        dcc.Input(
            id="max-hr-input",
            type="number",
            value=max_hr,
            min=140, max=230, step=1,
            style={
                "width": "100px", "fontFamily": FONT_MONO,
                "fontSize": "16px", "fontWeight": "700",
                "padding": "8px 10px",
                "border": f"1px solid {BORDER}",
                "borderRadius": "4px",
                "backgroundColor": "transparent",
                "color": "inherit", "outline": "none",
                "boxSizing": "border-box",
            },
        ),
        html.Span(" bpm", style={"color": TEXT_MUTED, "marginLeft": "8px"}),
    ], style={"marginBottom": "20px"})

    # Save button
    save_btn = html.Button("Save HR Settings", id="save-hr-btn", n_clicks=0,
                           className="btn-accent",
                           style={"padding": "8px 20px", "fontSize": "13px"})
    save_status = html.Span(id="hr-save-status", style={
        "marginLeft": "12px", "fontSize": "13px", "color": TEXT_MUTED,
    })

    return html.Div([*stores, dcc.Store(id="zone-pct-sync"),
                      zone_bar, max_hr_input,
                      html.Div([save_btn, save_status])])


def _read_api_key() -> str:
    """Fetch the current user's read API key for mobile pairing."""
    with session_scope() as session:
        row = session.scalar(
            select(SyncState).where(
                SyncState.user_id == current_user_id(),
                SyncState.provider == "strava",
            )
        )
        return (row.api_key_read if row else "") or ""


def _qr_data_url(payload: str) -> str:
    """Render ``payload`` as a ``data:image/svg+xml;base64,...`` URL.

    Returned as an ``<img src>`` value, which sidesteps the Markdown
    sanitizer's stripping of raw ``<svg>`` tags in Dash.
    """
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError:
        return ""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(image_factory=SvgPathImage)
    import base64
    import io
    buf = io.BytesIO()
    img.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _pair_card_body(code: str | None, api_base: str | None) -> list:
    """Render the pair-card body depending on whether a code is live."""
    if not code:
        return [
            html.P("Scan a one-time QR from your phone to sign the MERON app in. "
                   "Codes expire after 10 minutes and are single-use.",
                   style={"color": TEXT_SECONDARY, "fontSize": "13px",
                          "margin": "0 0 10px 0"}),
            html.Button("Generate pair code", id="pair-generate-btn", n_clicks=0,
                        className="btn-accent",
                        style={"padding": "8px 20px", "fontSize": "13px"}),
        ]

    # We have a live code — render the QR + the short code as a fallback.
    import json
    payload = json.dumps({"api_base": api_base, "pair_code": code},
                         separators=(",", ":"))
    data_url = _qr_data_url(payload)
    if data_url:
        qr_el = html.Img(src=data_url, alt="pairing QR",
                         style={"width": "180px", "height": "180px",
                                "display": "block"})
    else:
        qr_el = html.Div("QR library not installed — use the code below.",
                         style={"color": TEXT_MUTED, "fontSize": "12px"})

    pretty_code = f"{code[:4]}-{code[4:]}" if len(code) == 8 else code
    return [
        html.Div([
            html.Div(qr_el, style={
                "background": "#fff", "padding": "8px",
                "display": "inline-block", "border": f"1px solid {BORDER}",
            }),
            html.Div([
                html.Div("PAIR CODE", style={
                    "fontSize": "11px", "letterSpacing": "0.2em",
                    "color": TEXT_MUTED, "fontFamily": FONT_MONO,
                }),
                html.Div(pretty_code, style={
                    "fontSize": "28px", "fontWeight": "700",
                    "fontFamily": FONT_MONO, "letterSpacing": "0.05em",
                    "color": TEXT_PRIMARY, "margin": "4px 0",
                }),
                html.Div(f"Server: {api_base}", style={
                    "fontSize": "12px", "color": TEXT_MUTED,
                    "fontFamily": FONT_MONO, "marginBottom": "10px",
                }),
                html.Div("Expires in 10 minutes. One use only.", style={
                    "fontSize": "12px", "color": TEXT_MUTED,
                }),
                html.Button("Regenerate", id="pair-generate-btn", n_clicks=0,
                            className="btn-ghost",
                            style={"padding": "6px 14px", "fontSize": "12px",
                                   "marginTop": "10px"}),
            ], style={"flex": "1", "marginLeft": "20px"}),
        ], style={"display": "flex", "alignItems": "flex-start"}),
    ]


def _admin_invites_section() -> html.Div | None:
    """Admin-only card — generate + revoke signup invite codes."""
    from strava_analytics.api.context import current_is_admin
    if not current_is_admin():
        return None

    return html.Div([
        html.H4("Invite users",
                style={"fontSize": "15px", "margin": "0 0 10px 0"}),
        html.P(
            "Generate a one-time code to let a friend sign up. "
            "Consumed on first signup; share it over a trusted channel.",
            style={"color": TEXT_SECONDARY, "fontSize": "13px",
                   "margin": "0 0 10px 0"},
        ),
        html.Button("Generate invite", id="invite-generate-btn", n_clicks=0,
                    className="btn-accent",
                    style={"padding": "8px 20px", "fontSize": "13px"}),
        html.Div(id="invite-latest", style={
            "marginTop": "10px", "fontFamily": FONT_MONO, "fontSize": "13px",
            "color": TEXT_PRIMARY,
        }),
        html.Div(id="invite-list", style={
            "marginTop": "14px", "fontSize": "12px", "color": TEXT_MUTED,
        }),
    ], style={
        "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
        "padding": "20px", "marginBottom": "12px",
    })


def _mobile_pair_section() -> html.Div:
    return html.Div([
        html.H4("Pair mobile app",
                style={"fontSize": "15px", "margin": "0 0 10px 0"}),
        html.Div(
            _pair_card_body(None, None),
            id="pair-card-body",
        ),
    ], style={
        "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
        "padding": "20px", "marginBottom": "12px",
    })


def _strava_status() -> dict:
    """Return {connected, athlete_id, last_sync_at, configured}."""
    info = {
        "configured": strava_oauth.is_configured(),
        "connected": False,
        "athlete_id": None,
        "last_sync_at": None,
    }
    try:
        with session_scope() as session:
            row = session.scalar(
                select(SyncState).where(
                    SyncState.user_id == current_user_id(),
                    SyncState.provider == "strava",
                )
            )
            if row and row.refresh_token:
                info["connected"] = True
                info["last_sync_at"] = (
                    row.last_sync_at.strftime("%Y-%m-%d %H:%M UTC")
                    if row.last_sync_at else "never"
                )
            user = session.get(User, 1)
            if user and user.strava_athlete_id:
                info["athlete_id"] = user.strava_athlete_id
    except Exception:
        pass
    return info


def _data_sources_section() -> html.Div:
    status = _strava_status()

    upload_card = html.Div([
        html.H4("Upload Strava export",
                style={"fontSize": "15px", "margin": "0 0 6px 0"}),
        html.P(
            "Drop a Strava bulk export (zip) or a single activities.csv.",
            style={"color": TEXT_MUTED, "fontSize": "13px", "marginBottom": "10px"},
        ),
        dcc.Upload(
            id="strava-export-upload",
            children=html.Div([
                html.Span("Drop file or "),
                html.Span("browse", style={"textDecoration": "underline"}),
            ]),
            style={
                "width": "100%", "minHeight": "70px",
                "lineHeight": "70px", "textAlign": "center",
                "border": f"1px dashed {BORDER}", "fontSize": "13px",
                "color": TEXT_SECONDARY, "cursor": "pointer",
            },
            multiple=False,
            accept=".zip,.csv",
        ),
        html.Div(id="strava-upload-status", style={
            "marginTop": "8px", "fontSize": "13px", "color": TEXT_SECONDARY,
        }),
    ], style={
        "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
        "padding": "20px", "marginBottom": "12px",
    })

    # Strava OAuth card
    if not status["configured"]:
        strava_body = html.P(
            "Strava OAuth is not configured. Set STRAVA_CLIENT_ID and "
            "STRAVA_CLIENT_SECRET environment variables, then restart the server.",
            style={"color": TEXT_MUTED, "fontSize": "13px", "margin": "0"},
        )
    elif status["connected"]:
        strava_body = html.Div([
            html.Div([
                html.Span("Connected", style={
                    "color": ACCENT, "fontWeight": "600", "fontSize": "13px",
                }),
                html.Span(
                    f" · athlete {status['athlete_id']}" if status["athlete_id"] else "",
                    style={"color": TEXT_MUTED, "fontSize": "13px"},
                ),
            ], style={"marginBottom": "6px"}),
            html.Div(f"Last sync: {status['last_sync_at']}",
                     style={"color": TEXT_MUTED, "fontSize": "13px",
                            "marginBottom": "12px"}),
            html.Div([
                html.Button("Sync now", id="strava-sync-btn", n_clicks=0,
                            className="btn-accent",
                            style={"padding": "8px 20px", "fontSize": "13px",
                                   "marginRight": "8px"}),
                html.Button("Disconnect", id="strava-disconnect-btn", n_clicks=0,
                            className="btn-ghost",
                            style={"padding": "8px 20px", "fontSize": "13px"}),
            ]),
            html.Div(id="strava-sync-status", style={
                "marginTop": "10px", "fontSize": "13px", "color": TEXT_SECONDARY,
            }),
        ])
    else:
        strava_body = html.Div([
            html.P("Authorize MERON to pull activities directly from Strava.",
                   style={"color": TEXT_SECONDARY, "fontSize": "13px",
                          "margin": "0 0 10px 0"}),
            html.A("Connect Strava",
                   href="/oauth/strava/start",
                   className="btn-accent",
                   style={"display": "inline-block",
                          "padding": "8px 20px", "fontSize": "13px",
                          "textDecoration": "none"}),
        ])

    strava_card = html.Div([
        html.H4("Connect Strava",
                style={"fontSize": "15px", "margin": "0 0 10px 0"}),
        strava_body,
    ], style={
        "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
        "padding": "20px", "marginBottom": "12px",
    })

    # Apple Health placeholder
    apple_card = html.Div([
        html.H4("Apple Health",
                style={"fontSize": "15px", "margin": "0 0 6px 0"}),
        html.P("Coming soon — pull workouts from iOS Health.",
               style={"color": TEXT_MUTED, "fontSize": "13px",
                      "margin": "0 0 10px 0"}),
        html.Button("Coming soon",
                    disabled=True,
                    className="btn-ghost",
                    style={"padding": "8px 20px", "fontSize": "13px",
                           "opacity": "0.5", "cursor": "not-allowed"}),
    ], style={
        "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
        "padding": "20px",
    })

    cards = [upload_card, strava_card, _mobile_pair_section()]
    admin_card = _admin_invites_section()
    if admin_card is not None:
        cards.append(admin_card)
    cards.append(apple_card)
    return html.Div(cards)


def layout(**_kwargs):
    # Settings is login-gated. Anonymous visitors can still see the read-only
    # dashboard pages, but managing Strava / HR zones / invites requires auth.
    from strava_analytics.api.context import is_authenticated
    if not is_authenticated():
        return html.Div([
            hero_section(
                label="SETTINGS",
                headline="Sign in to manage your account.",
                subtext="The public demo is read-only. Log in to connect your "
                        "own Strava, edit activities, and pair the mobile app.",
            ),
            html.Div([
                dcc.Link("Log in", href="/login",
                         className="btn-accent",
                         style={"display": "inline-block",
                                "padding": "10px 24px", "fontSize": "13px",
                                "textDecoration": "none",
                                "marginRight": "10px"}),
                dcc.Link("Sign up with an invite", href="/signup",
                         className="btn-ghost",
                         style={"display": "inline-block",
                                "padding": "10px 24px", "fontSize": "13px",
                                "textDecoration": "none"}),
            ], style={"padding": "40px 24px"}),
            footer(),
        ])

    # Read current theme from a dcc.Store (populated by clientside callback on load)
    return html.Div([
        hero_section(
            label="SETTINGS",
            headline="Make it yours.",
            subtext="Appearance and preferences.",
        ),

        dcc.Store(id="current-theme-store"),

        page_section("DATA SOURCES", [
            html.P(
                "Connect Strava, upload an export, or plug in Apple Health.",
                style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                       "marginBottom": "20px"},
            ),
            _data_sources_section(),
        ]),

        page_section("APPEARANCE", [
            html.P("Choose your theme. Your preference is saved locally.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                          "marginBottom": "20px"}),
            html.Div([
                _theme_option("light", "Light", "Bright and clean", "\u2600\uFE0E"),
                _theme_option("dark", "Dark", "Easy on the eyes", "\u263D"),
                _theme_option("system", "System", "Match your OS", "\u2699\uFE0E"),
            ], id="theme-options", style={
                "display": "flex", "gap": "16px", "flexWrap": "wrap",
            }),
            html.Div(id="theme-selection-output", style={"display": "none"}),
        ]),

        page_section("HEART RATE ZONES", [
            html.P("Configure your HR zones for run classification. Changes require a server restart to take effect.",
                   style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                          "marginBottom": "20px"}),
            _hr_zones_section(),
        ], alt_bg=True),

        page_section("CHATGPT INTEGRATION", [
            html.P(
                "Enter your OpenAI API key to enable the chat widget. "
                "Get one at platform.openai.com (included with ChatGPT Pro).",
                style={"color": TEXT_SECONDARY, "fontSize": "0.9rem",
                       "marginBottom": "16px"},
            ),
            html.Div([
                html.Label("OpenAI API Key", style={
                    "fontSize": "12px", "fontWeight": "600",
                    "color": TEXT_SECONDARY, "marginBottom": "4px",
                    "display": "block",
                }),
                dcc.Input(
                    id="openai-key-input",
                    type="password",
                    value=data.get_athlete_config().get("openai_api_key", ""),
                    placeholder="sk-...",
                    style={
                        "width": "320px", "fontFamily": FONT_MONO,
                        "fontSize": "13px",
                        "padding": "8px 10px",
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "4px",
                        "backgroundColor": "transparent",
                        "color": "inherit", "outline": "none",
                        "boxSizing": "border-box",
                    },
                ),
            ], style={"marginBottom": "12px"}),
            html.Div([
                html.Button("Save API Key", id="save-openai-key-btn", n_clicks=0,
                            className="btn-accent",
                            style={"padding": "8px 20px", "fontSize": "13px"}),
                html.Span(id="openai-key-save-status", style={
                    "marginLeft": "12px", "fontSize": "13px", "color": TEXT_MUTED,
                }),
            ]),
        ]),

        page_section("ABOUT", [
            html.Div([
                html.P("MERON", style={
                    "fontSize": "16px", "fontWeight": "700", "color": TEXT_PRIMARY,
                }),
                html.P(
                    "Personal fitness intelligence, built from your Strava export data. "
                    "Charts powered by Chart.js. Maps by Leaflet. No data leaves your machine.",
                    style={"color": TEXT_SECONDARY, "fontSize": "0.85rem",
                           "marginTop": "8px", "lineHeight": "1.6"},
                ),
            ], style={
                "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
                "padding": "24px",
            }),
        ], alt_bg=True),

        footer(),
    ])


# ── Clientside callbacks ──────────────────────────────────────────────

# On page load: read localStorage and highlight the active theme option
clientside_callback(
    """
    function(pathname) {
        var saved = localStorage.getItem("meron-theme")
                 || localStorage.getItem("strava-theme")
                 || "system";
        if (localStorage.getItem("strava-theme") && !localStorage.getItem("meron-theme")) {
            localStorage.setItem("meron-theme", saved);
            localStorage.removeItem("strava-theme");
        }
        setTimeout(function() {
            var cards = document.querySelectorAll(".theme-option-card");
            cards.forEach(function(c) { c.style.borderColor = ""; });
            var active = document.getElementById("theme-" + saved);
            if (active) active.style.borderColor = "#1a8a77";
        }, 200);
        return saved;
    }
    """,
    Output("current-theme-store", "data"),
    Input("url", "pathname"),
)

# On theme selection: apply theme, save to localStorage, update highlight
clientside_callback(
    """
    function(n1, n2, n3) {
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length) return "";
        var triggeredId = ctx.triggered[0].prop_id.split(".")[0];
        var theme = triggeredId.replace("theme-", "");

        // Save and apply
        localStorage.setItem("meron-theme", theme);
        if (window._applyTheme) window._applyTheme(theme);

        // Update card highlights
        var cards = document.querySelectorAll(".theme-option-card");
        cards.forEach(function(c) { c.style.borderColor = ""; });
        var active = document.getElementById("theme-" + theme);
        if (active) active.style.borderColor = "#1a8a77";

        return theme;
    }
    """,
    Output("theme-selection-output", "children"),
    Input("theme-light", "n_clicks"),
    Input("theme-dark", "n_clicks"),
    Input("theme-system", "n_clicks"),
    prevent_initial_call=True,
)


# Save HR zone settings
# Sync zone bar data attribute to a hidden store on save click
clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return window.dash_clientside.no_update;
        if (window._currentZonePct && window._currentZonePct.length === 4) {
            return window._currentZonePct.join(",");
        }
        var bar = document.getElementById("hr-zone-bar");
        if (!bar) return "";
        return bar.getAttribute("data-zone-pct") || "60,70,80,90";
    }
    """,
    Output("zone-pct-sync", "data"),
    Input("save-hr-btn", "n_clicks"),
    prevent_initial_call=True,
)


@callback(
    Output("hr-save-status", "children"),
    Output("data-version-store", "data"),
    Input("zone-pct-sync", "data"),
    State("max-hr-input", "value"),
    State("data-version-store", "data"),
    prevent_initial_call=True,
)
def save_hr_settings(zone_pct_str, max_hr, current_version):
    if not zone_pct_str or not max_hr:
        return "", (current_version or 0)
    from strava_analytics.api.context import is_authenticated
    if not is_authenticated():
        return "Log in first.", (current_version or 0)
    pcts = [int(p) for p in zone_pct_str.split(",")]
    cfg = data.get_athlete_config()
    cfg["max_hr"] = int(max_hr)
    cfg["hr_zones_pct"] = pcts[:4]
    data.save_athlete_config(cfg)
    # Re-enrich data with new zones so charts update immediately
    data.reload()
    return "Saved and applied.", (current_version or 0) + 1


@callback(
    Output("openai-key-save-status", "children"),
    Input("save-openai-key-btn", "n_clicks"),
    State("openai-key-input", "value"),
    prevent_initial_call=True,
)
def save_openai_key(n_clicks, api_key):
    if not n_clicks:
        return ""
    from strava_analytics.api.context import is_authenticated
    if not is_authenticated():
        return "Log in first."
    cfg = data.get_athlete_config()
    cfg["openai_api_key"] = (api_key or "").strip()
    data.save_athlete_config(cfg)
    return "Saved." if api_key else "Cleared."


# ── Data Sources callbacks ───────────────────────────────────────────

def _format_report(report: dict) -> str:
    parts = []
    if report.get("inserted"):
        parts.append(f"{report['inserted']} new")
    if report.get("updated"):
        parts.append(f"{report['updated']} updated")
    if report.get("skipped"):
        parts.append(f"{report['skipped']} skipped")
    errs = report.get("errors") or []
    if errs:
        parts.append(f"{len(errs)} errors")
    return ", ".join(parts) or "no changes"


@callback(
    Output("strava-upload-status", "children"),
    Output("data-version-store", "data", allow_duplicate=True),
    Input("strava-export-upload", "contents"),
    State("strava-export-upload", "filename"),
    State("data-version-store", "data"),
    prevent_initial_call=True,
)
def handle_strava_upload(contents, filename, current_version):
    if not contents or not filename:
        return no_update, no_update
    from strava_analytics.api.context import is_authenticated
    if not is_authenticated():
        return "Log in first.", (current_version or 0)

    # Decode the base64 payload dcc.Upload provides
    header, _, b64 = contents.partition(",")
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        return f"Upload failed: {e}", (current_version or 0)

    import tempfile, zipfile
    from pathlib import Path
    from strava_analytics.db import meron_dir

    upload_root = meron_dir() / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = upload_root / ts
    dest.mkdir(parents=True, exist_ok=True)
    saved = dest / Path(filename).name
    saved.write_bytes(raw)

    # If a zip, extract; if a bare csv, place it as activities.csv
    target = None
    lower = filename.lower()
    if lower.endswith(".zip"):
        try:
            with zipfile.ZipFile(saved) as zf:
                zf.extractall(dest)
        except zipfile.BadZipFile:
            return "Not a valid zip file.", (current_version or 0)
        for cand in [dest, *dest.iterdir()]:
            if cand.is_dir() and (cand / "activities.csv").exists():
                target = cand
                break
    elif lower.endswith(".csv"):
        if saved.name != "activities.csv":
            (dest / "activities.csv").write_bytes(raw)
        target = dest
    else:
        return f"Unsupported file type: {filename}", (current_version or 0)

    if target is None:
        return "activities.csv not found in upload.", (current_version or 0)

    with session_scope() as session:
        report = ingest_bulk(target, user_id=current_user_id(), session=session)
    data.reload()
    return f"Imported: {_format_report(report)}.", (current_version or 0) + 1


@callback(
    Output("strava-sync-status", "children"),
    Output("data-version-store", "data", allow_duplicate=True),
    Input("strava-sync-btn", "n_clicks"),
    State("data-version-store", "data"),
    prevent_initial_call=True,
)
def handle_strava_sync(n_clicks, current_version):
    if not n_clicks:
        return no_update, no_update
    from strava_analytics.api.context import is_authenticated
    if not is_authenticated():
        return "Log in first.", (current_version or 0)
    with session_scope() as session:
        report = run_strava_sync(user_id=current_user_id(), session=session)
    data.reload()
    return f"Sync: {_format_report(report)}.", (current_version or 0) + 1


@callback(
    Output("strava-sync-status", "children", allow_duplicate=True),
    Input("strava-disconnect-btn", "n_clicks"),
    prevent_initial_call=True,
)
def handle_strava_disconnect(n_clicks):
    if not n_clicks:
        return no_update
    from strava_analytics.api.context import is_authenticated
    if not is_authenticated():
        return "Log in first."
    with session_scope() as session:
        strava_oauth.disconnect(session, user_id=current_user_id())
    return "Disconnected. Reload the page."


@callback(
    Output("invite-latest", "children"),
    Output("invite-list", "children"),
    Input("invite-generate-btn", "n_clicks"),
    prevent_initial_call=True,
)
def handle_generate_invite(n_clicks):
    if not n_clicks:
        return no_update, no_update
    from strava_analytics.api.context import current_is_admin
    from strava_analytics.api.routes.auth import _new_invite_code
    from strava_analytics.db.models import InviteCode
    if not current_is_admin():
        return "Admin only.", no_update
    code = _new_invite_code()
    with session_scope() as session:
        session.add(InviteCode(code=code, created_by_user_id=current_user_id()))
        session.commit()
        outstanding = session.query(InviteCode).filter(
            InviteCode.consumed_by_user_id.is_(None)
        ).count()
    pretty = f"{code[:4]}-{code[4:]}" if len(code) == 8 else code
    return (
        html.Div([
            html.Span("New code: ", style={"color": TEXT_MUTED}),
            html.Span(pretty, style={"fontWeight": "700"}),
            html.Span("   (share over a trusted channel; signup link: ",
                     style={"color": TEXT_MUTED, "marginLeft": "6px"}),
            html.Code(f"/signup?code={code}"),
            html.Span(")", style={"color": TEXT_MUTED}),
        ]),
        f"{outstanding} outstanding invite(s) total.",
    )


@callback(
    Output("pair-card-body", "children"),
    Input("pair-generate-btn", "n_clicks"),
    prevent_initial_call=True,
)
def handle_generate_pair_code(n_clicks):
    """Mint a single-use pair code bound to the logged-in user."""
    if not n_clicks:
        return no_update

    import os
    from flask import request as flask_request

    from strava_analytics.api.context import is_authenticated

    if not is_authenticated():
        return html.P(
            "Log in first to pair a mobile device.",
            style={"color": TEXT_MUTED, "fontSize": "13px"},
        )

    read_key = _read_api_key()
    if not read_key:
        return html.P(
            "No API key yet — run the server once to seed it, then reload.",
            style={"color": TEXT_MUTED, "fontSize": "13px"},
        )

    # Prefer the explicit public URL for production; fall back to whatever
    # host the browser used to reach Settings (works for local + tunnel).
    api_base = (os.environ.get("MERON_PUBLIC_URL") or
                flask_request.host_url.rstrip("/"))
    code, _expires = pairing.create_pair(api_key=read_key, api_base=api_base)
    return _pair_card_body(code, api_base)
