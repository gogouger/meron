"""Chat widget components — floating bubble + slide-up chat panel."""

from dash import html, dcc

from strava_analytics.web.theme import ACCENT, TEXT_MUTED


def chat_widget() -> html.Div:
    """Return the full chat widget (bubble + panel + stores).

    Add this to the global app layout so it appears on every page.
    """
    return html.Div([
        # Chat history store (session-persistent)
        dcc.Store(id="chat-history-store", data=[], storage_type="session"),

        # Floating chat bubble
        html.Button(
            html.Span("\U0001F4AC", style={"fontSize": "24px"}),
            id="chat-bubble-btn",
            className="chat-bubble",
            title="Ask about your data",
        ),

        # Chat panel
        html.Div([
            # Header
            html.Div([
                html.Span("Ask about your data", style={
                    "fontWeight": "600", "fontSize": "14px",
                }),
                html.Button("\u00d7", id="chat-close-btn", className="chat-close-btn"),
            ], className="chat-header"),

            # Message area
            html.Div(id="chat-messages", className="chat-messages"),

            # Input area
            html.Div([
                dcc.Input(
                    id="chat-input",
                    type="text",
                    placeholder="Ask anything about your training...",
                    className="chat-input",
                    debounce=False,
                    n_submit=0,
                ),
                html.Button(
                    "\u27A4",
                    id="chat-send-btn",
                    className="chat-send-btn",
                ),
            ], className="chat-input-area"),
        ], id="chat-panel", className="chat-panel"),
    ], id="chat-widget")
