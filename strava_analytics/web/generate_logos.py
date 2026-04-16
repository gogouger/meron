#!/usr/bin/env python3
"""Generate SVG logos by tracing PNG originals with vtracer.

Requires: pip install vtracer
Run:      python3 strava_analytics/web/generate_logos.py
Output:   8 SVG files in strava_analytics/web/assets/
"""

from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

try:
    import vtracer
except ImportError:
    raise SystemExit("vtracer not installed. Run: pip install vtracer")

# ── Constants ────────────────────────────────────────────────────────

ASSETS = Path(__file__).parent / "assets"

BRAND = {
    "navy":  (10, 27, 51),     # #0A1B33
    "blue":  (13, 110, 253),   # #0D6EFD
    "red":   (255, 51, 48),    # #FF3330
    "white": (255, 255, 255),  # #FFFFFF
    "muted": (100, 116, 139),  # #64748B
}
BRAND_HEX = {
    "navy": "#0a1b33", "blue": "#0d6efd", "red": "#ff3330",
    "white": "#ffffff", "muted": "#64748b",
}

NAVY_LIGHT = "#0F2547"

# ── Helpers ──────────────────────────────────────────────────────────

def _color_dist(c1, c2):
    return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _snap_hex(hex_color, threshold=100):
    """Snap a hex color to the nearest brand color."""
    rgb = _hex_to_rgb(hex_color)
    best_name, best_dist = None, float("inf")
    for name, brand_rgb in BRAND.items():
        d = _color_dist(rgb, brand_rgb)
        if d < best_dist:
            best_dist = d
            best_name = name
    if best_dist < threshold:
        return BRAND_HEX[best_name]
    return hex_color


def _snap_pixels(img, palette=None, white_to_transparent=True):
    """Snap every pixel to the nearest brand color, removing anti-aliasing.

    If white_to_transparent, white pixels become transparent.
    """
    if palette is None:
        palette = list(BRAND.values())
    img = img.convert("RGBA")
    data = list(img.getdata())
    new_data = []
    for r, g, b, a in data:
        if a < 50:
            new_data.append((0, 0, 0, 0))
            continue
        best_color, best_dist = (r, g, b), float("inf")
        for pr, pg, pb in palette:
            d = ((r - pr)**2 + (g - pg)**2 + (b - pb)**2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_color = (pr, pg, pb)
        if white_to_transparent and best_color == BRAND["white"]:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(best_color + (255,))
    img.putdata(new_data)
    return img


def _remove_white_bg(img):
    """Remove white background via flood fill from corners.

    Only removes white pixels connected to the image edges,
    preserving interior white (like snow caps on mountains).
    """
    img = img.convert("RGBA")
    w, h = img.size
    pixels = img.load()

    # Flood fill from all edge pixels that are white
    visited = set()
    queue = []
    for x in range(w):
        for y in [0, h - 1]:
            queue.append((x, y))
    for y in range(h):
        for x in [0, w - 1]:
            queue.append((x, y))

    bg_pixels = set()
    while queue:
        x, y = queue.pop()
        if (x, y) in visited:
            continue
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        visited.add((x, y))
        r, g, b, a = pixels[x, y]
        if r > 220 and g > 220 and b > 220:
            bg_pixels.add((x, y))
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if (nx, ny) not in visited:
                    queue.append((nx, ny))

    # Set background pixels to transparent
    for x, y in bg_pixels:
        pixels[x, y] = (255, 255, 255, 0)

    return img


def _upscale(img, factor):
    w, h = img.size
    return img.resize((w * factor, h * factor), Image.NEAREST)


def _save_temp(img, suffix=".png"):
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    img.save(f.name)
    return Path(f.name)


def _trace(input_png, **kwargs):
    """Trace a PNG → SVG string using vtracer."""
    out = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
    out.close()
    params = dict(
        colormode="color",
        hierarchical="stacked",
        mode="spline",
        filter_speckle=4,
        color_precision=6,
        layer_difference=16,
        corner_threshold=60,
        length_threshold=4.0,
        max_iterations=10,
        splice_threshold=45,
        path_precision=8,
    )
    params.update(kwargs)
    vtracer.convert_image_to_svg_py(str(input_png), out.name, **params)
    svg_text = Path(out.name).read_text()
    Path(out.name).unlink()
    return svg_text


def _snap_svg_colors(svg_text, threshold=100):
    """Snap all fill colors in SVG to brand palette."""
    def repl(m):
        original = m.group(1)
        snapped = _snap_hex(original, threshold)
        return f'fill="{snapped}"'
    return re.sub(r'fill="(#[0-9a-fA-F]{6})"', repl, svg_text)


def _set_viewbox(svg_text, w, h):
    """Replace the viewBox and add width/height."""
    svg_text = re.sub(
        r'viewBox="[^"]*"',
        f'viewBox="0 0 {w} {h}"',
        svg_text,
    )
    # Remove any existing width/height
    svg_text = re.sub(r'\s+width="[^"]*"', '', svg_text)
    svg_text = re.sub(r'\s+height="[^"]*"', '', svg_text)
    return svg_text


def _remove_bg_paths(svg_text, bg_color_hex):
    """Remove paths whose fill matches the background color."""
    snapped_bg = _snap_hex(bg_color_hex, threshold=50)
    # Parse and filter
    lines = svg_text.split('\n')
    filtered = []
    for line in lines:
        # Skip path elements filled with the background color
        if '<path' in line and f'fill="{snapped_bg}"' in line:
            continue
        filtered.append(line)
    return '\n'.join(filtered)


# ── Font / text helpers ──────────────────────────────────────────────

FONT_STYLE = (
    '<style>\n'
    '  @import url(\'https://fonts.googleapis.com/css2?'
    'family=Montserrat:wght@700;800;900&amp;'
    'family=Inter:wght@400;500;600;700&amp;display=swap\');\n'
    '</style>\n'
)

def _wordmark(fill, x, y, sz, anchor="middle"):
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f"font-family=\"Montserrat, 'Arial Black', sans-serif\" "
        f'font-weight="900" font-size="{sz}" '
        f'letter-spacing="0.08em" fill="{fill}">MERON</text>\n'
    )

