"""Dash web application — MERON brand layout."""

import argparse
import logging
import os
from pathlib import Path

# Auto-load .env from repo root or ~/.meron/ before anything reads os.environ
try:
    from dotenv import load_dotenv
    # Search order: current working dir, then ~/.meron/
    for _p in (Path.cwd() / ".env", Path.home() / ".meron" / ".env"):
        if _p.exists():
            load_dotenv(_p, override=False)
except ImportError:
    pass

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, page_container, Input, Output, State, callback, clientside_callback
import pandas as pd

from strava_analytics.api import register_api, register_oauth
from strava_analytics.web import data


# Canonical site URL for OpenGraph / Twitter metadata. Leave empty for local dev
# (relative /assets paths work fine locally); set MERON_SITE_URL=https://... when
# the site is publicly deployed so social scrapers can resolve the share image.
SITE_URL = os.environ.get("MERON_SITE_URL", "").rstrip("/")
OG_IMAGE = (f"{SITE_URL}/assets/meron-logo-dark-bg.png"
            if SITE_URL else "/assets/meron-logo-dark-bg.png")


MERON_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
        <meta name="description" content="MERON \u2014 personal fitness intelligence. Strength. Endurance. Elevation.">

        <!-- Favicons -->
        <link rel="icon" type="image/svg+xml" href="/assets/meron-icon.svg">
        <link rel="icon" type="image/png" sizes="32x32" href="/assets/meron-icon.png">

        <!-- Apple touch icons (iOS home screen) -->
        <link rel="apple-touch-icon" sizes="180x180" href="/assets/meron-app-icon.png">
        <link rel="apple-touch-icon" sizes="152x152" href="/assets/meron-app-icon.png">
        <link rel="apple-touch-icon" sizes="120x120" href="/assets/meron-app-icon.png">

        <!-- Standalone iOS / Android web-app -->
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="MERON">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="application-name" content="MERON">

        <!-- Theme color (mobile browser chrome) -->
        <meta name="theme-color" content="#f8f9fc" media="(prefers-color-scheme: light)">
        <meta name="theme-color" content="#0A1B33" media="(prefers-color-scheme: dark)">

        <!-- PWA manifest -->
        <link rel="manifest" href="/assets/manifest.json">

        <!-- OpenGraph -->
        <meta property="og:type" content="website">
        <meta property="og:site_name" content="MERON">
        <meta property="og:title" content="MERON">
        <meta property="og:description" content="Personal fitness intelligence. Strength. Endurance. Elevation.">
        <meta property="og:image" content="__OG_IMAGE__">
        __OG_URL__

        <!-- Twitter Card -->
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="MERON">
        <meta name="twitter:description" content="Personal fitness intelligence. Strength. Endurance. Elevation.">
        <meta name="twitter:image" content="__OG_IMAGE__">

        {%metas%}
        <title>{%title%}</title>
        <!-- Dash's {%favicon%} placeholder is intentionally omitted; the
             explicit <link rel="icon"> tags above reference our MERON
             favicon.ico / SVG / PNG and replace the default Plotly icon. -->
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""


