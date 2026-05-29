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

# Data viz palette — "sea-green + earth" (legible on cream)
ACCENT_SLATE = "#5f8aa8"    # dusty blue (secondary)
ACCENT_AMBER = "#d4a83f"    # goldenrod (tertiary)
TERRACOTTA = "#cc7a4d"      # warm clay
PLUM = "#9a6f95"            # muted plum
SAGE = "#7ba05f"            # soft sage green

# Semantic high-intensity / warning — deep rust
ACCENT_RED = "#a9573f"

# Pre-computed gradient variants (60% / 40% opacity as solid-looking colors)
ACCENT_60 = _hex_to_rgba(ACCENT, 0.6)
SLATE_60 = _hex_to_rgba(ACCENT_SLATE, 0.6)
SLATE_40 = _hex_to_rgba(ACCENT_SLATE, 0.4)
AMBER_60 = _hex_to_rgba(ACCENT_AMBER, 0.6)

# Backgrounds (light theme — cool tones)
BG_LIGHT = "#F4F3EB"       # page background (cream — family)
BG_CARD = "#fbfaf4"         # card / chart background (paper)
BG_SURFACE = "#ece9dc"     # slightly tinted surface
BG_INPUT = "#ece9dc"

# Text
TEXT_PRIMARY = "#1a1d1a"    # ink (family)
TEXT_SECONDARY = "#384039"  # muted green-gray
TEXT_MUTED = "#7e8a83"      # soft sage gray

# Border
BORDER = "#cdd0c3"          # warm hairline

# Fonts
FONT_SANS = "Inter, -apple-system, sans-serif"
FONT_MONO = "'IBM Plex Mono', monospace"

# ---------------------------------------------------------------------------
# Data viz color mappings — all derived from the base colors
# ---------------------------------------------------------------------------

SERIES_COLORS = [ACCENT, TERRACOTTA, ACCENT_AMBER, ACCENT_SLATE, PLUM, SAGE]

LIFT_COLORS = {
    "bench": ACCENT,            # sea-green
    "squat": ACCENT_SLATE,      # dusty blue
    "deadlift": TERRACOTTA,     # clay
    "ohp": PLUM,                # plum
}

RUN_TYPE_COLORS = {
    "race": TERRACOTTA,         # clay
    "long": ACCENT_SLATE,       # dusty blue
    "moderate": ACCENT_AMBER,   # goldenrod
    "easy": SAGE,               # sage
}

FATIGUE_COLORS = {
    "Fresh": SAGE,
    "Normal": TEXT_MUTED,
    "Fatigued": ACCENT_AMBER,
    "Heavy Load": ACCENT_RED,
}

PHASE_COLORS = {
    "build1": ACCENT_SLATE,
    "build2": ACCENT,
    "taper": ACCENT_AMBER,
    "race": TERRACOTTA,
}

WORKOUT_TYPE_COLORS = {
    "lift": ACCENT,
    "run": ACCENT_SLATE,
    "rest": TEXT_MUTED,
    "obstacle": ACCENT_AMBER,
    "mobility": SAGE,
}

# HR zones — cool -> warm intensity ramp
HR_ZONE_COLORS = {
    1: SAGE,            # Recovery
    2: ACCENT,          # Easy (sea-green)
    3: ACCENT_AMBER,    # Moderate (goldenrod)
    4: TERRACOTTA,      # Threshold (clay)
    5: ACCENT_RED,      # Max (rust)
}
HR_ZONE_LABELS = ["Z1 Recovery", "Z2 Easy", "Z3 Moderate", "Z4 Threshold", "Z5 Max"]

ACTIVITY_TYPE_COLORS = {
    "Run": ACCENT,
    "Weight Training": TERRACOTTA,
    "Walk": SAGE,
    "Hike": SAGE,
    "Ride": ACCENT_SLATE,
    "Swim": ACCENT_SLATE,
    "Yoga": PLUM,
}

GRIDLINE = "#dfdfd2"
AXIS_COLOR = "#cdd0c3"

# ---------------------------------------------------------------------------
# Dark mode overrides — MERON navy palette
# ---------------------------------------------------------------------------

DARK_COLORS = {
    "bg": "#0e1411",
    "bg_card": "#141b17",
    "bg_light": "#141b17",
    "text_primary": "#e9efe8",
    "text_secondary": "#7e8a80",
    "text_muted": "#5e6b63",
    "border": "#313a33",
    "gridline": "#222b26",
}

# ---------------------------------------------------------------------------
# Backwards-compat aliases (old names → new palette)
# ---------------------------------------------------------------------------
STRAVA_ORANGE = ACCENT
ACCENT_TEAL = ACCENT_SLATE
ACCENT_GREEN = ACCENT_SLATE      # sage-like uses now map to blue
ACCENT_YELLOW = ACCENT_AMBER
ACCENT_PURPLE = ACCENT_AMBER     # violet uses now map to gold