def _tagline(base, accent, x, y, sz, anchor="middle"):
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'font-family="Inter, sans-serif" font-weight="600" '
        f'font-size="{sz}" letter-spacing="0.15em" fill="{base}">'
        f"STRENGTH. "
        f'<tspan fill="{accent}" font-weight="700">ENDURANCE.</tspan>'
        f" ELEVATION.</text>\n"
    )


# ── Variant converters ───────────────────────────────────────────────

# Cache — trace the primary PNG once, reuse paths in multiple variants
_PRIMARY_CACHE = {}

def _trace_primary_full():
    """Trace the FULL primary PNG (icon + text) — highest quality source.

    Returns: dict with 'paths', 'orig_w', 'orig_h', 'scale'
    The paths are at coords (orig_w * scale, orig_h * scale).
    Cached since expensive and reused by icon, outline, primary.
    """
    if "result" in _PRIMARY_CACHE:
        return _PRIMARY_CACHE["result"]

    img = Image.open(ASSETS / "meron-logo-primary.png").convert("RGBA")
    orig_w, orig_h = img.size

    scale = 3
    img = img.resize((orig_w * scale, orig_h * scale), Image.LANCZOS)
    img = _remove_white_bg(img)
    img = _snap_pixels(img, white_to_transparent=False)

    tmp = _save_temp(img)
    svg = _trace(tmp, filter_speckle=scale * 4, color_precision=6,
                 layer_difference=16, hierarchical="stacked")
    svg = _snap_svg_colors(svg)
    tmp.unlink()

    paths = re.findall(r'<path[^/]*/>', svg)
    result = {
        "paths": paths,
        "orig_w": orig_w,
        "orig_h": orig_h,
        "scale": scale,
    }
    _PRIMARY_CACHE["result"] = result
    return result


def _path_bbox(path_d):
    """Rough bbox of an SVG path's numeric coordinates."""
    nums = re.findall(r'-?\d+\.?\d*', path_d)
    if len(nums) < 2:
        return None
    xs, ys = [], []
    for i in range(0, len(nums) - 1, 2):
        try:
            xs.append(float(nums[i]))
            ys.append(float(nums[i + 1]))
        except ValueError:
            continue
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


