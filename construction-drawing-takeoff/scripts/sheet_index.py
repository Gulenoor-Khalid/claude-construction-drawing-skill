#!/usr/bin/env python3
"""Index a drawing set (and optionally combine it into one PDF) so sheets can be cross-referenced.

Usage:
    python sheet_index.py drawings/                      # every PDF in a folder
    python sheet_index.py A-101.pdf A-201.pdf S-101.pdf --combine combined_set.pdf --json index.json

For each page it reports: paper size, vector/raster, likely sheet number, title, and scales
found in the title-block area. With --combine it writes one PDF with a bookmark per sheet,
which gives Claude the whole coordinated set (plans, sections, schedules) in one file.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawing_utils import PT_TO_MM, write_json  # noqa: E402
from inspect_drawing import paper_name  # noqa: E402

SHEET_RE = re.compile(r"\b([A-Z]{1,3}[-_. ]?\d{2,4}(?:[.-]\d{1,3})?)\b")
SCALE_RE = re.compile(r"\b1\s*:\s*\d{1,5}\b|\b\d+/\d+\"\s*=\s*1'-0\"|\bNTS\b|NOT TO SCALE", re.I)


def page_info(page) -> dict:
    W, H = page.rect.width, page.rect.height
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"].strip()
                if t:
                    spans.append((t, s["size"], s["bbox"]))
    # title block: right 35% or bottom 25% of the sheet
    tb = [s for s in spans if s[2][0] > W * 0.65 or s[2][1] > H * 0.75]
    corner = [s for s in tb if s[2][0] > W * 0.6 and s[2][1] > H * 0.6] or tb

    sheet_no = None
    for t, size, _ in sorted(corner, key=lambda s: -s[1]):
        m = SHEET_RE.search(t)
        if m and not SCALE_RE.search(t):
            sheet_no = m.group(1)
            break
    scales = sorted({m.group(0).upper().replace(" ", "") for t, _, _ in spans for m in SCALE_RE.finditer(t)})
    title_parts = [t for t, size, _ in sorted(corner, key=lambda s: -s[1])
                   if len(t) > 3 and not SCALE_RE.search(t) and t != sheet_no and not re.fullmatch(r"[\d\W]+", t)][:2]

    import fitz
    n_vec = sum(len(d["items"]) for d in page.get_drawings())
    img = 0.0
    for i in page.get_image_info():
        r = fitz.Rect(i["bbox"]) & page.rect
        img += r.width * r.height
    kind = "RASTER" if n_vec < 20 and img > 0.5 * W * H else "VECTOR" if n_vec >= 20 else "SPARSE"
    return {"paper": paper_name(W * PT_TO_MM, H * PT_TO_MM), "kind": kind, "sheet": sheet_no,
            "title": " / ".join(title_parts), "scales": scales}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="PDF files or folders")
    ap.add_argument("--combine", help="write a single combined PDF with bookmarks")
    ap.add_argument("--json", help="write the index as JSON")
    args = ap.parse_args()

    import fitz
    files = []
    for p in args.inputs:
        files += sorted(glob.glob(os.path.join(p, "*.pdf"))) if os.path.isdir(p) else [p]
    if not files:
        sys.exit("No PDFs found.")

    index, out_doc, toc = [], fitz.open() if args.combine else None, []
    for path in files:
        doc = fitz.open(path)
        for page in doc:
            info = {"file": os.path.basename(path), "page": page.number + 1, **page_info(page)}
            index.append(info)
            if out_doc is not None:
                out_doc.insert_pdf(doc, from_page=page.number, to_page=page.number)
                label = info["sheet"] or f"{info['file']} p{info['page']}"
                toc.append([1, f"{label} {info['title']}".strip()[:120], len(out_doc)])

    print(f"\n| # | File | Page | Sheet | Title | Scales | Paper | Type |")
    print(f"|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(index, 1):
        print(f"| {i} | {r['file']} | {r['page']} | {r['sheet'] or '?'} | {r['title'] or '?'} | "
              f"{', '.join(r['scales']) or '-'} | {r['paper']} | {r['kind']} |")
    raster = [r for r in index if r["kind"] == "RASTER"]
    if raster:
        print(f"\n! {len(raster)} raster page(s): these cannot be measured, only read.")

    if out_doc is not None:
        out_doc.set_toc(toc)
        out_doc.save(args.combine, garbage=3, deflate=True)
        print(f"\nSaved combined set: {args.combine} ({len(out_doc)} pages, bookmarked)")
    if args.json:
        write_json(args.json, index)
        print(f"Saved {args.json}")


if __name__ == "__main__":
    main()
