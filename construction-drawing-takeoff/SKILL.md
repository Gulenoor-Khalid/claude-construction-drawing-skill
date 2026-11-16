---
name: construction-drawing-takeoff
description: Extract exact quantities, lengths, areas, counts and dimensions from construction drawings by measuring the drawing geometry (vector PDF, DXF, IFC) instead of guessing from pixels, then cross-check dimension text against geometry and compare results against specifications. Use this skill whenever someone uploads or mentions architectural, structural or MEP drawings, floor plans, sections, sheets, CAD files, BIM models, take-offs, quantity surveying, BOQs, wall lengths, slab areas, door/window counts, "check this drawing against the spec", RFIs about dimensions, or asks any question whose answer depends on a measurement from a drawing, even if they don't say "take-off" and even if they only ask Claude to "read" or "look at" a plan.
---

# Construction drawing take-off

Most AI answers about drawings are wrong for one reason: the model reads the *text and pixels* on a sheet and guesses. A dimension string can be overridden, a detail can be "not to scale", and a scanned sheet has no geometry at all. This skill makes Claude measure the actual vectors, state where every number came from, and flag anything it could not verify.

The scripts in `scripts/` do the measuring. Your job is to pick the right path, run them, sanity-check the results like an experienced QS or engineer would, and report clearly.

## The core rule: measured vs. read

Every number you give the user must carry its source:

| Source | Meaning | Trust |
|---|---|---|
| **Measured** | Computed from vector geometry at a verified scale | High |
| **Model quantity** | Read from IFC base quantities / properties | High (if the model was exported with quantities) |
| **Dimension text** | The number written on the drawing | Medium: it can be overridden or wrong |
| **Read from image** | Taken from a raster/scanned sheet by eye | Low: say so, don't present it as exact |

Never blend these silently. If you could only read a value, say "read from the drawing, not measured". The whole point of this skill is that the user can trust the difference.

## Workflow

### 1. Triage the files first

```bash
python scripts/inspect_drawing.py <file> [<file> ...]
```

This tells you, per file and per page, whether real geometry exists:

- **Vector PDF**: lines and text are real objects, so they can be measured. Continue.
- **Raster / scanned PDF or image**: there is no geometry. Tell the user plainly that exact measurement is not possible from this file, give what you can read (labelled *Read from image*), and ask for a better file. `references/file-formats.md` has wording they can send to the designer.
- **DXF**: best for exact take-offs (real coordinates, layers, blocks, dimension entities).
- **DWG**: proprietary, not readable here. Ask for DXF, or tell them how to convert it (see `references/file-formats.md`).
- **IFC**: BIM model. Element counts and quantities come straight from the model.

If the user gave several sheets, build an index so you can cross-reference instead of treating each sheet in isolation:

```bash
python scripts/sheet_index.py <folder-or-pdfs> --combine combined_set.pdf
```

### 2. Lock the scale and units before measuring anything

A wrong scale makes every number wrong by the same factor, and it looks perfectly plausible. So:

- **DXF**: units come from `$INSUNITS`. If it's unset, infer from magnitudes (a 5 m wall reads 5000 in mm drawings) and say you inferred it.
- **IFC**: units come from the project; the script reports them.
- **PDF**: run calibration. It matches dimension strings to the dimension lines beside them and computes the scale from dozens of pairs:

  ```bash
  python scripts/pdf_extract.py plan.pdf --page 1 --calibrate
  ```

  It reports the scale (e.g. `1:100`), how many dimension pairs agree, and the outliers. If the user tells you the scale, pass `--scale 1:100` instead and still check it against at least one known dimension. Sheets with several viewports at different scales need `--region` per viewport (see `references/scale-and-units.md`).

  **PDFs with no text layer.** Many CAD exports draw text as line work (SHX fonts), so `inspect_drawing.py` reports "No text layer" and calibration finds nothing. The geometry is still exact, so combine your eyes with the vectors:
  1. `--render view.png --region ...` and look at the image to read a dimension string and see where its dimension line is (the script prints the pixel-to-point conversion).
  2. `--near x,y,radius` at that spot lists the line segments there with their exact paper lengths.
  3. Scale = dimension value ÷ (length_pt × 0.352778). Check it against a second dimension, then measure with `--scale`.
  Values you read from the render are *Dimension text*; lengths you compute from vectors are *Measured*.

If calibration is weak (few pairs, low agreement), say so and ask the user to confirm the scale rather than proceeding with false precision.

### 3. Extract

Pick the script for the format. Each writes a JSON file (and CSV where useful) and prints a summary.