# Icon-only palette (no 'muted' — avoids anti-aliasing snapping to gray)
_ICON_PALETTE = [BRAND["navy"], BRAND["blue"], BRAND["red"], BRAND["white"]]
_ICON_BRAND_COLORS = {BRAND_HEX["navy"], BRAND_HEX["blue"],
                      BRAND_HEX["red"], BRAND_HEX["white"]}


def _keep_only_brand_colors(paths, allowed_hex_colors):
    """Drop paths whose fill isn't in the allowed set.

    Tidies up any remaining anti-aliasing fringe paths that didn't
    snap cleanly to a brand color.
    """
    kept = []
    for p in paths:
        m = re.search(r'fill="(#[0-9a-fA-F]{6})"', p)
        if m and m.group(1).lower() in {c.lower() for c in allowed_hex_colors}:
            kept.append(p)
    return kept


def _get_primary_icon_paths():
    """Get paths for just the icon area (y < 170) from a fresh trace.

    Uses the icon-only palette (no muted gray) so anti-aliasing between
    navy and white snaps cleanly to navy. Drops fringe paths post-trace.

    Returns: (paths, traced_w, traced_h, orig_w, orig_h)
    """
    if "icon_paths" in _PRIMARY_CACHE:
        return _PRIMARY_CACHE["icon_paths"]

    img = Image.open(ASSETS / "meron-logo-primary.png").convert("RGBA")
    orig_w, _ = img.size
    img = img.crop((0, 0, orig_w, 170))
    crop_w, crop_h = img.size

    scale = 3
    img = img.resize((crop_w * scale, crop_h * scale), Image.LANCZOS)
    img = _remove_white_bg(img)
    img = _snap_pixels(img, palette=_ICON_PALETTE, white_to_transparent=False)

    tmp = _save_temp(img)
    svg = _trace(tmp, filter_speckle=scale * 4, color_precision=6,
                 layer_difference=16, hierarchical="stacked")
    svg = _snap_svg_colors(svg)
    tmp.unlink()

    paths = re.findall(r'<path[^/]*/>', svg)
    # Drop any remaining non-brand fringe paths
    paths = _keep_only_brand_colors(paths, _ICON_BRAND_COLORS)
    result = (paths, crop_w * scale, crop_h * scale, crop_w, crop_h)
    _PRIMARY_CACHE["icon_paths"] = result
    return result


# ── Designed SVG primitives ──────────────────────────────────────────
# Clean, hand-designed geometry for icon/outline/app-icon variants.
# ViewBox: 200 x 160, with the icon content living in roughly
# x=20..180, y=10..130 and a heartbeat baseline at y=108.

# Mountain silhouette — sharp, dramatic multi-peak ridgeline
MOUNTAIN_POLY = [
    (25, 130),    # bottom-left base
    (50, 78),     # left shoulder
    (60, 55),     # left peak (secondary)
    (70, 78),     # valley
    (80, 42),     # tall secondary peak
    (90, 65),     # valley before main
    (98, 55),     # small ridge
    (110, 10),    # MAIN PEAK (tallest)
    (122, 48),    # descending
    (132, 28),    # right shoulder peak
    (142, 62),    # descending right
    (155, 88),    # lower right slope
    (175, 130),   # bottom-right base
]

# Snow caps — just the top ~35% of each peak
SNOW_LINE_Y = 60
SNOW_POLY = [
    (48, SNOW_LINE_Y),    # left snow line entry (aligned with left slope)
    (50, 78),
    (60, 55),             # left peak
    (70, 78),
    (80, 42),             # secondary peak
    (90, 65),
    (98, 55),
    (110, 10),            # main peak
    (122, 48),
    (132, 28),             # right shoulder
    (142, 62),
    (146, SNOW_LINE_Y),   # right snow line exit
]

# Short EKG heartbeat — contained within the mountain width (for icon-only)
HEARTBEAT_SHORT = [
    (42, 108),
    (70, 108),
    (76, 108),
    (82, 116),    # P-wave dip
    (88, 86),     # Q
    (94, 124),    # R spike down
    (100, 74),    # S spike up
    (106, 108),   # back to baseline
    (112, 108),
    (155, 108),
]

