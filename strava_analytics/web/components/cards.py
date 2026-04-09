"""Reusable stat card components — Ozni-themed."""

import dash_bootstrap_components as dbc
from dash import html

from strava_analytics.web.theme import (
    ACCENT, ACCENT_SLATE, BG_CARD, BG_SURFACE, TEXT_PRIMARY,
    TEXT_SECONDARY, TEXT_MUTED, FONT_MONO, BORDER,
)


def stat_card(title: str, value: str, subtitle: str = "",
              color: str = ACCENT) -> dbc.Card:
    """Create a KPI stat card with top border accent."""
    return dbc.Card(
        dbc.CardBody([
            html.P(title, className="stat-label"),
            html.H3(value, className="stat-value",
                     style={"color": color}),
            html.P(subtitle, className="stat-subtitle") if subtitle else None,
        ]),
        className="stat-card",
        style={"borderTop": f"2px solid {color}"},
    )


def stat_card_row(cards: list[dbc.Card]) -> dbc.Row:
    """Wrap stat cards in a responsive row."""
    n = len(cards)
    width = max(2, 12 // n)
    return dbc.Row(
        [dbc.Col(card, xs=6, md=width) for card in cards],
        className="g-3 mb-4",
    )


def container_card(title: str, children, accent_color: str = BORDER) -> html.Div:
    """Wrap content in a themed container — matches ozniai.com card pattern."""
    return html.Div([
        html.Div(title, className="container-label"),
        html.Div(children, style={"padding": "0"}),
    ], className="container-card",
       style={"borderTop": f"1.5px solid {accent_color}"})


def metric_cell(label: str, value: str, delta: str = "",
                delta_color: str = ACCENT_SLATE) -> html.Div:
    """Single metric in a grid — label on top, monospace value below."""
    children = [
        html.Div(label, className="metric-label"),
        html.Div(value, className="metric-value"),
    ]
    if delta:
        children.append(html.Div(delta, className="metric-delta",
                                  style={"color": delta_color}))
    return html.Div(children, className="metric-cell")


def metric_grid(cells: list) -> html.Div:
    """Grid of metric cells."""
    return html.Div(cells, className="metric-grid")


# ── Shared activity card helpers ──────────────────────────────────────

def stat_cell(label: str, val: str) -> html.Div:
    """Small stat cell for activity card summaries (monospace value)."""
    return html.Div([
        html.Div(label, style={
            "fontSize": "10px", "fontWeight": "500",
            "textTransform": "uppercase", "letterSpacing": "0.1em",
            "color": "var(--text-muted)",
        }),
        html.Div(val, style={
            "fontFamily": "var(--font-mono)",
            "fontSize": "14px", "fontWeight": "600",
            "color": "var(--text-primary)",
        }),
    ], style={"minWidth": "80px"})


def duration_str(seconds) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    import pandas as _pd
    if _pd.isna(seconds) or seconds <= 0:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def activity_type_badge(type_name: str, color: str) -> html.Span:
    """Coloured pill badge for activity type / run type."""
    return html.Span(
        type_name or "activity",
        style={
            "backgroundColor": color, "color": "white",
            "fontSize": "10px", "fontWeight": "600",
            "textTransform": "uppercase", "letterSpacing": "0.05em",
            "padding": "2px 8px", "marginLeft": "8px",
            "display": "inline-block",
        },
    )
