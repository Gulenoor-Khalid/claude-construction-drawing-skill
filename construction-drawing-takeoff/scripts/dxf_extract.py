#!/usr/bin/env python3
"""Exact take-off from a DXF drawing.

Usage examples:
    python dxf_extract.py plan.dxf
    python dxf_extract.py plan.dxf --layers "A-WALL*,A-DOOR*" --explode-blocks --csv takeoff.csv
    python dxf_extract.py plan.dxf --find "W-3" --out plan.json
    python dxf_extract.py plan.dxf --units mm        # if $INSUNITS is unset

Reports, per layer: total length of linework, area of closed polylines/circles, hatch area.
Also: block (symbol) counts with attributes, and every DIMENSION checked against its geometry,
so overridden dimension text is flagged.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawing_utils import INSUNITS, LENGTH_TO_M, parse_dimension_text, write_json  # noqa: E402

FLATTEN = 0.5  # max chord deviation in drawing units when flattening curves


def path_points(entity):
    from ezdxf import path as ezpath
    p = ezpath.make_path(entity)
    return [(v.x, v.y) for v in p.flattening(FLATTEN)]


def poly_len(pts) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def poly_area(pts) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def hatch_area(h) -> float:
    from ezdxf import path as ezpath
    try:
        paths = list(ezpath.from_hatch(h))
    except Exception:
        return 0.0
    areas, flags = [], []
    for i, p in enumerate(paths):
        pts = [(v.x, v.y) for v in p.flattening(FLATTEN)]
        areas.append(poly_area(pts) if len(pts) > 2 else 0.0)
        try:
            flags.append(h.paths[i].path_type_flags)
        except Exception:
            flags.append(0)
    if not areas:
        return 0.0
    ext = [a for a, f in zip(areas, flags) if f & 1]
    if ext:
        holes = [a for a, f in zip(areas, flags) if not f & 1]
        return max(sum(ext) - sum(holes), 0.0)
    biggest = max(areas)
    return max(biggest - (sum(areas) - biggest), 0.0)


def plain(text: str) -> str:
    try:
        from ezdxf.tools.text import plain_mtext
        return plain_mtext(text)
    except Exception:
        return text


def iter_entities(entities, explode: bool, via=None, depth: int = 0):
    """Yield (entity, via_block_name). With explode, recurse into block inserts
    (virtual entities are already transformed to world coordinates, incl. block scale)."""
    for e in entities:
        yield e, via
        if explode and e.dxftype() == "INSERT" and depth < 8:
            try:
                children = list(e.virtual_entities())
            except Exception:
                continue
            parent_layer = e.dxf.get("layer", "0")
            for ch in children:  # CAD rule: block content on layer 0 takes the insert's layer
                if ch.dxf.get("layer", "0") == "0":
                    ch.dxf.layer = parent_layer
            yield from iter_entities(children, True, via or e.dxf.name, depth + 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf")
    ap.add_argument("--layers", help="comma-separated layer patterns, e.g. 'A-WALL*,S-*' (case-insensitive)")
    ap.add_argument("--explode-blocks", action="store_true",
                    help="include geometry inside block inserts (walls/fixtures drawn as blocks or xref-bound)")
    ap.add_argument("--units", help="override drawing units if $INSUNITS is unset/wrong (mm, cm, m, in, ft)")
    ap.add_argument("--find", action="append", default=[], help="find TEXT/MTEXT/attribute containing this")
    ap.add_argument("--near", help="x,y[,radius] in drawing units: list individual edges (lines and polyline "
                                   "sides) near a point with their lengths, e.g. at a wall tag's position")
    ap.add_argument("--layout", default="Model", help="layout to read (default: Model)")
    ap.add_argument("--out", help="write JSON")
    ap.add_argument("--csv", help="write per-layer take-off CSV")
    args = ap.parse_args()

    import ezdxf
    doc = ezdxf.readfile(args.dxf)
    layout = doc.modelspace() if args.layout == "Model" else doc.layouts.get(args.layout)

    unit = args.units or INSUNITS.get(doc.header.get("$INSUNITS", 0))
    to_m = LENGTH_TO_M.get(unit) if unit else None
    patterns = [p.strip().lower() for p in args.layers.split(",")] if args.layers else None

    def layer_ok(name: str) -> bool:
        return not patterns or any(fnmatch.fnmatch(name.lower(), p) for p in patterns)

    layers = defaultdict(lambda: {"entities": Counter(), "length": 0.0, "closed_area": 0.0, "hatch_area": 0.0,
                                  "closed_shapes": 0})
    blocks = Counter()
    block_layers = defaultdict(Counter)
    block_attrs = defaultdict(list)
    dims, texts, edges = [], [], []
    dimlfac_header = doc.header.get("$DIMLFAC", 1.0)

    for e, via in iter_entities(layout, args.explode_blocks):
        t = e.dxftype()
        lay = e.dxf.get("layer", "0")
        if not layer_ok(lay):
            continue
        L = layers[lay]
        L["entities"][t] += 1
        try:
            if t == "LINE":
                s, en = e.dxf.start, e.dxf.end
                L["length"] += math.dist((s[0], s[1]), (en[0], en[1]))
                edges.append(((s[0], s[1]), (en[0], en[1]), lay, t))
            elif t in ("LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"):
                pts = path_points(e)
                closed = getattr(e, "closed", False) or getattr(e, "is_closed", False) or (
                    len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6)
                L["length"] += poly_len(pts) + (math.dist(pts[-1], pts[0]) if closed and pts and
                                                math.dist(pts[0], pts[-1]) > 1e-6 else 0)
                ring = pts + ([pts[0]] if closed and math.dist(pts[0], pts[-1]) > 1e-6 else [])
                edges.extend((ring[i], ring[i + 1], lay, t) for i in range(len(ring) - 1)
                             if math.dist(ring[i], ring[i + 1]) > 1e-9)
                if closed and len(pts) > 2:
                    L["closed_area"] += poly_area(pts)
                    L["closed_shapes"] += 1
            elif t == "CIRCLE":
                r = e.dxf.radius
                L["length"] += 2 * math.pi * r
                L["closed_area"] += math.pi * r * r
                L["closed_shapes"] += 1
            elif t == "ARC":
                span = (e.dxf.end_angle - e.dxf.start_angle) % 360 or 360
                L["length"] += e.dxf.radius * math.radians(span)
            elif t == "HATCH":
                L["hatch_area"] += hatch_area(e)
            elif t == "INSERT":
                name = e.dxf.name
                blocks[name] += 1
                block_layers[name][lay] += 1
                attrs = {a.dxf.tag: a.dxf.text for a in getattr(e, "attribs", [])}
                if attrs and len(block_attrs[name]) < 200:
                    block_attrs[name].append(attrs)
            elif t == "DIMENSION":
                try:
                    meas = e.get_measurement()
                    meas = float(meas) if not hasattr(meas, "x") else None
                except Exception:
                    meas = None
                try:
                    dimlfac = e.override().get("dimlfac", None)
                except Exception:
                    dimlfac = None
                if dimlfac is None:
                    try:
                        dimlfac = doc.dimstyles.get(e.dxf.get("dimstyle", "Standard")).dxf.get("dimlfac", 1.0)
                    except Exception:
                        dimlfac = dimlfac_header
                raw = e.dxf.get("text", "") or ""
                text = plain(raw).strip()
                shown = meas * dimlfac if meas is not None else None
                overridden = bool(text) and "<>" not in text
                flag = None
                if overridden and shown is not None:
                    parsed = parse_dimension_text(text)
                    if parsed is None:
                        flag = f"text override '{text}' hides the measured value {shown:.3f}"
                    elif abs(parsed[0] - shown) > max(0.001 * abs(shown), 0.5):  # beyond normal rounding
                        flag = f"text says {parsed[0]:g} but geometry measures {shown:.3f}"
                loc = e.dxf.get("defpoint", None)
                dims.append({"layer": lay, "measured": None if meas is None else round(meas, 4),
                             "dimlfac": dimlfac, "displayed_value": None if shown is None else round(shown, 4),
                             "text": text or "<>", "overridden": overridden, "flag": flag,
                             "location": None if loc is None else [round(loc[0], 2), round(loc[1], 2)],
                             "in_block": via})
            elif t in ("TEXT", "MTEXT", "ATTRIB"):
                s = e.plain_text() if t == "MTEXT" else e.dxf.get("text", "")
                ins = e.dxf.get("insert", None)
                texts.append({"layer": lay, "text": s,
                              "at": None if ins is None else [round(ins[0], 2), round(ins[1], 2)]})
        except Exception as exc:
            L["entities"][f"{t} (error: {type(exc).__name__})"] += 1

    # attributes on inserts (ATTRIB entities live on the INSERT, not in the layout)
    for e in layout.query("INSERT"):
        for a in getattr(e, "attribs", []):
            texts.append({"layer": a.dxf.get("layer", "0"), "text": a.dxf.text, "tag": a.dxf.tag,
                          "at": [round(a.dxf.insert[0], 2), round(a.dxf.insert[1], 2)]})

    rows = []
    for name, L in sorted(layers.items(), key=lambda kv: -kv[1]["length"]):
        row = {"layer": name, "entities": dict(L["entities"]), "closed_shapes": L["closed_shapes"],
               "length": round(L["length"], 4), "closed_area": round(L["closed_area"], 4),
               "hatch_area": round(L["hatch_area"], 4)}
        if to_m:
            row["length_m"] = round(L["length"] * to_m, 4)
            row["closed_area_m2"] = round(L["closed_area"] * to_m ** 2, 4)
            row["hatch_area_m2"] = round(L["hatch_area"] * to_m ** 2, 4)
        rows.append(row)

    flagged = [d for d in dims if d["flag"]]
    result = {
        "file": args.dxf, "units": unit or "UNSET", "units_source": "--units" if args.units else "$INSUNITS",
        "explode_blocks": args.explode_blocks, "layer_filter": args.layers,
        "layers": rows,
        "blocks": [{"name": n, "count": c, "by_layer": dict(block_layers[n]),
                    "attribute_samples": block_attrs[n][:20]} for n, c in blocks.most_common()],
        "dimensions": dims, "dimension_flags": flagged,
    }

    # ---- print summary
    print(f"\n== {args.dxf}")
    print(f"  Units: {unit or 'UNSET (pass --units after checking magnitudes)'}"
          + (" [from --units]" if args.units else ""))
    if not unit:
        print("  ! Units unknown: lengths below are raw drawing units.")
    print(f"\n  {'layer':<24} {'length':>14} {'closed_area':>16} {'hatch_area':>14}  entities")
    for r in rows[:40]:
        if to_m:
            print(f"  {r['layer'][:24]:<24} {r['length_m']:>12.3f} m {r['closed_area_m2']:>13.3f} m2 "
                  f"{r['hatch_area_m2']:>11.3f} m2  {sum(r['entities'].values())}")
        else:
            print(f"  {r['layer'][:24]:<24} {r['length']:>14.2f} {r['closed_area']:>16.2f} "
                  f"{r['hatch_area']:>14.2f}  {sum(r['entities'].values())}")
    if blocks:
        print("\n  Blocks (exact counts):")
        for n, c in blocks.most_common(30):
            print(f"    {c:>5} x {n}")
    if dims:
        print(f"\n  Dimensions: {len(dims)} found, {sum(d['overridden'] for d in dims)} with text override, "
              f"{len(flagged)} flagged")
        for d in flagged[:30]:
            print(f"    ! layer {d['layer']} at {d['location']}: {d['flag']}")

    if args.find:
        result["find"] = {}
        print("\n  Text search:")
        for q in args.find:
            hits = [t for t in texts if q.lower() in str(t["text"]).lower()]
            result["find"][q] = hits
            print(f"    '{q}': {len(hits)} hit(s)")
            for h in hits[:20]:
                print(f"       {h['text']!r} on {h['layer']} at {h['at']}")

    if args.near:
        v = [float(x) for x in args.near.split(",")]
        px, py, rad = v[0], v[1], (v[2] if len(v) > 2 else 1000.0)

        def dist(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            tt = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy)))
            return math.hypot(px - (a[0] + tt * dx), py - (a[1] + tt * dy))

        hits = sorted(((dist(a, b), a, b, lay, t) for a, b, lay, t in edges), key=lambda h: h[0])
        hits = [h for h in hits if h[0] <= rad][:25]
        result["near"] = [{"distance": round(d, 3), "length": round(math.dist(a, b), 4),
                           "length_m": round(math.dist(a, b) * to_m, 4) if to_m else None,
                           "from": [round(a[0], 3), round(a[1], 3)], "to": [round(b[0], 3), round(b[1], 3)],
                           "layer": lay, "entity": t} for d, a, b, lay, t in hits]
        print(f"\n  Edges within {rad:g} of ({px:g}, {py:g}):")
        for h in result["near"]:
            ln = f"{h['length_m']:.3f} m" if to_m else f"{h['length']:.3f}"
            print(f"    d={h['distance']:>9.1f}  len={ln:>12}  {h['layer']}/{h['entity']}  {h['from']} -> {h['to']}")

    if args.out:
        result["texts"] = texts
        write_json(args.out, result)
        print(f"\nSaved {args.out}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["layer", "units", "length", "closed_area", "hatch_area", "length_m", "closed_area_m2",
                        "hatch_area_m2", "entity_count"])
            for r in rows:
                w.writerow([r["layer"], unit or "UNSET", r["length"], r["closed_area"], r["hatch_area"],
                            r.get("length_m", ""), r.get("closed_area_m2", ""), r.get("hatch_area_m2", ""),
                            sum(r["entities"].values())])
        print(f"Saved {args.csv}")


if __name__ == "__main__":
    main()