# Long EKG heartbeat — extends across full dumbbell width (for bg variants)
HEARTBEAT_LONG = [
    (10, 108),
    (70, 108),
    (76, 108),
    (82, 116),
    (88, 86),
    (94, 124),
    (100, 74),
    (106, 108),
    (112, 108),
    (190, 108),
]


def _pts(points):
    """Convert list of (x, y) tuples to SVG points string."""
    return " ".join(f"{x},{y}" for x, y in points)


# Icon viewBox dimensions (shared across primitive-based variants)
ICON_VB_W, ICON_VB_H = 200, 160

# Dumbbell geometry (in icon coord space) — used by outline and app-icon
DUMBBELL_BAR_Y = 108
DUMBBELL_PLATES = [
    # (x, y, w, h)
    (14, 92, 12, 32),     # left inner plate
    (4, 96, 6, 24),       # left outer plate
    (174, 92, 12, 32),    # right inner plate
    (190, 96, 6, 24),     # right outer plate
]
DUMBBELL_BAR = (8, DUMBBELL_BAR_Y, 192, DUMBBELL_BAR_Y)  # x1, y1, x2, y2


def convert_icon(name="meron-icon.svg"):
    """Icon variant — reuse primary's icon paths as-is.

    Uses the primary logo's high-res traced icon region directly.
    This ensures the heartbeat lines up perfectly with the mountain
    and uses the same color scheme (red with white outline).
    """
    paths, tw, th, ow, oh = _get_primary_icon_paths()

    icon_png = Image.open(ASSETS / "meron-icon.png")
    icon_w, icon_h = icon_png.size

    sx = icon_w / tw
    sy = icon_h / th

    svg_out = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {icon_w} {icon_h}">\n'
        f'<g transform="scale({sx:.6f},{sy:.6f})">\n'
    )
    for p in paths:
        svg_out += f'  {p}\n'
    svg_out += '</g>\n</svg>\n'

    (ASSETS / name).write_text(svg_out)
    return name


def convert_outline():
    """Outline variant — reuse primary's icon paths, flatten to navy silhouette.

    Takes the same traced paths as the icon variant, then recolors:
      red heartbeat → white (cutout through navy silhouette)
      white snow → white (preserved cutout)
      navy mountain / blue dumbbell → navy
      anti-aliasing fringes → navy
    """
    paths, tw, th, ow, oh = _get_primary_icon_paths()

    recolored = []
    for p in paths:
        low = p.lower()
        if f'fill="{BRAND_HEX["red"]}"' in low:
            p_out = re.sub(r'fill="#[0-9a-fA-F]{6}"',
                           f'fill="{BRAND_HEX["white"]}"', p)
        elif f'fill="{BRAND_HEX["white"]}"' in low:
            p_out = p
        else:
            p_out = re.sub(r'fill="#[0-9a-fA-F]{6}"',
                           f'fill="{BRAND_HEX["navy"]}"', p)
        recolored.append(p_out)

    outline_png = Image.open(ASSETS / "meron-logo-outline.png")
    ow_out, oh_out = outline_png.size
    sx = ow_out / tw
    sy = oh_out / th

    svg_out = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {ow_out} {oh_out}">\n'
        f'<g transform="scale({sx:.6f},{sy:.6f})">\n'
    )
    for p in recolored:
        svg_out += f'  {p}\n'
    svg_out += '</g>\n</svg>\n'

    (ASSETS / "meron-logo-outline.svg").write_text(svg_out)
    return "meron-logo-outline.svg"


def convert_primary():
    """Primary variant — use the full traced primary (icon + text together).

    Since we trace the entire PNG including the MERON text, the text
    matches the PNG exactly (no web-font rendering mismatch).
    """
    data = _trace_primary_full()
    paths, ow, oh, scale = data["paths"], data["orig_w"], data["orig_h"], data["scale"]

    svg_out = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {ow} {oh}">\n'
        f'<g transform="scale({1/scale:.6f})">\n'
    )
    for p in paths:
        svg_out += f'  {p}\n'
    svg_out += '</g>\n</svg>\n'

    (ASSETS / "meron-logo-primary.svg").write_text(svg_out)
    return "meron-logo-primary.svg"


