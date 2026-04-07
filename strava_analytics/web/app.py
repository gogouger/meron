"""Dash web application — Ozni AI brand-matched layout."""

import argparse
import logging
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, page_container, Input, Output, clientside_callback

from strava_analytics.web import data
import strava_analytics.web.theme  # noqa: F401


def create_app() -> dash.Dash:
    app = dash.Dash(
        __name__,
        use_pages=True,
        pages_folder=str(Path(__file__).parent / "pages"),
        external_stylesheets=[
            dbc.themes.FLATLY,
            "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap",
        ],
        suppress_callback_exceptions=True,
        title="Strava Analytics — Ozni AI",
        update_title=None,
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

    # Navbar — matches ozniai.com fixed nav pattern (mobile-responsive)
    navbar = html.Nav([
        html.Div([
            html.Div([
                # Brand
                dcc.Link(
                    html.Span("Strava Analytics", className="brand-text"),
                    href="/", className="brand-link",
                ),
                # Mobile hamburger toggle
                html.Button(
                    hamburger_svg,
                    id="nav-toggle",
                    className="nav-toggle",
                    **{"aria-label": "Toggle navigation"},
                ),
                # Nav links
                html.Div([
                    dcc.Link("Overview", href="/", className="ozni-nav-link"),
                    dcc.Link("Running", href="/running", className="ozni-nav-link"),
                    dcc.Link("Lifting", href="/lifting", className="ozni-nav-link"),
                    dcc.Link("Predictions", href="/races", className="ozni-nav-link"),
                    dcc.Link("Plan", href="/plan", className="ozni-nav-link"),
                ], id="nav-links", className="nav-links"),
            ], className="nav-inner"),
        ], className="nav-container"),
    ], className="ozni-navbar")

    app.layout = html.Div([
        dcc.Location(id="url"),
        html.Div(id="page-title-target", style={"display": "none"}),
        navbar,
        html.Main([
            page_container,
        ]),
    ])

    # Dynamic page title based on current URL
    clientside_callback(
        """
        function(pathname) {
            var titles = {
                "/": "Overview",
                "/running": "Running",
                "/lifting": "Lifting",
                "/races": "Predictions",
                "/plan": "Plan"
            };
            var page = titles[pathname] || "Overview";
            document.title = "Strava Analytics \u2014 " + page;
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

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Strava Analytics Web Dashboard")
    parser.add_argument("export_dir",
                        help="Path to Strava export directory")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    data.init(args.export_dir)
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
