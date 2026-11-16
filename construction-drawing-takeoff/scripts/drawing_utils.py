"""Shared helpers: units, scales and dimension-text parsing."""
from __future__ import annotations

import json
import math
import re
from typing import Optional

PT_TO_MM = 25.4 / 72.0  # 1 PDF point = 0.352777... mm on paper

COMMON_SCALES = [1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500,
                 750, 1000, 1250, 1500, 2000, 2500, 5000]

# Imperial architectural scales expressed as 1:N (e.g. 1/4" = 1'-0" -> 1:48)
IMPERIAL_SCALES = {48: '1/4" = 1\'-0"', 96: '1/8" = 1\'-0"', 24: '1/2" = 1\'-0"',
                   192: '1/16" = 1\'-0"', 16: '3/4" = 1\'-0"', 12: '1" = 1\'-0"', 64: '3/16" = 1\'-0"',
                   32: '3/8" = 1\'-0"', 120: '1" = 10\'', 240: '1" = 20\'', 360: '1" = 30\'',
                   480: '1" = 40\'', 600: '1" = 50\'', 1200: '1" = 100\''}

LENGTH_TO_M = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
               "in": 0.0254, "ft": 0.3048, "yd": 0.9144}

# DXF $INSUNITS codes -> unit name
INSUNITS = {0: None, 1: "in", 2: "ft", 3: "mi", 4: "mm", 5: "cm", 6: "m", 7: "km",
            8: "microinch", 9: "mil", 10: "yd", 14: "dm"}


def parse_scale(text: str) -> float:
    """'1:100' / '1/100' / '100' -> 100.0"""
    t = text.strip().replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)[:/](\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(2)) / float(m.group(1))
    return float(t)


def snap_scale(denominator: float, tol: float = 0.015) -> Optional[int]:
    """Snap a computed scale denominator to the nearest standard scale if within tol."""
    for s in COMMON_SCALES + list(IMPERIAL_SCALES):
        if abs(denominator - s) / s <= tol:
            return s
    return None


_FT_IN = re.compile(r"^(\d+)\s*'\s*-?\s*(\d+(?:\.\d+)?)?\s*(?:(\d+)/(\d+))?\s*\"?$")
_IN = re.compile(r"^(\d+(?:\.\d+)?)\s*\"$")
_METRIC = re.compile(r"^(\d{1,3}(?:[ ,]\d{3})+|\d+)(?:\.(\d+))?\s*(mm|cm|m)?$", re.I)


def parse_dimension_text(text: str):
    """Parse a dimension string into (value, unit_hint).

    Returns value in the drawing's own number (e.g. 12450 for '12 450' or '12,450')
    and unit_hint in {'mm','cm','m','in', None}. Feet-inches are returned in inches.
    Returns None if the text doesn't look like a dimension.
    """
    t = text.strip().strip("()[]").replace(" ", " ").replace(" ", " ")
    t = re.sub(r"^(?:[A-Z]{1,3}\s*=\s*)", "", t)  # e.g. 'L=3600'
    if not t or len(t) > 16:
        return None
    m = _FT_IN.match(t)
    if m and "'" in t:
        ft = int(m.group(1))
        inch = float(m.group(2) or 0)
        if m.group(3) and m.group(4):
            inch += int(m.group(3)) / int(m.group(4))
        return ft * 12 + inch, "in"
    m = _IN.match(t)
    if m:
        return float(m.group(1)), "in"
    m = _METRIC.match(t)
    if m:
        whole = re.sub(r"[ ,]", "", m.group(1))
        val = float(whole + ("." + m.group(2) if m.group(2) else ""))
        unit = m.group(3).lower() if m.group(3) else None
        if val == 0:
            return None
        return val, unit
    return None


def fmt(x: float, nd: int = 3) -> str:
    return f"{x:,.{nd}f}"


def seg_length(p, q) -> float:
    return math.hypot(q[0] - p[0], q[1] - p[1])


def shoelace(points) -> float:
    a = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
