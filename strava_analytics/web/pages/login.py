"""Login + signup pages.

Thin forms that POST to ``/api/auth/login`` and ``/api/auth/signup`` via
a clientside callback. After success the cookie is set server-side and
we redirect to ``/``. Anonymous visitors can still browse the demo
dashboard; login is only needed for mutations, Settings, and to see
their own data.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, clientside_callback, dcc, html

from strava_analytics.web.theme import (
    BG_CARD, BORDER, FONT_MONO, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)


dash.register_page(__name__, path="/login", name="Login")


def _form_input(id_: str, label: str, type_: str = "text",
                placeholder: str = "", value: str = "",
                autocomplete: str = "") -> html.Div:
    return html.Div([
        html.Label(label, htmlFor=id_, style={
            "fontSize": "11px", "fontWeight": "600",
            "textTransform": "uppercase", "letterSpacing": "0.08em",
            "color": TEXT_MUTED, "marginBottom": "6px",
            "display": "block",
        }),
        dcc.Input(
            id=id_, type=type_, value=value, placeholder=placeholder,
            autoComplete=autocomplete or None,
            style={
                "width": "100%", "fontFamily": FONT_MONO,
                "fontSize": "14px", "padding": "10px 12px",
                "border": f"1px solid {BORDER}",
                "borderRadius": "4px", "backgroundColor": "transparent",
                "color": "inherit", "outline": "none",
                "boxSizing": "border-box",
            },
            debounce=False,
        ),
    ], style={"marginBottom": "16px"})


def layout(**kwargs):
    return html.Div([
        html.Div([
            html.Div([
                html.Img(src="/assets/meron-icon.svg", alt="MERON",
                         style={"width": "40px", "height": "40px",
                                "marginBottom": "16px", "opacity": "0.9"}),
                html.H1("Sign in", style={
                    "fontSize": "28px", "fontWeight": "700",
                    "margin": "0 0 8px 0", "color": TEXT_PRIMARY,
                    "letterSpacing": "-0.01em",
                }),
                html.P("Welcome back.", style={
                    "color": TEXT_MUTED, "margin": "0 0 28px 0",
                    "fontSize": "14px",
                }),
                _form_input("login-username", "Username",
                            placeholder="you",
                            autocomplete="username"),
                _form_input("login-password", "Password", type_="password",
                            placeholder="••••••••",
                            autocomplete="current-password"),
                html.Button(
                    "Sign in", id="login-submit", n_clicks=0,
                    className="btn-accent",
                    style={"padding": "12px 24px", "fontSize": "14px",
                           "fontWeight": "600", "width": "100%",
                           "marginTop": "4px", "cursor": "pointer"},
                ),
                html.Div(id="login-status", style={
                    "marginTop": "14px", "fontSize": "13px",
                    "color": "var(--accent)", "minHeight": "18px",
                    "textAlign": "center",
                }),
                html.Div(
                    dcc.Link("Have an invite? Sign up",
                             href="/signup",
                             style={"color": TEXT_MUTED,
                                    "fontSize": "13px",
                                    "textDecoration": "underline"}),
                    style={"textAlign": "center", "marginTop": "20px"},
                ),
            ], style={
                "backgroundColor": BG_CARD,
                "border": f"1px solid {BORDER}",
                "borderRadius": "6px",
                "padding": "40px 36px",
                "width": "100%", "maxWidth": "380px",
                "boxShadow": "0 1px 2px rgba(0,0,0,0.04)",
            }),
        ], style={
            "minHeight": "calc(100vh - 64px)",
            "display": "flex", "alignItems": "center",
            "justifyContent": "center",
            "padding": "40px 24px",
        }),
    ])


# Submit via clientside fetch — no page reload needed for the XHR itself,
# but we do a hard redirect on success so the cookie is seen by Dash.
clientside_callback(
    """
    async function(n_clicks, username, password) {
        if (!n_clicks) return '';
        if (!username || !password) return 'Enter username and password.';
        try {
            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({username, password}),
            });
            const body = await resp.json();
            if (resp.ok) {
                window.location.href = '/';
                return 'Signed in.';
            }
            return (body.error && body.error.message) || 'Login failed.';
        } catch (e) {
            return 'Network error: ' + e.message;
        }
    }
    """,
    Output("login-status", "children"),
    Input("login-submit", "n_clicks"),
    State("login-username", "value"),
    State("login-password", "value"),
    prevent_initial_call=True,
)
