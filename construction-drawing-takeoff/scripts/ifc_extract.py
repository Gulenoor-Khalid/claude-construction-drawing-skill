#!/usr/bin/env python3
"""Quantities and counts from an IFC (BIM) model.

Usage examples:
    python ifc_extract.py model.ifc
    python ifc_extract.py model.ifc --classes IfcWall,IfcSlab,IfcDoor --out model.json
    python ifc_extract.py model.ifc --classes IfcDoor --elements-csv doors.csv

Reads base quantities (Qto_* / IfcElementQuantity) and converts them to SI units
(m, m2, m3). If a model has no quantity sets, the script says so: ask for a re-export
with "Export base quantities" enabled (Revit, ArchiCAD, Tekla all support it).
Requires: pip install ifcopenshell
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawing_utils import write_json  # noqa: E402

DEFAULT_CLASSES = ["IfcWall", "IfcSlab", "IfcColumn", "IfcBeam", "IfcDoor", "IfcWindow", "IfcStair",
                   "IfcRoof", "IfcCovering", "IfcSpace", "IfcFooting", "IfcPile", "IfcRailing",
                   "IfcCurtainWall", "IfcPlate", "IfcMember", "IfcFlowTerminal", "IfcFlowSegment"]

# Per-element dimensions: summing these is meaningless, so report a range instead
NON_ADDITIVE = {"Width", "Height", "Depth", "Thickness", "OverallWidth", "OverallHeight", "OverallDepth",
                "NominalWidth", "NominalHeight", "NominalThickness", "Span", "Slope", "Pitch",
                "CrossSectionArea", "OuterSurfaceArea"}

VALUE_ATTR = {"IfcQuantityLength": ("LengthValue", "LENGTHUNIT", "m"),
              "IfcQuantityArea": ("AreaValue", "AREAUNIT", "m2"),
              "IfcQuantityVolume": ("VolumeValue", "VOLUMEUNIT", "m3"),
              "IfcQuantityCount": ("CountValue", None, "nr"),
              "IfcQuantityWeight": ("WeightValue", "MASSUNIT", "kg"),
              "IfcQuantityTime": ("TimeValue", None, "s")}


def unit_scales(f):
    import ifcopenshell.util.unit as uu
    scales = {}
    for ut in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT", "MASSUNIT"):
        try:
            scales[ut] = uu.calculate_unit_scale(f, ut)
        except TypeError:  # older ifcopenshell: length only
            ls = uu.calculate_unit_scale(f)
            scales[ut] = {"LENGTHUNIT": ls, "AREAUNIT": ls ** 2, "VOLUMEUNIT": ls ** 3}.get(ut, 1.0)
        except Exception:
            scales[ut] = 1.0
    return scales


def element_quantities(e, scales):
    out = {}
    for rel in getattr(e, "IsDefinedBy", []) or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pdef = rel.RelatingPropertyDefinition
        if not pdef.is_a("IfcElementQuantity"):
            continue
        for q in pdef.Quantities:
            spec = VALUE_ATTR.get(q.is_a())
            if not spec:
                continue
            attr, ut, si = spec
            val = getattr(q, attr, None)
            if val is None:
                continue
            factor = scales.get(ut, 1.0) if ut else 1.0
            out[f"{q.Name} [{si}]"] = float(val) * factor
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ifc")
    ap.add_argument("--classes", help="comma-separated IFC classes (subtypes included). Default: common building elements")
    ap.add_argument("--all", action="store_true", help="every IfcElement and IfcSpace")
    ap.add_argument("--out", help="write JSON summary")
    ap.add_argument("--elements-csv", help="write one row per element with its quantities")
    args = ap.parse_args()

    try:
        import ifcopenshell
        import ifcopenshell.util.element as ue
    except ImportError:
        sys.exit("ifcopenshell is not installed: pip install ifcopenshell")

    f = ifcopenshell.open(args.ifc)
    scales = unit_scales(f)

    if args.all:
        elements = list(f.by_type("IfcElement")) + list(f.by_type("IfcSpace"))
    else:
        classes = [c.strip() for c in args.classes.split(",")] if args.classes else DEFAULT_CLASSES
        elements, seen = [], set()
        for c in classes:
            try:
                for e in f.by_type(c):
                    if e.id() not in seen:
                        seen.add(e.id())
                        elements.append(e)
            except RuntimeError:
                print(f"  (class {c} not in schema {f.schema}, skipped)")

    by_class = defaultdict(lambda: {"count": 0, "with_quantities": 0, "values": defaultdict(list),
                                    "by_storey": Counter(), "by_type": Counter()})
    rows = []
    for e in elements:
        cls = e.is_a()
        c = by_class[cls]
        c["count"] += 1
        storey = ue.get_container(e)
        storey_name = getattr(storey, "Name", None) or "-"
        etype = ue.get_type(e)
        type_name = getattr(etype, "Name", None) or getattr(e, "ObjectType", None) or "-"
        c["by_storey"][storey_name] += 1
        c["by_type"][type_name] += 1
        q = element_quantities(e, scales)
        if q:
            c["with_quantities"] += 1
        for k, v in q.items():
            c["values"][k].append(v)
        rows.append({"GlobalId": e.GlobalId, "class": cls, "name": e.Name, "type": type_name,
                     "storey": storey_name, **{k: round(v, 4) for k, v in q.items()}})

    summary = {}
    print(f"\n== {args.ifc}  (schema {f.schema}, length unit scale to m: {scales['LENGTHUNIT']})")
    any_q = False
    for cls, c in sorted(by_class.items(), key=lambda kv: -kv[1]["count"]):
        totals, ranges = {}, {}
        for k, vals in c["values"].items():
            if k.split(" [")[0] in NON_ADDITIVE:
                ranges[k] = {"min": round(min(vals), 4), "max": round(max(vals), 4), "n": len(vals)}
            else:
                totals[k] = round(sum(vals), 4)
        summary[cls] = {"count": c["count"], "with_quantities": c["with_quantities"],
                        "totals_SI": totals, "dimension_ranges_SI": ranges,
                        "by_storey": dict(c["by_storey"]), "by_type": dict(c["by_type"].most_common(50))}
        any_q = any_q or c["with_quantities"] > 0
        print(f"\n  {cls}: {c['count']} (quantities on {c['with_quantities']})")
        for k, v in sorted(totals.items()):
            print(f"     total {k:<30} {v:>14,.3f}")
        for k, r in sorted(ranges.items()):
            rng = f"{r['min']:,.3f}" if r["min"] == r["max"] else f"{r['min']:,.3f} - {r['max']:,.3f}"
            print(f"     {k:<36} {rng:>14}  (per element, not summed)")
        if len(c["by_storey"]) > 1:
            print("     by storey: " + ", ".join(f"{s}={n}" for s, n in c["by_storey"].most_common()))
        if len(c["by_type"]) > 1:
            print("     by type:   " + ", ".join(f"{t}={n}" for t, n in c["by_type"].most_common(8)))
    if elements and not any_q:
        print("\n  ! No base quantities in this model. Counts are exact; for areas/volumes ask for an IFC "
              "export with base quantities enabled.")

    if args.out:
        write_json(args.out, {"file": args.ifc, "schema": f.schema, "unit_scales_to_SI": scales,
                              "classes": summary})
        print(f"\nSaved {args.out}")
    if args.elements_csv:
        keys = ["GlobalId", "class", "name", "type", "storey"]
        extra = sorted({k for r in rows for k in r} - set(keys))
        with open(args.elements_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys + extra)
            w.writeheader()
            w.writerows(rows)
        print(f"Saved {args.elements_csv}")


if __name__ == "__main__":
    main()
