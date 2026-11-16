# Scale and units

Getting scale wrong is the most dangerous error: every number is off by the same factor and still looks reasonable. Lock it before measuring and verify it against at least one known dimension.

## PDF maths

- PDF coordinates are **points**: 1 pt = 1/72 inch = **0.352778 mm** on paper.
- Real length = paper length × scale denominator.
  `real_mm = length_pt × 0.352778 × N` for a 1:N drawing.
  Example: a 352.9 pt line at 1:100 → 352.9 × 0.352778 × 100 = 12,450 mm.
- Area scales with the square: `real_m2 = area_pt2 × (0.352778 × N / 1000)²`.
- Imperial: 1/4" = 1'-0" is 1:48, 1/8" = 1'-0" is 1:96. `real_in = length_pt / 72 × N`.

## Calibration (`pdf_extract.py --calibrate`)

The script pairs each dimension string with the dimension line next to it, computes `value / paper_length` for every pair, and takes the value most pairs agree on (±2%).

- **High confidence**: ≥ 5 pairs agree and ≥ 70% of all pairs agree. Use it, and still spot-check one dimension.
- **Medium / low**: few pairs. Ask the user to confirm the scale (it's usually in the title block: `sheet_index.py` lists the scales it finds).
- **Outliers** are useful: a dimension that disagrees with its line by more than 2% is often an overridden dimension (someone typed the number), a detail drawn NTS, or a viewport at another scale. Report them.

### Sheets with several scales
Plans at 1:100 and details at 1:20 on the same sheet will give two clusters of ratios. Measure each viewport separately with `--region x0,y0,x1,y1`. Find viewport boundaries from the outliers' locations, from the detail titles (`--find "1:20"`), or by looking at the page.

### Things that break PDF scale
- "Fit to paper" plotting: no standard scale. Calibration still works if dimensions exist; otherwise ask for a re-plot.
- Page rotation: lengths are unaffected, so ignore it.
- Printed drawings scanned back to PDF: no geometry. Can't be measured.
- Dimensions drawn in a different unit to the label (e.g. a "mm" drawing with dimensions in m): calibration reports the units it assumed. Sanity-check a door width.

## DXF units

- `$INSUNITS` in the header: 4 = mm, 6 = m, 1 = inch, 2 = feet, 0 = unset.
- **Unset is common.** Infer from magnitudes: a typical door is ~900 (mm), ~0.9 (m), ~36 (in) or ~3 (ft). State the inference and pass `--units`.
- **DIMLFAC** (linear dimension scale factor) multiplies the measured value in dimension text. Details drawn at a different scale inside model space sometimes use DIMLFAC so labels read correctly. `dxf_extract.py` applies it when checking dimensions; geometry lengths are raw model units.
- Paper-space layouts contain viewports at plot scale. Measure in **model space** (default) unless the user asks about a layout.
- Blocks can be inserted at a scale. `--explode-blocks` transforms block contents to world coordinates, so lengths are correct.

## IFC units

Project units come from `IfcUnitAssignment`. `ifc_extract.py` converts quantities to m / m² / m³ and prints the scale it applied. Revit exports in mm or ft depending on the template, so always check.

## Plausibility checks (metric)

| Element | Typical range |
|---|---|
| Door leaf width | 0.7 – 1.2 m |
| Floor-to-floor height | 2.8 – 4.5 m |
| Internal wall thickness | 0.075 – 0.25 m |
| External wall thickness | 0.2 – 0.5 m |
| RC slab thickness | 0.15 – 0.35 m |
| Column size | 0.25 – 1.0 m |
| Corridor width | 1.0 – 2.5 m |

A result 10×, 25.4× or 1000× outside these ranges means a units/scale mistake, not a strange building.