def convert_horizontal():
    """Horizontal variant — trace the entire PNG including text.

    Since text is traced from the PNG itself, the result matches exactly.
    """
    img = Image.open(ASSETS / "meron-logo-horizontal.png").convert("RGBA")
    orig_w, orig_h = img.size

    scale = 3
    img = img.resize((orig_w * scale, orig_h * scale), Image.LANCZOS)
    img = _remove_white_bg(img)
    img = _snap_pixels(img, white_to_transparent=False)

    tmp = _save_temp(img)
    svg = _trace(tmp, filter_speckle=scale * 4, color_precision=6,
                 layer_difference=16, hierarchical="stacked")
    svg = _snap_svg_colors(svg)
    tmp.unlink()

    paths = re.findall(r'<path[^/]*/>', svg)

    svg_out = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {orig_w} {orig_h}">\n'
        f'<g transform="scale({1/scale:.6f})">\n'
    )
    for p in paths:
        svg_out += f'  {p}\n'
    svg_out += '</g>\n</svg>\n'

    (ASSETS / "meron-logo-horizontal.svg").write_text(svg_out)
    return "meron-logo-horizontal.svg"


def _trace_bg_variant(png_name, bg_color_hex, bg_snap_name):
    """Shared pipeline for dark-bg and red-bg variants.

    LANCZOS upscale → snap pixels → trace → replace bg with rect.
    """
    img = Image.open(ASSETS / png_name).convert("RGBA")
    w, h = img.size

    scale = 3
    img = img.resize((w * scale, h * scale), Image.LANCZOS)
    # Snap pixels — bg color becomes exact, icon elements clean up
    img = _snap_pixels(img, white_to_transparent=False)
    tmp = _save_temp(img)

    svg = _trace(tmp, filter_speckle=scale * 4, color_precision=6)
    svg = _snap_svg_colors(svg)
    tmp.unlink()

    paths = re.findall(r'<path[^/]*/>', svg)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">\n',
        f'<rect width="{w}" height="{h}" fill="{bg_color_hex}"/>\n',
        f'<g transform="scale({1/scale:.6f})">\n',
    ]
    for p in paths:
        # Skip bg-colored paths
        if f'fill="{bg_color_hex}"' in p:
            continue
        lines.append(f'  {p}\n')
    lines.append('</g>\n')
    lines.append('</svg>\n')
    return ''.join(lines), w, h


def _icon_primitives(mountain_color, snow_color, heartbeat_color,
                     dumbbell_color, include_snow=True, include_dumbbell=True):
    """Return a list of SVG element strings in correct z-order.

    Order: mountain fill → dumbbell → heartbeat → snow caps (on top).
    """
    parts = []
    parts.append(f'<polygon points="{_pts(MOUNTAIN_POLY)}" fill="{mountain_color}"/>')

    if include_dumbbell:
        x1, y1, x2, y2 = DUMBBELL_BAR
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{dumbbell_color}" stroke-width="4" stroke-linecap="round"/>'
        )
        for (x, y, w, h) in DUMBBELL_PLATES:
            parts.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" '
                f'fill="{dumbbell_color}"/>'
            )

    parts.append(
        f'<polyline points="{_pts(HEARTBEAT_LONG)}" fill="none" '
        f'stroke="{heartbeat_color}" stroke-width="5" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
    )

    if include_snow:
        parts.append(f'<polygon points="{_pts(SNOW_POLY)}" fill="{snow_color}"/>')

    return parts


