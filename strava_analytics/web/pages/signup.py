"""Signup page — invite-only account creation."""

from __future__ import annotations

import dash
from dash import Input, Output, State, clientside_callback, dcc, html

from strava_analytics.web.components.layout import footer, hero_section
from strava_analytics.web.theme import (
    BG_CARD, BORDER, FONT_MONO, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)


dash.register_page(__name__, path="/signup", name="Sign up")


def _input(id_: str, label: str, type_: str = "text",
           placeholder: str = "") -> html.Div:
    return html.Div([
        html.Label(label, style={
            "fontSize": "12px", "fontWeight": "600",
            "color": TEXT_SECONDARY, "marginBottom": "4px",
            "display": "block",
        }),
        dcc.Input(id=id_, type=type_, placeholder=placeholder,
                  style={"width": "100%", "fontFamily": FONT_MONO,
                         "fontSize": "13px", "padding": "8px 10px"}),
    ], style={"marginBottom": "12px"})


def layout(**kwargs):
    # The invite code may arrive as a query param: /signup?code=XXXX-XXXX
    prefill_code = (kwargs.get("code") or "").strip().upper()
    return html.Div([
        hero_section(
            label="SIGN UP",
            headline="Create your account.",
            subtext="Invite-only — paste the code your admin shared with you.",
            icon=False,
        ),
        html.Div([
            html.Div([
                html.H3("Sign up", style={
                    "fontSize": "18px", "margin": "0 0 16px 0",
                    "color": TEXT_PRIMARY,
                }),
                html.Div([
                    html.Label("Invite code", style={
                        "fontSize": "12px", "fontWeight": "600",
                        "color": TEXT_SECONDARY, "marginBottom": "4px",
                        "display": "block",
                    }),
                    dcc.Input(
                        id="signup-invite", type="text",
                        value=prefill_code, placeholder="ABCD-1234",
                        style={"width": "100%", "fontFamily": FONT_MONO,
                               "fontSize": "13px", "padding": "8px 10px"},
                    ),
                ], style={"marginBottom": "12px"}),
                _input("signup-username", "Username",
                        placeholder="3–64 chars · a-z, 0-9, _ -"),
                _input("signup-password", "Password", type_="password",
                        placeholder="at least 8 chars"),
                html.Button(
                    "Create account", id="signup-submit", n_clicks=0,
                    className="btn-accent",
                    style={"padding": "10px 24px", "fontSize": "13px",
                           "width": "100%"},
                ),
                html.Div(id="signup-status", style={
                    "marginTop": "10px", "fontSize": "13px",
                    "color": TEXT_MUTED, "minHeight": "18px",
                }),
                html.P([
                    "Already have an account? ",
                    dcc.Link("Sign in", href="/login",
                             style={"color": "var(--accent)"}),
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
