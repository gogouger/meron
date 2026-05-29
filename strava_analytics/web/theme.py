"""MERON brand theme for the Dash layout.

4-color palette: dark navy, blue, red, white.
Data viz tertiary: warm gold (functional, not brand).

  background: #f8f9fc (cool blue-white)
  foreground: #0A1B33 (dark navy)
  accent:     #1a8a77 (sea-green — unified with the ggouger.com family)
  blue:       #0D6EFD (MERON blue)
  gold:       #d4a84b (warm data viz tertiary)
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
# MERON brand colors
# ---------------------------------------------------------------------------

# Primary accent — sea-green (unified with the ggouger.com family)
ACCENT = "#1a8a77"
ACCENT_HOVER = "#16786a"

# Data viz accents — blue + warm gold
ACCENT_SLATE = "#0D6EFD"    # MERON blue (secondary)
ACCENT_AMBER = "#d4a84b"    # warm gold (tertiary, data viz only)

# Semantic danger/warning — distinct from brand red
ACCENT_RED = "#dc2626"

# Pre-computed gradient variants (60% / 40% opacity as solid-looking colors)
ACCENT_60 = _hex_to_rgba(ACCENT, 0.6)
SLATE_60 = _hex_to_rgba(ACCENT_SLATE, 0.6)
SLATE_40 = _hex_to_rgba(ACCENT_SLATE, 0.4)
AMBER_60 = _hex_to_rgba(ACCENT_AMBER, 0.6)

# Backgrounds (light theme — cool tones)
BG_LIGHT = "#f8f9fc"       # page background
BG_CARD = "#ffffff"         # card / chart background
BG_SURFACE = "#f0f2f5"     # slightly tinted surface
BG_INPUT = "#f0f2f5"

# Text
TEXT_PRIMARY = "#0A1B33"    # MERON dark navy
TEXT_SECONDARY = "#475569"  # cool slate gray
TEXT_MUTED = "#94A3B8"      # light cool slate

# Border
BORDER = "#E5E7EB"          # cool light border

# Fonts
FONT_SANS = "Inter, -apple-system, sans-serif"
FONT_MONO = "'IBM Plex Mono', monospace"

# ---------------------------------------------------------------------------
# Data viz color mappings — all derived from the base colors
# ---------------------------------------------------------------------------

SERIES_COLORS = [ACCENT, ACCENT_SLATE, ACCENT_AMBER, SLATE_60, AMBER_60]

LIFT_COLORS = {
    "bench": ACCENT,            # red — primary lift
    "squat": ACCENT_SLATE,      # blue
    "deadlift": ACCENT_AMBER,   # gold
    "ohp": SLATE_60,            # light blue
}

RUN_TYPE_COLORS = {
    "race": ACCENT,             # red
    "long": ACCENT_SLATE,       # blue
    "moderate": ACCENT_AMBER,   # gold
    "easy": SLATE_60,           # light blue
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

HR_ZONE_COLORS = {
    1: SLATE_60,        # Recovery
    2: ACCENT_SLATE,    # Easy
    3: ACCENT_AMBER,    # Moderate
    4: ACCENT,          # Threshold
    5: ACCENT_RED,      # Max
}
HR_ZONE_LABELS = ["Z1 Recovery", "Z2 Easy", "Z3 Moderate", "Z4 Threshold", "Z5 Max"]

ACTIVITY_TYPE_COLORS = {
    "Run": ACCENT,
    "Weight Training": ACCENT_AMBER,
    "Walk": SLATE_60,
    "Hike": SLATE_60,
    "Ride": ACCENT_SLATE,
    "Swim": ACCENT_SLATE,
    "Yoga": AMBER_60,
}

GRIDLINE = "#f0f2f5"
AXIS_COLOR = "#CBD5E1"

# ---------------------------------------------------------------------------
# Dark mode overrides — MERON navy palette
# ---------------------------------------------------------------------------

DARK_COLORS = {
    "bg": "#0A1B33",
    "bg_card": "#0F2547",
    "bg_light": "#0F2547",
    "text_primary": "#FFFFFF",
    "text_secondary": "#94A3B8",
    "text_muted": "#64748B",
    "border": "#1E3A5F",
    "gridline": "#1E3A5F",
}

# ---------------------------------------------------------------------------
# Backwards-compat aliases (old names → new palette)
# ---------------------------------------------------------------------------
STRAVA_ORANGE = ACCENT
ACCENT_TEAL = ACCENT_SLATE
ACCENT_GREEN = ACCENT_SLATE      # sage-like uses now map to blue
ACCENT_YELLOW = ACCENT_AMBER
ACCENT_PURPLE = ACCENT_AMBER     # violet uses now map to gold