```bash
# Vector PDF: lengths/areas grouped by layer, colour and line weight; text with positions
python scripts/pdf_extract.py plan.pdf --page 1 --scale 1:100 --out plan_page1.json
python scripts/pdf_extract.py plan.pdf --page 1 --scale 1:100 --region 100,80,600,500   # one viewport/area
python scripts/pdf_extract.py plan.pdf --page 1 --find "W-3"                             # locate a tag
python scripts/pdf_extract.py plan.pdf --page 1 --scale 1:100 --near 356,276,45          # exact lines near a point
python scripts/pdf_extract.py plan.pdf --page 1 --region 100,80,600,500 --render view.png # look at an area

# DXF: lengths and areas per layer, block counts with attributes, dimension checks
python scripts/dxf_extract.py plan.dxf --out plan_dxf.json --csv plan_takeoff.csv
python scripts/dxf_extract.py plan.dxf --layers "A-WALL*,S-COL*" --explode-blocks

# IFC: element counts, base quantities per class and storey
python scripts/ifc_extract.py model.ifc --classes IfcWall,IfcSlab,IfcDoor --out model.json
```

How to turn raw geometry into a quantity:

- **PDF groups**: in a vector PDF, walls, gridlines, hatching and furniture are usually separated by layer (if the PDF kept CAD layers) or by stroke colour/line weight. Look at the group table, identify which group is the element the user asked about (check a known element's length against its dimension), then use that group's totals. Explain the mapping you chose.
- **Wall lengths from double lines**: a wall drawn as two faces gives two lines per wall. Give the outside face, inside face and centreline (the average of the two faces), and say which wall owns the corners, because QSs measure to different conventions. For DXF, `dxf_extract.py --near x,y,radius` at a wall tag's position lists the individual wall sides with their lengths.
- **Single elements**: to measure one wall or one opening, `--find` its tag, then `--near` the tag's position to get the exact lines next to it (outer and inner faces show up as two parallel lengths).
- **Areas**: use closed polylines/hatches (DXF) or closed paths (PDF). Room areas from hatches/fills are usually the most reliable. A group's closed area adds up *every* closed shape in it, so nested outlines (outer and inner wall faces) are summed: subtract them where you need a net area (e.g. wall footprint = outer − inner).
- **Counts**: DXF block inserts (doors, fixtures, columns) are exact counts. In PDFs, count repeated tags or symbols via `--find` and say it's a text-based count.

### 4. Cross-check like an engineer

Before reporting, look for the problems a human checker would catch:

- **Dimension overrides**: `dxf_extract.py` compares every dimension's text with its measured geometry. In PDFs, calibration outliers point to the same thing. Report each mismatch with location. These are often real drawing errors and worth more to the user than the take-off itself.
- **Dimension chains**: calibration checks that each chain (3600 + 4850 + 4000) adds up to the overall dimension. A chain that doesn't add up is a classic setting-out error, so report it.
- **Sheet vs. sheet**: compare plan vs. section vs. schedule (door counts on plan vs. door schedule, slab thickness in section vs. spec).
- **Same sheet, two formats**: if you have both the PDF and the DXF of a sheet, compare them (key dimensions, counts, dimension text). A mismatch usually means they are different revisions. Flag it and ask which one is current.
- **Plausibility**: wall heights 2.4–4 m, door widths 0.7–1.2 m, slab thickness 0.1–0.4 m. If a number is wildly off, suspect scale or units first.
- **NTS details**: anything marked "NTS" or "not to scale" can't be measured. Use its dimension text and label it as such.

### 5. Compare against the specification (when asked)

Put requirements and measurements into two CSVs (format in the script's `--help`) and run:

```bash
python scripts/check_against_spec.py requirements.csv measurements.csv --out compliance.md
```

It handles unit conversion and gives PASS / FAIL / MISSING with the margin and the spec clause.

### 6. Report

Use this structure. Keep it tight: the user wants numbers they can rely on, not an essay.

```markdown
## Answer
<the direct answer, e.g. "Wall W-3 is 12.450 m (measured)">

## Quantities
| Item | Quantity | Unit | Source | Method / location |
|---|---|---|---|---|

## Scale & units
<scale used, how it was verified, confidence>

## Flags
- <dimension text vs geometry mismatches, NTS areas, missing info, assumptions>

## What would make this more accurate
<only if relevant, e.g. "a DXF of sheet A-101 would let me count doors exactly">
```

## When the scripts can't do it

The scripts cover the common cases, not every drawing. If something doesn't fit (rotated viewports, xrefs, arcs or curved walls, unusual dimension styles), write a short Python snippet with PyMuPDF / ezdxf / IfcOpenShell to do the specific measurement, and keep the same discipline: verified scale, a stated source for every number, and flags for anything uncertain.

## Setup

The scripts need Python 3.9+ and:

```bash
pip install pymupdf ezdxf          # PDF + DXF
pip install ifcopenshell           # optional, for IFC
```

If a package is missing, install it before starting rather than falling back to reading the drawing by eye.

## Reference files

- `references/file-formats.md`: which files give exact answers, how to spot a bad PDF, how to convert DWG/Revit, and a message the user can send to designers. Read it when a file is raster, DWG, or otherwise unsuitable.
- `references/scale-and-units.md`: PDF scale maths, multi-viewport sheets, DXF units and DIMLFAC, imperial drawings. Read it when calibration is weak or numbers look off by a factor.