def _build_bg_variant(bg_color, mountain_color, snow_color,
                      heartbeat_color, dumbbell_color, include_snow=True):
    """Build a landscape bg variant using clean primitives."""
    vb_w, vb_h = 480, 200
    # Fit icon into canvas with padding, centered
    PAD_Y = 20
    fit = (vb_h - 2 * PAD_Y) / ICON_VB_H
    scaled_w = ICON_VB_W * fit
    scaled_h = ICON_VB_H * fit
    ox = (vb_w - scaled_w) / 2
    oy = (vb_h - scaled_h) / 2

    parts = _icon_primitives(mountain_color, snow_color, heartbeat_color,
                             dumbbell_color, include_snow=include_snow)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}">\n',
        f'  <rect width="{vb_w}" height="{vb_h}" fill="{bg_color}"/>\n',
        f'  <g transform="translate({ox:.2f},{oy:.2f}) scale({fit:.4f})">\n',
    ]
    lines.extend(f'    {p}\n' for p in parts)
    lines.append('  </g>\n')
    lines.append('</svg>\n')
    return ''.join(lines)


def _recolor_icon_paths(paths, *, mountain, snow, heartbeat, dumbbell):
    """Recolor primary's icon paths for bg variants.

    Maps:
      navy (mountain) → mountain color
      blue (dumbbell) → dumbbell color
      red (heartbeat) → heartbeat color
      white (snow)    → snow color
    """
    out = []
    for p in paths:
        low = p.lower()
        if f'fill="{BRAND_HEX["navy"]}"' in low:
            out.append(re.sub(r'fill="#[0-9a-fA-F]{6}"', f'fill="{mountain}"', p))
        elif f'fill="{BRAND_HEX["blue"]}"' in low:
            out.append(re.sub(r'fill="#[0-9a-fA-F]{6}"', f'fill="{dumbbell}"', p))
        elif f'fill="{BRAND_HEX["red"]}"' in low:
            out.append(re.sub(r'fill="#[0-9a-fA-F]{6}"', f'fill="{heartbeat}"', p))
        elif f'fill="{BRAND_HEX["white"]}"' in low:
            out.append(re.sub(r'fill="#[fF]{6}"', f'fill="{snow}"', p))
    return out


def _build_bg_variant(bg_hex, mountain, snow, heartbeat, dumbbell, filename):
    """Wide landscape bg variant with the icon centered.

    Reuses primary's clean icon paths and recolors them per-variant.
    """
    paths, tw, th, _ow, _oh = _get_primary_icon_paths()
    recolored = _recolor_icon_paths(paths, mountain=mountain, snow=snow,
                                    heartbeat=heartbeat, dumbbell=dumbbell)

    # Canvas: landscape 512×164 (matches PNG aspect), icon centered
    VB_W, VB_H = 512, 164
    PAD_Y = 12
    fit = (VB_H - 2 * PAD_Y) / th
    scaled_w = tw * fit
    scaled_h = th * fit
    ox = (VB_W - scaled_w) / 2
    oy = (VB_H - scaled_h) / 2

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VB_W} {VB_H}">\n',
        f'<rect width="{VB_W}" height="{VB_H}" fill="{bg_hex}"/>\n',
        f'<g transform="translate({ox:.2f},{oy:.2f}) scale({fit:.6f})">\n',
    ]
    lines.extend(f'  {p}\n' for p in recolored)
    lines.append('</g>\n</svg>\n')

    (ASSETS / filename).write_text(''.join(lines))
    return filename


def convert_dark_bg():
    """Dark bg — primary's icon, recolored for navy background.

    White mountain + dumbbell, blue snow accent, red heartbeat.
    """
    return _build_bg_variant(
        bg_hex=BRAND_HEX["navy"],
        mountain=BRAND_HEX["white"],
        snow=BRAND_HEX["blue"],
        heartbeat=BRAND_HEX["red"],
        dumbbell=BRAND_HEX["white"],
        filename="meron-logo-dark-bg.svg",
    )


