"""Settings page — theme toggle, HR zones, and app configuration."""

import dash
from dash import html, dcc, callback, clientside_callback, Output, Input, State

from strava_analytics.web import data
from strava_analytics.web.components.layout import (
    hero_section, page_section, footer,
)
from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, ACCENT_AMBER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BG_CARD, BG_SURFACE, BORDER,
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
            style={"width": "100px", "fontFamily": "'IBM Plex Mono', monospace",
                   "fontSize": "16px", "fontWeight": "700"},
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


def layout(**_kwargs):
    # Read current theme from a dcc.Store (populated by clientside callback on load)
    return html.Div([
        hero_section(
            label="SETTINGS",
            headline="Make it yours.",
            subtext="Appearance and preferences.",
        ),

        dcc.Store(id="current-theme-store"),

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

        page_section("ABOUT", [
            html.Div([
                html.P("Strava Analytics", style={
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
        var saved = localStorage.getItem("strava-theme") || "system";
        setTimeout(function() {
            var cards = document.querySelectorAll(".theme-option-card");
            cards.forEach(function(c) { c.style.borderColor = ""; });
            var active = document.getElementById("theme-" + saved);
            if (active) active.style.borderColor = "#ef3c4a";
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
        localStorage.setItem("strava-theme", theme);
        if (window._applyTheme) window._applyTheme(theme);

        // Update card highlights
        var cards = document.querySelectorAll(".theme-option-card");
        cards.forEach(function(c) { c.style.borderColor = ""; });
        var active = document.getElementById("theme-" + theme);
        if (active) active.style.borderColor = "#ef3c4a";

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
    pcts = [int(p) for p in zone_pct_str.split(",")]
    cfg = data.get_athlete_config()
    cfg["max_hr"] = int(max_hr)
    cfg["hr_zones_pct"] = pcts[:4]
    data.save_athlete_config(cfg)
    # Re-enrich data with new zones so charts update immediately
    data.reload()
    return "Saved and applied.", (current_version or 0) + 1
