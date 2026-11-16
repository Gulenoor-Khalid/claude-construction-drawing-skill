#!/usr/bin/env python3
"""Compare measured quantities against specification requirements.

Usage:
    python check_against_spec.py requirements.csv measurements.csv [--out compliance.md]

requirements.csv columns (header required; leave blanks where not applicable):
    item,min,max,unit,clause
    Corridor clear width,1200,,mm,Spec 4.2.1
    Slab thickness,200,250,mm,S-001 note 3
    Door D01 clear opening,850,,mm,Part M table 2
    Parking spaces,40,,nr,Planning cond. 7

measurements.csv columns:
    item,value,unit,source
    Corridor clear width,1.15,m,Measured: A-101 grid C-D
    Slab thickness,200,mm,Dimension text: S-201 section 2

Items are matched by name (case-insensitive). Units are converted within a family
(length mm/cm/m/in/ft, area mm2/m2/ft2, volume m3/l/ft3, count nr/no/ea/pcs).
"""
from __future__ import annotations

import argparse
import csv
import sys

TO_BASE = {
    # length -> m
    "mm": ("L", 0.001), "cm": ("L", 0.01), "m": ("L", 1.0), "in": ("L", 0.0254), "ft": ("L", 0.3048),
    # area -> m2
    "mm2": ("A", 1e-6), "cm2": ("A", 1e-4), "m2": ("A", 1.0), "ft2": ("A", 0.09290304), "sqft": ("A", 0.09290304),
    # volume -> m3
    "m3": ("V", 1.0), "l": ("V", 0.001), "ft3": ("V", 0.0283168), "cy": ("V", 0.764555),
    # count
    "nr": ("N", 1.0), "no": ("N", 1.0), "ea": ("N", 1.0), "pcs": ("N", 1.0), "": ("N", 1.0),
}


def norm_unit(u: str) -> str:
    u = (u or "").strip().lower().replace("²", "2").replace("³", "3").replace("^", "")
    return {"sq m": "m2", "sqm": "m2", "cu m": "m3", "nos": "no", "each": "ea"}.get(u, u)


def to_base(value: float, unit: str):
    u = norm_unit(unit)
    if u not in TO_BASE:
        raise ValueError(f"unknown unit '{unit}'")
    fam, k = TO_BASE[u]
    return fam, value * k


def num(s):
    s = (s or "").strip().replace(",", "")
    return float(s) if s else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("requirements")
    ap.add_argument("measurements")
    ap.add_argument("--out", help="write the report as Markdown")
    args = ap.parse_args()

    with open(args.requirements, newline="", encoding="utf-8-sig") as f:
        reqs = list(csv.DictReader(f))
    with open(args.measurements, newline="", encoding="utf-8-sig") as f:
        meas = {r["item"].strip().lower(): r for r in csv.DictReader(f)}

    lines = ["| Item | Required | Measured | Status | Margin | Source | Clause |",
             "|---|---|---|---|---|---|---|"]
    counts = {"PASS": 0, "FAIL": 0, "MISSING": 0, "ERROR": 0}
    for r in reqs:
        item = r["item"].strip()
        unit = r.get("unit", "")
        lo, hi = num(r.get("min")), num(r.get("max"))
        req_txt = (f"{lo:g}–{hi:g}" if lo is not None and hi is not None else
                   f"≥ {lo:g}" if lo is not None else f"≤ {hi:g}" if hi is not None else "?") + f" {unit}"
        m = meas.get(item.lower())
        if not m:
            counts["MISSING"] += 1
            lines.append(f"| {item} | {req_txt} | – | MISSING | – | – | {r.get('clause', '')} |")
            continue
        try:
            v = num(m["value"])
            fam_m, v_base = to_base(v, m.get("unit", ""))
            fam_r, _ = to_base(1.0, unit)
            if fam_m != fam_r:
                raise ValueError(f"unit mismatch ({m.get('unit')} vs {unit})")
            _, k = to_base(1.0, unit)
            v_req_units = v_base / k  # measured value expressed in the requirement's unit
            ok = (lo is None or v_req_units >= lo - 1e-9) and (hi is None or v_req_units <= hi + 1e-9)
            margins = []
            if lo is not None:
                margins.append(v_req_units - lo)
            if hi is not None:
                margins.append(hi - v_req_units)
            margin = min(margins) if margins else 0.0
            status = "PASS" if ok else "FAIL"
            counts[status] += 1
            lines.append(f"| {item} | {req_txt} | {v_req_units:,.3f} {unit} (given {m['value']} {m.get('unit', '')}) "
                         f"| **{status}** | {margin:+,.3f} {unit} | {m.get('source', '')} | {r.get('clause', '')} |")
        except Exception as exc:
            counts["ERROR"] += 1
            lines.append(f"| {item} | {req_txt} | {m.get('value')} {m.get('unit', '')} | ERROR | {exc} | "
                         f"{m.get('source', '')} | {r.get('clause', '')} |")

    extra = sorted(set(meas) - {r["item"].strip().lower() for r in reqs})
    summary = (f"**{counts['PASS']} pass, {counts['FAIL']} fail, {counts['MISSING']} missing"
               + (f", {counts['ERROR']} error" if counts["ERROR"] else "") + "**")
    report = "\n".join(["# Specification check", "", summary, ""] + lines)
    if extra:
        report += "\n\nMeasured but not in requirements: " + ", ".join(meas[k]["item"] for k in extra)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"\nSaved {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
