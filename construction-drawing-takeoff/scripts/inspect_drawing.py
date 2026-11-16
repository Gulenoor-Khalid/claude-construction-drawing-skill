#!/usr/bin/env python3
"""Triage drawing files: can they be measured exactly, or only read?

Usage:
    python inspect_drawing.py <file> [<file> ...] [--json out.json]

Supports PDF, DXF, DWG (detect only), IFC, and images.
For each file, prints a verdict:
    VECTOR   - real geometry, measurable
    RASTER   - pixels only (scan/image), NOT measurable exactly
    HYBRID   - vector content plus large embedded images (check which part you need)
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawing_utils import INSUNITS, PT_TO_MM, write_json  # noqa: E402

ISO_SIZES = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420),
             "A4": (210, 297), "ARCH D": (610, 914), "ARCH E": (914, 1219),
             "ANSI D": (559, 864), "ANSI E": (864, 1118)}


def paper_name(w_mm: float, h_mm: float) -> str:
    a, b = sorted((w_mm, h_mm))
    for name, (x, y) in ISO_SIZES.items():
        if abs(a - x) < 6 and abs(b - y) < 6:
            return name
    return f"{w_mm:.0f}x{h_mm:.0f} mm"


def inspect_pdf(path: str) -> dict:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    pages = []
    for page in doc:
        area = page.rect.width * page.rect.height
        drawings = page.get_drawings()
        n_items = sum(len(d["items"]) for d in drawings)
        text = page.get_text("text")
        n_chars = len(text.strip())
        img_cover = 0.0
        for info in page.get_image_info():
            r = fitz.Rect(info["bbox"]) & page.rect
            img_cover += r.width * r.height
        img_ratio = min(img_cover / area, 1.0) if area else 0
        layers = sorted({d.get("layer") for d in drawings if d.get("layer")})

        if n_items < 20 and img_ratio > 0.5:
            verdict = "RASTER"
            note = "Scanned/image page: no geometry. Values can only be read, not measured."
        elif img_ratio > 0.5:
            verdict = "HYBRID"
            note = "Vector content over a large image. Measure vectors only; image parts are unmeasurable."
        elif n_items >= 20:
            verdict = "VECTOR"
            note = "Real linework present: measurable once scale is confirmed."
        else:
            verdict = "SPARSE"
            note = "Very little geometry: possibly a text page, cover sheet or schedule."
        if verdict in ("VECTOR", "HYBRID") and n_chars == 0:
            note += (" No text layer: text was exported as line work (common with SHX fonts). Geometry is still "
                     "exact, but labels/dimension strings must be read from a render (pdf_extract.py --render).")
        if verdict in ("RASTER",) and n_chars > 0:
            note += " (Has a text layer, likely OCR: text is searchable but not reliable for dimensions.)"

        w_mm, h_mm = page.rect.width * PT_TO_MM, page.rect.height * PT_TO_MM
        pages.append({
            "page": page.number + 1,
            "paper": paper_name(w_mm, h_mm),
            "size_mm": [round(w_mm, 1), round(h_mm, 1)],
            "vector_items": n_items,
            "text_chars": n_chars,
            "image_coverage": round(img_ratio, 2),
            "pdf_layers": layers[:40],
            "verdict": verdict,
            "note": note,
        })
    ocgs = doc.get_ocgs() if hasattr(doc, "get_ocgs") else {}
    return {"file": path, "type": "PDF", "pages": pages,
            "optional_content_layers": [v.get("name") for v in ocgs.values()][:80]}


def inspect_dxf(path: str) -> dict:
    import ezdxf
    from collections import Counter

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    counts = Counter(e.dxftype() for e in msp)
    insunits = doc.header.get("$INSUNITS", 0)
    unit = INSUNITS.get(insunits)
    layouts = [l.name for l in doc.layouts if l.name != "Model"]
    return {
        "file": path, "type": "DXF", "dxf_version": doc.dxfversion,
        "units": unit or "UNSET (infer from magnitudes and say so)",
        "dimlfac_header_default": doc.header.get("$DIMLFAC", 1.0),
        "dimlfac_note": "header default only; dimension styles/overrides may differ (dxf_extract.py applies the real one per dimension)",
        "layers": len(doc.layers), "layer_names": [l.dxf.name for l in doc.layers][:80],
        "modelspace_entities": dict(counts.most_common()),
        "paperspace_layouts": layouts,
        "verdict": "VECTOR",
        "note": "Exact coordinates available. Use dxf_extract.py.",
    }


def inspect_ifc(path: str) -> dict:
    try:
        import ifcopenshell
    except ImportError:
        return {"file": path, "type": "IFC", "verdict": "UNKNOWN",
                "note": "Install ifcopenshell (pip install ifcopenshell) to read IFC."}
    from collections import Counter
    f = ifcopenshell.open(path)
    counts = Counter(e.is_a() for e in f.by_type("IfcElement"))
    has_qto = any(rel.RelatingPropertyDefinition.is_a("IfcElementQuantity")
                  for rel in f.by_type("IfcRelDefinesByProperties"))
    return {"file": path, "type": "IFC", "schema": f.schema,
            "elements": dict(counts.most_common()),
            "storeys": [s.Name for s in f.by_type("IfcBuildingStorey")],
            "has_base_quantities": has_qto,
            "verdict": "MODEL",
            "note": ("Base quantities present." if has_qto else
                     "No quantity sets found: re-export with 'Export base quantities' enabled for exact areas/volumes.")}


def inspect_file(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return inspect_pdf(path)
    if ext == ".dxf":
        return inspect_dxf(path)
    if ext == ".ifc":
        return inspect_ifc(path)
    if ext == ".dwg":
        return {"file": path, "type": "DWG", "verdict": "CONVERT",
                "note": "DWG is a closed format. Ask for DXF, or convert with ODA File Converter / "
                        "'Save As DXF' in AutoCAD, BricsCAD or DraftSight. See references/file-formats.md."}
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"):
        return {"file": path, "type": "IMAGE", "verdict": "RASTER",
                "note": "Image only: no geometry. Ask for vector PDF, DXF or IFC for exact values."}
    return {"file": path, "type": ext or "?", "verdict": "UNKNOWN", "note": "Unsupported file type."}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", help="write full results to this JSON file")
    args = ap.parse_args()

    results = []
    for p in args.files:
        try:
            r = inspect_file(p)
        except Exception as exc:  # keep going on other files
            r = {"file": p, "verdict": "ERROR", "note": f"{type(exc).__name__}: {exc}"}
        results.append(r)

        print(f"\n=== {p}")
        if r.get("type") == "PDF":
            for pg in r["pages"]:
                print(f"  page {pg['page']:>3}  {pg['paper']:<10} {pg['verdict']:<7} "
                      f"vector_items={pg['vector_items']:<6} text_chars={pg['text_chars']:<6} "
                      f"images={pg['image_coverage']:.0%}  {pg['note']}")
            if r.get("optional_content_layers"):
                print(f"  PDF layers: {', '.join(map(str, r['optional_content_layers'][:20]))}")
        else:
            for k, v in r.items():
                if k != "file":
                    print(f"  {k}: {v}")

    if args.json:
        write_json(args.json, results)
        print(f"\nSaved {args.json}")


if __name__ == "__main__":
    main()
