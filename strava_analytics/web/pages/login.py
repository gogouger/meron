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

from strava_analytics.web.components.layout import footer, hero_section
from strava_analytics.web.theme import (
    BG_CARD, BORDER, FONT_MONO, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)


dash.register_page(__name__, path="/login", name="Login")


def _form_input(id_: str, label: str, type_: str = "text",
                placeholder: str = "", value: str = "") -> html.Div:
    return html.Div([
        html.Label(label, style={
            "fontSize": "12px", "fontWeight": "600",
            "color": TEXT_SECONDARY, "marginBottom": "4px",
            "display": "block",
        }),
        dcc.Input(
            id=id_, type=type_, value=value, placeholder=placeholder,
            style={"width": "100%", "fontFamily": FONT_MONO,
                   "fontSize": "13px", "padding": "8px 10px"},
            debounce=False,
        ),
    ], style={"marginBottom": "12px"})


def layout(**kwargs):
    return html.Div([
        hero_section(
            label="LOGIN",
            headline="Welcome back.",
            subtext="Sign in to see your own data and manage settings.",
            icon=False,
        ),
        html.Div([
            html.Div([
                html.H3("Sign in", style={
                    "fontSize": "18px", "margin": "0 0 16px 0",
                    "color": TEXT_PRIMARY,
                }),
                _form_input("login-username", "Username",
                             placeholder="you"),
                _form_input("login-password", "Password", type_="password",
                             placeholder="••••••••"),
                html.Button(
                    "Sign in", id="login-submit", n_clicks=0,
                    className="btn-accent",
                    style={"padding": "10px 24px", "fontSize": "13px",
                           "width": "100%"},
                ),
                html.Div(id="login-status", style={
                    "marginTop": "10px", "fontSize": "13px",
                    "color": TEXT_MUTED, "minHeight": "18px",
                }),
                html.P([
                    "Don't have an account? ",
                    dcc.Link("Sign up with an invite code",
                             href="/signup", style={"color": "var(--accent)"}),
                    ".",
                ], style={
                    "marginTop": "16px", "fontSize": "13px",
                    "color": TEXT_MUTED,
                }),
            ], style={
                "backgroundColor": BG_CARD, "border": f"1px solid {BORDER}",
                "padding": "28px", "maxWidth": "380px", "margin": "40px auto",
            }),
        ], style={"padding": "0 24px"}),
        footer(),
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