def convert_red_bg():
    """Red bg — trace the PNG's line-art directly (preserves element separation).

    The PNG is drawn as thin white strokes on red, so element detail
    (mountain ridgeline, heartbeat, dumbbell plates) comes through
    when traced as binary white-on-red.
    """
    img = Image.open(ASSETS / "meron-logo-red-bg.png").convert("RGBA")
    w, h = img.size

    # Binary threshold: white-ish pixels → opaque white, red bg → transparent
    data = list(img.getdata())
    new_data = []
    for r, g, b, a in data:
        # White has g and b both high; red bg has only high r
        if g > 150 and b > 150:
            new_data.append((255, 255, 255, 255))
        else:
            new_data.append((0, 0, 0, 0))
    img.putdata(new_data)

    scale = 4
    img = img.resize((w * scale, h * scale), Image.LANCZOS)
    # Re-threshold after LANCZOS softening
    data = list(img.getdata())
    new_data = []
    for r, g, b, a in data:
        if a > 128 and (r + g + b) / 3 > 128:
            new_data.append((255, 255, 255, 255))
        else:
            new_data.append((0, 0, 0, 0))
    img.putdata(new_data)

    tmp = _save_temp(img)
    svg = _trace(tmp, filter_speckle=scale * 4, color_precision=2,
                 mode="spline")
    tmp.unlink()

    # Force all paths to white (binary trace produces black; snap to white)
    paths = re.findall(r'<path[^/]*/>', svg)
    paths = [re.sub(r'fill="#[0-9a-fA-F]{6}"',
                    f'fill="{BRAND_HEX["white"]}"', p) for p in paths]

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">\n',
        f'<rect width="{w}" height="{h}" fill="{BRAND_HEX["red"]}"/>\n',
        f'<g transform="scale({1/scale:.6f})">\n',
    ]
    for p in paths:
        lines.append(f'  {p}\n')
    lines.append('</g>\n</svg>\n')

    (ASSETS / "meron-logo-red-bg.svg").write_text(''.join(lines))
    return "meron-logo-red-bg.svg"


def convert_app_icon():
    """App icon — primary's icon on a rounded navy gradient square.

    Same recoloring scheme as dark-bg (white mountain+dumbbell, blue snow,
    red heartbeat) on a 512x512 gradient background with rounded corners.
    """
    paths, tw, th, _ow, _oh = _get_primary_icon_paths()
    recolored = _recolor_icon_paths(
        paths,
        mountain=BRAND_HEX["white"],
        snow=BRAND_HEX["blue"],
        heartbeat=BRAND_HEX["red"],
        dumbbell=BRAND_HEX["white"],
    )

    VB = 512
    PAD = 60
    canvas = VB - 2 * PAD
    fit = min(canvas / tw, canvas / th)
    scaled_w = tw * fit
    scaled_h = th * fit
    ox = (VB - scaled_w) / 2
    oy = (VB - scaled_h) / 2

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VB} {VB}" '
        f'width="{VB}" height="{VB}">\n',
        '<defs>\n',
        '  <linearGradient id="bg-g" x1="0" y1="0" x2="0" y2="1">\n',
        f'    <stop offset="0%" stop-color="{NAVY_LIGHT}"/>\n',
        f'    <stop offset="100%" stop-color="{BRAND_HEX["navy"]}"/>\n',
        '  </linearGradient>\n',
        '</defs>\n',
        f'<rect width="{VB}" height="{VB}" rx="100" fill="url(#bg-g)"/>\n',
        f'<g transform="translate({ox:.2f},{oy:.2f}) scale({fit:.6f})">\n',
    ]
    lines.extend(f'  {p}\n' for p in recolored)
    lines.append('</g>\n</svg>\n')

    (ASSETS / "meron-app-icon.svg").write_text(''.join(lines))
    return "meron-app-icon.svg"


# ── Main ─────────────────────────────────────────────────────────────

def main():
    converters = [
        ("meron-icon.svg", lambda: convert_icon("meron-icon.svg")),
        ("meron-icon-simple.svg", lambda: convert_icon("meron-icon-simple.svg")),
        ("meron-logo-primary.svg", convert_primary),
        ("meron-logo-horizontal.svg", convert_horizontal),
        ("meron-logo-outline.svg", convert_outline),
        ("meron-logo-dark-bg.svg", convert_dark_bg),
        ("meron-logo-red-bg.svg", convert_red_bg),
        ("meron-app-icon.svg", convert_app_icon),
    ]

    print(f"Generating {len(converters)} SVG logos → {ASSETS}/\n")
    for name, convert in converters:
        try:
            result = convert()
            size = (ASSETS / name).stat().st_size
            print(f"  ✓ {name:30s} ({size:,} bytes)")
        except Exception as e:
            print(f"  ✗ {name:30s} ERROR: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