def create_app() -> dash.Dash:
    app = dash.Dash(
        __name__,
        use_pages=True,
        pages_folder=str(Path(__file__).parent / "pages"),
        external_stylesheets=[
            dbc.themes.FLATLY,
            "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap",
            "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        ],
        external_scripts=[
            "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",
            "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js",
            "https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js",
            "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js",
            "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        ],
        suppress_callback_exceptions=True,
        title="MERON",
        update_title=None,
    )

    # Inject branded <head> (favicons, OG, Twitter, manifest, PWA meta)
    og_url_tag = (f'<meta property="og:url" content="{SITE_URL}/">'
                  if SITE_URL else "")
    app.index_string = (
        MERON_INDEX_TEMPLATE
        .replace("__OG_IMAGE__", OG_IMAGE)
        .replace("__OG_URL__", og_url_tag)
    )

    # Hamburger icon (three-line SVG)
    hamburger_svg = html.Span(
        dash.dcc.Markdown(
            '<svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/>'
            '<line x1="3" y1="12" x2="21" y2="12"/>'
            '<line x1="3" y1="18" x2="21" y2="18"/></svg>',
            dangerously_allow_html=True,
        ),
    )

    # Navbar — MERON brand (mobile-responsive)
    navbar = html.Nav([
        html.Div([
            html.Div([
                # Brand
                dcc.Link([
                    html.Img(src="/assets/meron-icon.svg", className="brand-icon", alt="MERON"),
                    html.Span("MERON", className="brand-text"),
                ], href="/", className="brand-link"),
                # Mobile hamburger toggle
                html.Button(
                    hamburger_svg,
                    id="nav-toggle",
                    className="nav-toggle",
                    **{"aria-label": "Toggle navigation"},
                ),
                # Nav links
                html.Div([
                    dcc.Link("Overview", href="/", className="meron-nav-link"),
                    dcc.Link("Running", href="/running", className="meron-nav-link"),
                    dcc.Link("Lifting", href="/lifting", className="meron-nav-link"),
                    dcc.Link("Activities", href="/activities", className="meron-nav-link"),
                    dcc.Link("Plan", href="/plan", className="meron-nav-link"),
                    dcc.Link("\u2699", href="/settings", className="meron-nav-link",
                             style={"fontSize": "18px", "opacity": "0.6"},
                             title="Settings"),
                    # Auth slot — filled by a clientside callback from /api/auth/me.
                    html.Span(id="nav-auth-slot", className="meron-nav-link",
                              style={"fontSize": "13px"}),
                ], id="nav-links", className="nav-links"),
            ], className="nav-inner"),
        ], className="nav-container"),
    ], className="meron-navbar")

    app.layout = html.Div([
        dcc.Location(id="url"),
        html.Div(id="page-title-target", style={"display": "none"}),
        # Global data version — incremented whenever settings are saved and data reloaded
        dcc.Store(id="data-version-store", data=0, storage_type="memory"),
        # Modal system: JS sets location hash → clientside callback → store → server renders
        dcc.Store(id="activity-modal-store", data=None),
        navbar,
        html.Main([
            page_container,
        ]),
        # Activity modal overlay — rendered by server callback
        html.Div(id="activity-modal-container"),
        # Global hover card — follows mouse, used by all chart pages
        html.Div(id="hover-card", style={
            "display": "none",
            "position": "fixed",
            "zIndex": "1000",
            "backgroundColor": "var(--bg-card)",
            "border": "1px solid var(--border)",
            "boxShadow": "0 8px 24px rgba(0,0,0,0.12)",
            "padding": "12px",
            "width": "260px",
            "pointerEvents": "none",
        }),
    ])

    # Register REST API endpoints on the underlying Flask server
    register_api(app.server)
    # Register OAuth blueprint (/oauth/strava/*)
    register_oauth(app.server)

    # Serve /favicon.ico directly from assets/ so bare-path favicon requests
    # (browser tab, link scrapers, /favicon.ico fallback) resolve to MERON.
    from flask import send_from_directory
    _assets_dir = Path(__file__).parent / "assets"

    @app.server.route("/favicon.ico")
    def _serve_favicon():
        return send_from_directory(str(_assets_dir), "favicon.ico",
                                    mimetype="image/x-icon")

    # Dynamic page title based on current URL
    clientside_callback(
        """
        function(pathname) {
            var titles = {
                "/": "Overview",
                "/running": "Running",
                "/lifting": "Lifting",
                "/activities": "Activities",
                "/plan": "Plan",
                "/settings": "Settings"
            };
            var page = titles[pathname] || "Overview";
            document.title = "MERON \u2014 " + page;
            return "";
        }
        """,
        Output("page-title-target", "children"),
        Input("url", "pathname"),
    )

    # Mobile nav toggle — open/close the nav-links panel
    clientside_callback(
        """
        function(n_clicks) {
            var links = document.getElementById("nav-links");
            if (links) {
                links.classList.toggle("nav-open");
            }
            return "";
        }
        """,
        Output("nav-toggle", "className"),
        Input("nav-toggle", "n_clicks"),
        prevent_initial_call=True,
    )

    # Modal trigger: JS sets location hash to #modal:YYYY-MM-DD
    # This clientside callback watches the hash and forwards to the store
    clientside_callback(
        """
        function(href) {
            if (!href) return window.dash_clientside.no_update;
            var hash = new URL(href).hash;
            if (hash && hash.startsWith("#modal:")) {
                var dateStr = hash.substring(7);
                // Clear the hash so it can be re-triggered for same date
                history.replaceState(null, "", window.location.pathname + window.location.search);
                return {date: dateStr, ts: Date.now()};
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("activity-modal-store", "data"),
        Input("url", "href"),
        prevent_initial_call=True,
    )

    # Close modal: clicking close button clears the store
    clientside_callback(
        """
        function(n_clicks) {
            if (!n_clicks) return window.dash_clientside.no_update;
            return null;
        }
        """,
        Output("activity-modal-store", "data", allow_duplicate=True),
        Input("modal-close-btn", "n_clicks"),
        prevent_initial_call=True,
    )

    return app


# ── Global modal callback (outside create_app so it registers at import) ──

@callback(
    Output("activity-modal-container", "children"),
    Input("activity-modal-store", "data"),
    prevent_initial_call=True,
)
def render_activity_modal(modal_data):
    """Render the activity modal overlay when triggered by a chart click."""
    from strava_analytics.web.components.cards import activity_card_body

    if not modal_data or not modal_data.get("date"):
        return html.Div()

    date_str = modal_data["date"]
    df = data.get_df()

    matches = df[df["date"].dt.strftime("%Y-%m-%d") == date_str]
    if matches.empty:
        return html.Div()

    row = matches.iloc[0]
    parts = activity_card_body(row, route_mode="eager")

    return html.Div([
        html.Div(id="modal-backdrop"),
        html.Div([
            html.Button("\u00d7", id="modal-close-btn"),
            html.Div([
                parts["header"],
                html.Div(parts["primary"], style={
                    "display": "flex", "gap": "24px", "flexWrap": "wrap",
                }),
                parts["extra"],
                *(parts["detail"] or []),
            ]),
        ], id="modal-content"),
    ], id="activity-modal-overlay")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="MERON Web Dashboard")
    parser.add_argument(
        "export_dir",
        nargs="?",
        default=None,
        help=(
            "Optional: path to a Strava export directory. If omitted the "
            "DB at $MERON_DB_PATH (~/.meron/meron.db) is used. If provided "
            "and the DB is empty, the export is auto-imported."
        ),
    )
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    data.init(args.export_dir)
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug, dev_tools_ui=False)


if __name__ == "__main__":
    main()
