"""Render a metal-bend *profile* (cross-section) to an inline SVG.

A profile is a small dict stored inside a line's ``specs_json`` under the
``profile`` key so it survives the quote -> invoice -> job order snapshot::

    {
        "start": 0,                       # initial heading in degrees (0 = east)
        "segments": [                     # walked in order
            {"len": 50,  "ang": 90, "dir": 1},   # 50mm, then bend 90 deg (CCW)
            {"len": 150, "ang": 0,  "dir": 1},   # 150mm, no further bend
        ],
    }

``ang``/``dir`` describe the bend applied *after* each segment (``dir`` = +1/-1
picks the turn direction). The same geometry is mirrored in JavaScript for the
live editor preview, so keep the two implementations in sync.
"""
import math

from django.utils.safestring import mark_safe


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def profile_points(profile):
    """Return ``(points, segments)`` in maths coordinates (y up).

    ``points`` is the ordered vertex list; ``segments`` is a list of
    ``(p1, p2, length)`` for the drawn (non-zero) segments.
    """
    profile = profile or {}
    heading = _num(profile.get('start'))
    x = y = 0.0
    points = [(x, y)]
    segments = []
    for seg in profile.get('segments') or []:
        length = _num(seg.get('len'))
        if length > 0:
            rad = math.radians(heading)
            nx = x + length * math.cos(rad)
            ny = y + length * math.sin(rad)
            points.append((nx, ny))
            segments.append(((x, y), (nx, ny), length))
            x, y = nx, ny
        direction = _num(seg.get('dir'), 1) or 1
        heading += direction * _num(seg.get('ang'))
    return points, segments


def has_profile(profile):
    return bool(profile) and any(
        _num(s.get('len')) > 0 for s in (profile.get('segments') or []))


def _fmt(value):
    """Trim trailing zeros: 3.5 -> '3.5', 11.0 -> '11'."""
    value = round(float(value), 2)
    return str(int(value)) if value == int(value) else str(value)


def profile_girth(profile):
    _points, segments = profile_points(profile)
    total = sum(length for _p1, _p2, length in segments)
    return int(total) if float(total) == int(total) else round(total, 2)


def girth_label(profile):
    girth = _fmt(profile_girth(profile))
    return f'{girth}"' if (profile or {}).get('unit') == 'in' else f'{girth} mm'


def build_profile_svg(profile, stroke='#0f172a',
                      show_labels=True, show_girth=True):
    """Return a self-contained ``<svg>`` string (auto-fit viewBox) or ''.

    Every dimension is proportional to the drawing size (which varies wildly
    between inch and mm profiles) so it renders identically at any scale; the
    viewBox handles the final fit to the container.
    """
    points, segments = profile_points(profile)
    if len(points) < 2:
        return ''

    flipped = [(px, -py) for px, py in points]          # y up -> SVG y down
    xs = [p[0] for p in flipped]
    ys = [p[1] for p in flipped]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    width = (maxx - minx) or 1.0
    height = (maxy - miny) or 1.0
    span = max(width, height)
    sw = span / 100.0
    fs = span / 12.0
    off = span * 0.09
    pad = span * 0.16

    path = ' '.join(
        f"{'M' if i == 0 else 'L'} {p[0]:.1f} {p[1]:.1f}"
        for i, p in enumerate(flipped))

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{minx - pad:.1f} {miny - pad:.1f} '
        f'{width + 2 * pad:.1f} {height + 2 * pad:.1f}" '
        'preserveAspectRatio="xMidYMid meet" '
        'style="width:100%;height:100%;display:block;">',
        f'<path d="{path}" fill="none" stroke="{stroke}" '
        f'stroke-width="{sw:.2f}" stroke-linejoin="round" stroke-linecap="round"/>',
    ]
    for end in (flipped[0], flipped[-1]):
        parts.append(
            f'<circle cx="{end[0]:.1f}" cy="{end[1]:.1f}" '
            f'r="{sw * 1.4:.2f}" fill="{stroke}"/>')
    if show_labels:
        for (p1, p2, length) in segments:
            ax, ay = p1[0], -p1[1]
            bx, by = p2[0], -p2[1]
            mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
            dx, dy = bx - ax, by - ay
            norm = math.hypot(dx, dy) or 1.0
            tx = mx + (-dy / norm) * off
            ty = my + (dx / norm) * off
            parts.append(
                f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{fs:.1f}" '
                'fill="#475569" text-anchor="middle" '
                'dominant-baseline="middle" '
                f'font-family="sans-serif">{_fmt(length)}</text>')
    if show_girth:
        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0
        r = span / 8.0
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.2f}" '
            f'fill="#ffffff" fill-opacity="0.82" stroke="{stroke}" '
            f'stroke-width="{sw:.2f}"/>')
        parts.append(
            f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="{fs * 1.1:.2f}" '
            f'fill="{stroke}" text-anchor="middle" dominant-baseline="central" '
            f'font-weight="bold" font-family="sans-serif">{_fmt(profile_girth(profile))}</text>')
    parts.append('</svg>')
    return mark_safe(''.join(parts))
