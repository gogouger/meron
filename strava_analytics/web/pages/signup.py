"""Signup page — invite-only account creation."""

from __future__ import annotations

import dash
from dash import Input, Output, State, clientside_callback, dcc, html

from strava_analytics.web.theme import (
    BG_CARD, BORDER, FONT_MONO, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)


dash.register_page(__name__, path="/signup", name="Sign up")


def _input(id_: str, label: str, type_: str = "text",
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
            id=id_, type=type_, placeholder=placeholder, value=value,
            autoComplete=autocomplete or None,
            style={
                "width": "100%", "fontFamily": FONT_MONO,
                "fontSize": "14px", "padding": "10px 12px",
                "border": f"1px solid {BORDER}",
                "borderRadius": "4px", "backgroundColor": "transparent",
                "color": "inherit", "outline": "none",
                "boxSizing": "border-box",
            },
        ),
    ], style={"marginBottom": "16px"})


def layout(**kwargs):
    # The invite code may arrive as a query param: /signup?code=XXXX-XXXX
    prefill_code = (kwargs.get("code") or "").strip().upper()
    return html.Div([
        html.Div([
            html.Div([
                html.Img(src="/assets/meron-icon.svg", alt="MERON",
                         style={"width": "40px", "height": "40px",
                                "marginBottom": "16px", "opacity": "0.9"}),
                html.H1("Sign up", style={
                    "fontSize": "28px", "fontWeight": "700",
                    "margin": "0 0 8px 0", "color": TEXT_PRIMARY,
                    "letterSpacing": "-0.01em",
                }),
                html.P("Invite-only — paste the code your admin shared.",
                       style={"color": TEXT_MUTED, "margin": "0 0 28px 0",
                              "fontSize": "14px"}),
                _input("signup-invite", "Invite code",
                       placeholder="ABCD-1234", value=prefill_code),
                _input("signup-username", "Username",
                       placeholder="3–64 chars · a-z, 0-9, _ -",
                       autocomplete="username"),
                _input("signup-password", "Password", type_="password",
                       placeholder="at least 8 chars",
                       autocomplete="new-password"),
                html.Button(
                    "Create account", id="signup-submit", n_clicks=0,
                    className="btn-accent",
                    style={"padding": "12px 24px", "fontSize": "14px",
                           "fontWeight": "600", "width": "100%",
                           "marginTop": "4px", "cursor": "pointer"},
                ),
                html.Div(id="signup-status", style={
                    "marginTop": "14px", "fontSize": "13px",
                    "color": "var(--accent)", "minHeight": "18px",
                    "textAlign": "center",
                }),
                html.Div(
                    dcc.Link("Already have an account? Sign in",
                             href="/login",
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


clientside_callback(
    """
    async function(n_clicks, invite_code, username, password) {
        if (!n_clicks) return '';
        if (!invite_code || !username || !password) {
            return 'All fields required.';
        }
        try {
            const resp = await fetch('/api/auth/signup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({invite_code, username, password}),
            });
            const body = await resp.json();
            if (resp.ok) {
                window.location.href = '/';
                return 'Account created.';
            }
            return (body.error && body.error.message) || 'Signup failed.';
        } catch (e) {
            return 'Network error: ' + e.message;
        }
    }
    """,
    Output("signup-status", "children"),
    Input("signup-submit", "n_clicks"),
    State("signup-invite", "value"),
    State("signup-username", "value"),
    State("signup-password", "value"),
    prevent_initial_call=True,
)
