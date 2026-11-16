#!/usr/bin/env python3
"""Measure geometry in a vector PDF drawing.

Usage examples:
    # 1. Find the scale from the drawing's own dimension strings
    python pdf_extract.py plan.pdf --page 1 --calibrate

    # 2. Take-off at a known scale: lengths/areas grouped by layer, colour and line weight
    python pdf_extract.py plan.pdf --page 1 --scale 1:100 --out plan.json

    # 3. Limit to one viewport or area (PDF points, origin top-left, as printed by --find)
    python pdf_extract.py plan.pdf --page 1 --scale 1:100 --region 100,80,600,500

    # 4. Locate tags or labels
    python pdf_extract.py plan.pdf --page 1 --find "W-3" --find "D01"

Coordinates are PDF points (1 pt = 1/72 inch = 0.3528 mm on paper), origin top-left.
Real length = paper length x scale denominator.
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawing_utils import (PT_TO_MM, IMPERIAL_SCALES, parse_dimension_text, parse_scale,  # noqa: E402
                           seg_length, shoelace, snap_scale, write_json)


# --------------------------------------------------------------------------- geometry
def _hex(color) -> str:
    if not color:
        return "none"
    c = list(color) + [0, 0, 0]
    return "#" + "".join(f"{int(round(max(0, min(1, v)) * 255)):02x}" for v in c[:3])


def _bezier_len(p0, p1, p2, p3, n=16) -> float:
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return sum(seg_length(pts[i], pts[i + 1]) for i in range(n))


def extract_geometry(page):
    """Return (segments, curves, closed_shapes) from a PyMuPDF page."""
    segments, curves, shapes = [], [], []
    for pi, d in enumerate(page.get_drawings()):
        key = (d.get("layer") or "", _hex(d.get("color")), round(d.get("width") or 0, 2))
        fill = _hex(d.get("fill"))
        stroked = d.get("color") is not None
        chain = []
        chain_ok = True
        seg_start = len(segments)
        for item in d["items"]:
            op = item[0]
            if op == "l":
                p, q = (item[1].x, item[1].y), (item[2].x, item[2].y)
                segments.append({"p": p, "q": q, "len": seg_length(p, q), "group": key, "path": pi})
                if not chain:
                    chain.append(p)
                elif seg_length(chain[-1], p) > 0.01:
                    chain_ok = False
                chain.append(q)
            elif op == "re":
                r = item[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                for i in range(4):
                    a, b = pts[i], pts[(i + 1) % 4]
                    segments.append({"p": a, "q": b, "len": seg_length(a, b), "group": key, "path": pi})
                shapes.append({"points": pts, "area": abs(r.width * r.height), "group": key, "fill": fill})
            elif op == "qu":
                qd = item[1]
                pts = [(qd.ul.x, qd.ul.y), (qd.ur.x, qd.ur.y), (qd.lr.x, qd.lr.y), (qd.ll.x, qd.ll.y)]
                for i in range(4):
                    a, b = pts[i], pts[(i + 1) % 4]
                    segments.append({"p": a, "q": b, "len": seg_length(a, b), "group": key, "path": pi})
                shapes.append({"points": pts, "area": shoelace(pts), "group": key, "fill": fill})
            elif op == "c":
                p0, p1, p2, p3 = [(pt.x, pt.y) for pt in item[1:5]]
                curves.append({"len": _bezier_len(p0, p1, p2, p3), "group": key, "p": p0, "q": p3, "path": pi})
                chain_ok = False
        if chain_ok and len(chain) >= 4:
            closed = d.get("closePath") or seg_length(chain[0], chain[-1]) < 0.01
            if closed:
                pts = chain[:-1] if seg_length(chain[0], chain[-1]) < 0.01 else chain
                a = shoelace(pts)
                if a > 1.0:
                    shapes.append({"points": pts, "area": a, "group": key, "fill": fill})
        if not stroked:
            # Fill-only paths (hatches, solid fills) have area but no visible linework:
            # keep their shapes, drop their edges from length totals.
            del segments[seg_start:]
            curves[:] = [c for c in curves if c.get("path") != pi]
    return segments, curves, shapes


def in_region(pt, region) -> bool:
    x0, y0, x1, y1 = region
    return x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1


# --------------------------------------------------------------------------- text
def extract_text(page):
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1, 0))
            for s in line["spans"]:
                t = s["text"].strip()
                if t:
                    x0, y0, x1, y1 = s["bbox"]
                    spans.append({"text": t, "bbox": [round(v, 2) for v in s["bbox"]],
                                  "center": ((x0 + x1) / 2, (y0 + y1) / 2),
                                  "size": round(s["size"], 2), "dir": (dx, dy)})
    return spans


# --------------------------------------------------------------------------- calibration
def _angle(p, q) -> float:
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180.0


def match_dimension(span, segments, max_angle=3.0):
    """Find the dimension line that a dimension string belongs to.

    Returns {"len", "s0", "s1", "off", "angle"} (paper pt; s0/s1 = extent along the line,
    off = line offset, both in absolute page coordinates) or None.
    """
    cx, cy = span["center"]
    dx, dy = span["dir"]
    t_ang = math.degrees(math.atan2(dy, dx)) % 180.0
    x0, y0, x1, y1 = span["bbox"]
    size = span["size"]
    text_w = abs((x1 - x0) * dx) + abs((y1 - y0) * dy)  # extent along reading direction
    max_d = max(2.5 * size, 10.0)

    ux, uy = math.cos(math.radians(t_ang)), math.sin(math.radians(t_ang))
    nx, ny = -uy, ux
    cu, cn = cx * ux + cy * uy, cx * nx + cy * ny

    def res(lo, hi, off):
        return {"len": hi - lo, "s0": lo + cu, "s1": hi + cu, "off": off + cn, "angle": t_ang}

    cand = []
    for s in segments:
        if s["len"] < max(text_w * 0.9, 5):
            continue
        a = _angle(s["p"], s["q"])
        diff = min(abs(a - t_ang), 180 - abs(a - t_ang))
        if diff > max_angle:
            continue
        off = (s["p"][0] - cx) * nx + (s["p"][1] - cy) * ny
        if abs(off) > max_d:
            continue
        t1 = (s["p"][0] - cx) * ux + (s["p"][1] - cy) * uy
        t2 = (s["q"][0] - cx) * ux + (s["q"][1] - cy) * uy
        lo, hi = min(t1, t2), max(t1, t2)
        cand.append((abs(off), off, lo, hi, s))
    if not cand:
        return None

    # Nearest line that actually spans (or sits around) the text
    cand.sort(key=lambda c: c[0])
    for d0, off0, _, _, _ in cand:
        same = [c for c in cand if abs(c[1] - off0) < 0.8]
        containing = [c for c in same if c[2] <= 0 <= c[3]]
        if containing:
            best = max(containing, key=lambda c: c[3] - c[2])
            return res(best[2], best[3], off0)
        # text sits in a gap of the dimension line
        left = [c for c in same if c[3] <= 0]
        right = [c for c in same if c[2] >= 0]
        if left and right:
            l_ = max(left, key=lambda c: c[3])
            r_ = min(right, key=lambda c: c[2])
            if r_[2] - l_[3] <= text_w + 2 * size:
                return res(l_[2], r_[3], off0)
    return None


def calibrate(spans, segments):
    pairs = []
    for sp in spans:
        parsed = parse_dimension_text(sp["text"])
        if not parsed:
            continue
        value, unit = parsed
        m = match_dimension(sp, segments)
        if not m or m["len"] < 5:
            continue
        pairs.append({"text": sp["text"], "value": value, "unit_hint": unit,
                      "paper_pt": round(m["len"], 3), "ratio": value / m["len"],
                      "at": [round(sp["center"][0], 1), round(sp["center"][1], 1)],
                      "_line": m})
    if not pairs:
        return {"ok": False, "reason": "No dimension strings could be matched to dimension lines.",
                "pairs": []}

    # Group by unit hint so '12.45 m' and '12450' don't fight
    def norm(p):
        r = p["ratio"]
        if p["unit_hint"] == "m":
            return r * 1000.0
        if p["unit_hint"] == "cm":
            return r * 10.0
        return r
    for p in pairs:
        p["ratio_norm"] = norm(p)

    best, support = None, []
    for p in pairs:
        s = [q for q in pairs if abs(q["ratio_norm"] - p["ratio_norm"]) / p["ratio_norm"] <= 0.02]
        if len(s) > len(support):
            best, support = p, s
    ratio = statistics.median(q["ratio_norm"] for q in support)
    for p in pairs:
        dev = (p["ratio_norm"] - ratio) / ratio
        p["deviation"] = round(dev, 4)
        p["agrees"] = abs(dev) <= 0.02

    imperial = sum(1 for p in support if p["unit_hint"] == "in") > len(support) / 2
    plain = [p for p in support if p["unit_hint"] is None]
    small_decimals = plain and statistics.median(p["value"] for p in plain) < 100 and \
        any(p["value"] != int(p["value"]) for p in plain)

    if imperial:
        denom = ratio * 72.0
        units = "inches (feet-inches)"
    elif small_decimals:
        denom = ratio * 1000.0 / PT_TO_MM
        units = "m (unsuffixed decimals assumed metres)"
    else:
        denom = ratio / PT_TO_MM
        units = "mm"
    snapped = snap_scale(denom)
    n = len(pairs)
    agree = sum(p["agrees"] for p in pairs)
    # what each dimension line actually measures, in the dimension's own units
    for p in pairs:
        p["measured_value"] = round(p["paper_pt"] * ratio / ({"m": 1000.0, "cm": 10.0}.get(p["unit_hint"], 1.0)), 1)
    chains = check_chains(pairs)
    for p in pairs:
        p.pop("_line", None)
    confidence = "high" if agree >= 5 and agree / n >= 0.7 else "medium" if agree >= 3 else "low"
    return {
        "ok": True,
        "dimension_units": units,
        "scale_denominator_computed": round(denom, 2),
        "scale_snapped": snapped,
        "scale_label": (IMPERIAL_SCALES.get(snapped) if imperial and snapped else
                        f"1:{snapped}" if snapped else f"~1:{denom:.1f} (non-standard)"),
        "pairs_matched": n,
        "pairs_agreeing": agree,
        "confidence": confidence,
        "outliers": [p for p in pairs if not p["agrees"]],
        "chain_checks": chains,
        "pairs": pairs,
    }


def check_chains(pairs, tol_pt=1.5):
    """Check that each dimension chain adds up to the overall dimension spanning it.

    A chain = dimensions on the same line (same angle and offset) that touch end to end.
    An overall = a dimension on a parallel line whose extent matches the chain's extent.
    """
    rows = defaultdict(list)
    for p in pairs:
        L = p["_line"]
        key = (round(L["angle"]), round(L["off"] / tol_pt))
        rows[key].append(p)
    results = []
    for key, members in rows.items():
        members.sort(key=lambda p: p["_line"]["s0"])
        # split into touching runs
        runs, cur = [], [members[0]]
        for p in members[1:]:
            if abs(p["_line"]["s0"] - cur[-1]["_line"]["s1"]) <= tol_pt:
                cur.append(p)
            else:
                runs.append(cur)
                cur = [p]
        runs.append(cur)
        for run in runs:
            if len(run) < 2:
                continue
            s0, s1 = run[0]["_line"]["s0"], run[-1]["_line"]["s1"]
            for o in pairs:
                L = o["_line"]
                if o in run or round(L["angle"]) != key[0]:
                    continue
                if abs(L["s0"] - s0) <= tol_pt and abs(L["s1"] - s1) <= tol_pt:
                    total = sum(p["value"] for p in run)
                    ok = abs(total - o["value"]) <= max(0.001 * o["value"], 0.5)
                    results.append({"chain": [p["text"] for p in run], "chain_sum": round(total, 3),
                                    "overall": o["text"], "adds_up": ok,
                                    "at": o["at"]})
    return results


# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=1, help="1-based page number")
    ap.add_argument("--scale", help="drawing scale, e.g. 1:100 (or 1:48 for 1/4\"=1'-0\")")
    ap.add_argument("--calibrate", action="store_true", help="infer scale from dimension strings")
    ap.add_argument("--region", help="x0,y0,x1,y1 in PDF points: only geometry fully inside")
    ap.add_argument("--find", action="append", default=[], help="text to locate (repeatable)")
    ap.add_argument("--dump-text", action="store_true", help="include every text span in the JSON")
    ap.add_argument("--near", help="x,y[,radius] in PDF pt: list line segments near a point with their lengths "
                                   "(use with --render to pick a dimension line and calibrate by hand)")
    ap.add_argument("--render", help="save a PNG of the page (or --region) to look at, e.g. region.png")
    ap.add_argument("--dpi", type=int, default=200, help="resolution for --render (default 200)")
    ap.add_argument("--top", type=int, default=25, help="rows to print in the summary")
    ap.add_argument("--out", help="write full results to JSON")
    args = ap.parse_args()

    import fitz
    doc = fitz.open(args.pdf)
    if not 1 <= args.page <= len(doc):
        sys.exit(f"Page {args.page} out of range (1..{len(doc)})")
    page = doc[args.page - 1]

    segments, curves, shapes = extract_geometry(page)
    spans = extract_text(page)
    region = [float(v) for v in args.region.split(",")] if args.region else None
    if region:
        segments = [s for s in segments if in_region(s["p"], region) and in_region(s["q"], region)]
        curves = [c for c in curves if in_region(c["p"], region) and in_region(c["q"], region)]
        shapes = [s for s in shapes if all(in_region(p, region) for p in s["points"])]
        spans = [s for s in spans if in_region(s["center"], region)]

    result = {"file": args.pdf, "page": args.page, "region": region,
              "page_size_pt": [round(page.rect.width, 2), round(page.rect.height, 2)],
              "counts": {"segments": len(segments), "curves": len(curves),
                         "closed_shapes": len(shapes), "text_spans": len(spans)}}

    if not segments and not curves:
        print("No vector geometry found here. This page/region is probably a raster image: "
              "it cannot be measured. Run inspect_drawing.py to confirm.")
    if not spans and (segments or curves):
        print("Note: no text layer on this page (text exported as line work). Measure geometry here, and read "
              "labels/dimension strings from a render: --render view.png [--region ...]")

    if args.render:
        clip = fitz.Rect(*region) if region else page.rect
        pix = page.get_pixmap(dpi=args.dpi, clip=clip)
        pix.save(args.render)
        print(f"Rendered {args.render} ({pix.width}x{pix.height}px). Pixel -> PDF pt: "
              f"x_pt = {clip.x0:.1f} + px * {72 / args.dpi:.4f}, y_pt = {clip.y0:.1f} + py * {72 / args.dpi:.4f}")

    # ---- scale
    denom = None
    if args.calibrate:
        cal = calibrate(spans, segments)
        result["calibration"] = cal
        print("\n== Scale calibration from dimension strings")
        if cal["ok"]:
            print(f"  Scale: {cal['scale_label']}  (computed 1:{cal['scale_denominator_computed']}, "
                  f"dimension units: {cal['dimension_units']})")
            print(f"  Pairs agreeing: {cal['pairs_agreeing']}/{cal['pairs_matched']}  "
                  f"confidence: {cal['confidence'].upper()}")
            for o in cal["outliers"][:15]:
                print(f"  ! '{o['text']}' at {o['at']}: the line it labels measures {o['measured_value']:g} "
                      f"({o['deviation']:+.1%}). Overridden/wrong dimension, NTS, other viewport scale, or mis-match")
            for c in cal["chain_checks"]:
                mark = "ok" if c["adds_up"] else "!"
                print(f"  {mark} chain {' + '.join(c['chain'])} = {c['chain_sum']:g} vs overall {c['overall']}"
                      + ("" if c["adds_up"] else "  <- DOES NOT ADD UP"))
            denom = cal["scale_snapped"] or cal["scale_denominator_computed"]
        else:
            print("  " + cal["reason"] + " Provide --scale and verify against a known dimension.")
    if args.scale:
        denom = parse_scale(args.scale)
    result["scale_denominator_used"] = denom

    mm_per_pt = PT_TO_MM * denom if denom else None

    # ---- groups
    groups = defaultdict(lambda: {"segments": 0, "length_pt": 0.0, "curves": 0, "curve_length_pt": 0.0,
                                  "closed_shapes": 0, "area_pt2": 0.0})
    for s in segments:
        g = groups[s["group"]]
        g["segments"] += 1
        g["length_pt"] += s["len"]
    for c in curves:
        g = groups[c["group"]]
        g["curves"] += 1
        g["curve_length_pt"] += c["len"]
    for sh in shapes:
        g = groups[sh["group"]]
        g["closed_shapes"] += 1
        g["area_pt2"] += sh["area"]

    rows = []
    for (layer, color, width), g in groups.items():
        row = {"layer": layer or "-", "stroke": color, "width": width, **{k: round(v, 3) if isinstance(v, float) else v
                                                                           for k, v in g.items()}}
        if mm_per_pt:
            row["length_m"] = round((g["length_pt"] + g["curve_length_pt"]) * mm_per_pt / 1000, 3)
            row["closed_area_m2"] = round(g["area_pt2"] * (mm_per_pt / 1000) ** 2, 3)
        rows.append(row)
    rows.sort(key=lambda r: r["length_pt"] + r["curve_length_pt"], reverse=True)
    result["groups"] = rows

    big = sorted(shapes, key=lambda s: s["area"], reverse=True)[:60]
    result["largest_closed_shapes"] = [{
        "group": {"layer": s["group"][0] or "-", "stroke": s["group"][1], "width": s["group"][2]},
        "fill": s["fill"],
        "bbox": [round(min(p[0] for p in s["points"]), 1), round(min(p[1] for p in s["points"]), 1),
                 round(max(p[0] for p in s["points"]), 1), round(max(p[1] for p in s["points"]), 1)],
        "area_pt2": round(s["area"], 2),
        **({"area_m2": round(s["area"] * (mm_per_pt / 1000) ** 2, 3)} if mm_per_pt else {}),
    } for s in big]

    print(f"\n== Geometry on page {args.page}" + (f" in region {region}" if region else "") +
          f": {len(segments)} segments, {len(curves)} curves, {len(shapes)} closed shapes, {len(spans)} text spans")
    hdr = f"  {'layer':<18} {'stroke':<8} {'width':>5} {'segs':>6} {'paper_len_pt':>13}"
    hdr += f" {'real_len_m':>11} {'closed_area_m2':>15}" if mm_per_pt else ""
    print(hdr)
    for r in rows[:args.top]:
        line = (f"  {r['layer'][:18]:<18} {r['stroke']:<8} {r['width']:>5} {r['segments']:>6} "
                f"{r['length_pt'] + r['curve_length_pt']:>13.1f}")
        if mm_per_pt:
            line += f" {r['length_m']:>11.3f} {r['closed_area_m2']:>15.3f}"
        print(line)
    if len(rows) > args.top:
        print(f"  ... {len(rows) - args.top} more groups in JSON")
    if not mm_per_pt:
        print("  (No scale set: lengths are paper points. Use --calibrate or --scale.)")

    # ---- find
    if args.find:
        result["find"] = {}
        print("\n== Text search")
        for q in args.find:
            hits = [s for s in spans if q.lower() in s["text"].lower()]
            result["find"][q] = [{"text": h["text"], "bbox": h["bbox"]} for h in hits]
            print(f"  '{q}': {len(hits)} hit(s)")
            for h in hits[:20]:
                print(f"     {h['text']!r} at bbox {h['bbox']}")

    if args.near:
        vals = [float(v) for v in args.near.split(",")]
        px, py = vals[0], vals[1]
        rad = vals[2] if len(vals) > 2 else 20.0

        def dist_to_seg(s):
            (x1, y1), (x2, y2) = s["p"], s["q"]
            dx, dy = x2 - x1, y2 - y1
            t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
            return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

        near = sorted(((dist_to_seg(s), s) for s in segments), key=lambda t: t[0])
        near = [(d, s) for d, s in near if d <= rad][:25]
        result["near"] = []
        print(f"\n== Segments within {rad:g} pt of ({px:g}, {py:g})")
        for d, s in near:
            row = {"distance_pt": round(d, 2), "length_pt": round(s["len"], 3),
                   "p": [round(v, 2) for v in s["p"]], "q": [round(v, 2) for v in s["q"]],
                   "angle_deg": round(_angle(s["p"], s["q"]), 1),
                   "layer": s["group"][0] or "-", "stroke": s["group"][1]}
            if mm_per_pt:
                row["length_real_mm"] = round(s["len"] * mm_per_pt, 1)
            result["near"].append(row)
            print(f"  d={d:5.1f}  len={s['len']:8.2f} pt" +
                  (f" = {row['length_real_mm']:>10,.1f} mm" if mm_per_pt else "") +
                  f"  angle={row['angle_deg']:>5}  {row['layer']}/{row['stroke']}  {row['p']} -> {row['q']}")
        print("  Manual scale from a dimension line: 1:N with N = real_mm / (length_pt * 0.352778)")

    if args.dump_text:
        result["text"] = [{"text": s["text"], "bbox": s["bbox"], "size": s["size"]} for s in spans]

    if args.out:
        write_json(args.out, result)
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
