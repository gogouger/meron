"""Ozni AI brand-aligned theme for the Dash layout.

3-color palette: red (vivid accent), slate (cool neutral), amber (warm neutral).
Gradients via opacity variants when more distinction is needed.

  background: #fafaf9 (light stone white)
  foreground: #0c0a09 (near black)
  accent:     #ef3c4a (Ozni red — the only loud color)
  slate:      #64748b (cool gray-blue)
  amber:      #b49352 (warm muted gold)
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_rgba(hex_color: str, alpha: float = 0.3) -> str:
    """Convert hex color to rgba string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------------------
# Ozni brand colors (light theme — matching ozniai.com)
# ---------------------------------------------------------------------------

# Primary accent — Ozni red (the only vivid color)
ACCENT = "#ef3c4a"
ACCENT_HOVER = "#dc2f3c"

# Data viz accents — cool + warm
ACCENT_SLATE = "#5b9bd5"    # bright steel-blue (secondary)
ACCENT_AMBER = "#d4a84b"    # warm gold (tertiary)

# Semantic danger/warning — distinct from brand red
ACCENT_RED = "#dc2626"

# Pre-computed gradient variants (60% / 40% opacity as solid-looking colors)
ACCENT_60 = _hex_to_rgba(ACCENT, 0.6)
SLATE_60 = _hex_to_rgba(ACCENT_SLATE, 0.6)
SLATE_40 = _hex_to_rgba(ACCENT_SLATE, 0.4)
AMBER_60 = _hex_to_rgba(ACCENT_AMBER, 0.6)

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

# Fonts — matching ozniai.com exactly
FONT_SANS = "Inter, -apple-system, sans-serif"
FONT_MONO = "'IBM Plex Mono', monospace"

# ---------------------------------------------------------------------------
# Data viz color mappings — all derived from the 3 base colors
# ---------------------------------------------------------------------------

SERIES_COLORS = [ACCENT, ACCENT_SLATE, ACCENT_AMBER, SLATE_60, AMBER_60]

LIFT_COLORS = {
    "bench": ACCENT,            # red — primary lift
    "squat": ACCENT_SLATE,      # slate
    "deadlift": ACCENT_AMBER,   # amber
    "ohp": SLATE_60,            # light slate
}

RUN_TYPE_COLORS = {
    "race": ACCENT,             # red
    "long": ACCENT_SLATE,       # slate
    "moderate": ACCENT_AMBER,   # amber
    "easy": SLATE_60,           # light slate
}

FATIGUE_COLORS = {
    "Fresh": ACCENT_SLATE,
    "Normal": TEXT_MUTED,
    "Fatigued": ACCENT_AMBER,
    "Heavy Load": ACCENT_RED,
}

PHASE_COLORS = {
    "build1": ACCENT_SLATE,
    "build2": ACCENT,
    "taper": ACCENT_AMBER,
    "race": ACCENT_RED,
}

WORKOUT_TYPE_COLORS = {
    "lift": ACCENT,
    "run": ACCENT_SLATE,
    "rest": TEXT_MUTED,
    "obstacle": ACCENT_AMBER,
    "mobility": SLATE_60,
}

ACTIVITY_TYPE_COLORS = {
    "Run": ACCENT,
    "Weight Training": ACCENT_AMBER,
    "Walk": SLATE_60,
    "Hike": SLATE_60,
    "Ride": ACCENT_SLATE,
    "Swim": ACCENT_SLATE,
    "Yoga": AMBER_60,
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

# ---------------------------------------------------------------------------
# Backwards-compat aliases (old names → new palette)
# ---------------------------------------------------------------------------
STRAVA_ORANGE = ACCENT
ACCENT_TEAL = ACCENT_SLATE
ACCENT_GREEN = ACCENT_SLATE      # sage-like uses now map to slate
ACCENT_YELLOW = ACCENT_AMBER
ACCENT_PURPLE = ACCENT_AMBER     # violet uses now map to amber
