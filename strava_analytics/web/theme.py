"""Ozni AI brand-aligned theme for Plotly charts and Dash layout.

Color palette extracted from ozniai.com (light theme):
  background: #fafaf9 (light stone white)
  foreground: #0c0a09 (near black)
  accent:     #ef3c4a (Ozni red)
  muted:      #57534e (warm gray)
  subtle:     #a8a29e (light warm gray)
  border:     #e7e5e4 (light warm border)
  surface:    #ffffff (white cards)
"""

import plotly.graph_objects as go
import plotly.io as pio

# ---------------------------------------------------------------------------
# Ozni brand colors (light theme — matching ozniai.com)
# ---------------------------------------------------------------------------

# Primary accent — Ozni red
ACCENT = "#ef3c4a"
ACCENT_HOVER = "#dc2f3c"

# Backgrounds (light theme)
BG_LIGHT = "#fafaf9"       # page background
BG_CARD = "#ffffff"         # card / chart background
BG_SURFACE = "#f5f5f4"     # slightly tinted surface
BG_INPUT = "#f5f5f4"

# Text
TEXT_PRIMARY = "#0c0a09"    # near black
TEXT_SECONDARY = "#57534e"  # warm gray
TEXT_MUTED = "#a8a29e"      # subtle warm gray

# Border
BORDER = "#e7e5e4"          # light warm border

# Semantic accents for data viz
ACCENT_TEAL = "#0891b2"
ACCENT_GREEN = "#16a34a"
ACCENT_RED = "#dc2626"
ACCENT_YELLOW = "#ca8a04"
ACCENT_PURPLE = "#9333ea"

# Fonts — matching ozniai.com exactly
FONT_SANS = "Inter, -apple-system, sans-serif"
FONT_MONO = "'IBM Plex Mono', monospace"

# Chart series colors — accent first, then semantic
SERIES_COLORS = [
    ACCENT, ACCENT_TEAL, ACCENT_GREEN, ACCENT_YELLOW,
    ACCENT_PURPLE, "#ea580c", "#db2777", "#0891b2",
]

LIFT_COLORS = {
    "bench": ACCENT,
    "squat": ACCENT_TEAL,
    "deadlift": ACCENT_GREEN,
    "ohp": ACCENT_YELLOW,
}

RUN_TYPE_COLORS = {
    "race": ACCENT, "workout": "#ea580c", "long": ACCENT_TEAL,
    "moderate": ACCENT_YELLOW, "easy": ACCENT_GREEN,
    "short/easy": "#0284c7", "ruck": ACCENT_PURPLE,
}

FATIGUE_COLORS = {
    "Fresh": ACCENT_GREEN, "Normal": ACCENT_TEAL,
    "Fatigued": ACCENT_YELLOW, "Heavy Load": ACCENT_RED,
}

PHASE_COLORS = {
    "build1": ACCENT_TEAL, "build2": ACCENT,
    "taper": ACCENT_YELLOW, "race": ACCENT_RED,
}

WORKOUT_TYPE_COLORS = {
    "lift": ACCENT, "run": ACCENT_TEAL, "rest": TEXT_MUTED,
    "obstacle": ACCENT_PURPLE, "mobility": ACCENT_GREEN,
}

GRIDLINE = "#f5f5f4"
AXIS_COLOR = "#d6d3d1"

# ---------------------------------------------------------------------------
# Dark mode overrides — used via CSS custom properties
# ---------------------------------------------------------------------------

DARK_COLORS = {
    "bg": "#0c0a09",
    "bg_card": "#1c1917",
    "bg_light": "#1c1917",
    "text_primary": "#fafaf9",
    "text_secondary": "#a8a29e",
    "text_muted": "#78716c",
    "border": "#292524",
    "gridline": "#292524",
}

# Keep old names as aliases for backwards compat
STRAVA_ORANGE = ACCENT

# ---------------------------------------------------------------------------
# Plotly template (light theme)
# ---------------------------------------------------------------------------

PLOTLY_TEMPLATE = go.layout.Template(
    layout=go.Layout(
        # Transparent backgrounds — CSS controls the visual color for light/dark
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_SANS, color=TEXT_SECONDARY, size=13),
        title=dict(font=dict(size=15, color=TEXT_SECONDARY, family=FONT_SANS), x=0.02),
        xaxis=dict(
            gridcolor=GRIDLINE, linecolor=AXIS_COLOR,
            zerolinecolor=GRIDLINE,
            tickfont=dict(color=TEXT_MUTED, size=10, family=FONT_MONO),
        ),
        yaxis=dict(
            gridcolor=GRIDLINE, linecolor=AXIS_COLOR,
            zerolinecolor=GRIDLINE,
            tickfont=dict(color=TEXT_MUTED, size=10, family=FONT_MONO),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT_SECONDARY, size=11),
            borderwidth=0,
        ),
        colorway=SERIES_COLORS,
        hoverlabel=dict(
            bgcolor="rgba(0,0,0,0)", font_color=TEXT_PRIMARY,
            font_family=FONT_MONO, font_size=12,
            bordercolor=BORDER,
        ),
        margin=dict(l=50, r=20, t=40, b=40),
        dragmode="pan",
        clickmode="event",
    )
)

pio.templates["strava_dark"] = PLOTLY_TEMPLATE
pio.templates.default = "strava_dark"
