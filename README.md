# Construction Drawing Take-off: a Claude skill

**Exact quantities from construction drawings: measured from the geometry, not guessed from pixels.**

Ask Claude "how long is wall W-3?" on a scanned plan and you'll get *"about 12 m"*.
Ask the same question with this skill on a vector PDF or DXF and you get **12.450 m (measured)**, plus a warning that the dimension next to it was typed in wrong.

AI doesn't fail at drawings because it's bad at construction. It fails because it reads the text and pixels on a sheet instead of measuring the lines. This skill gives Claude the tools and the discipline to measure.

---

## What it does

- **Triage your files**: tells you per page whether a drawing can be measured exactly (vector) or only read (scan), and what to ask the designer for instead.
- **Find the scale on its own**: matches dimension strings to their dimension lines and computes the scale (e.g. 1:100) from dozens of pairs, with a confidence level.
- **Measure**: lengths, areas and counts by layer, colour or line weight from vector PDFs; exact take-offs from DXF (layers, hatches, blocks with attributes); counts and base quantities from IFC models.
- **Catch drawing errors**: flags dimensions whose text doesn't match the geometry (overridden or wrong dimensions), and calibration outliers like NTS details.
- **Check against the spec**: compares measured values to requirements with unit conversion and gives PASS / FAIL / margin / clause.
- **Work with a whole set**: indexes sheets (number, title, scale) and combines them into one bookmarked PDF so Claude can cross-reference plan, section and schedule.
- **Label every number with its source**: *Measured*, *Model quantity*, *Dimension text* or *Read from image*, so you always know what you can rely on.

## Which files work

| You upload | Result |
|---|---|
| **DXF** | Exact. Best option. |
| **IFC** with base quantities | Exact counts and quantities. |
| **Vector PDF** exported from CAD | Exact once the scale is verified (the skill does this). |
| Scanned PDF / photo / image | Read only, not measurable. The skill tells you so and asks for a better file. |
| DWG | Convert to DXF first (instructions included). |

## Install

### Claude Code
Copy the skill folder into your skills directory:

```bash
git clone https://github.com/<your-account>/claude-construction-drawing-skill.git
```

Then copy `construction-drawing-takeoff/` to `~/.claude/skills/` (all projects) or `.claude/skills/` inside one project.

### Claude app (claude.ai / desktop)
1. Download [`dist/construction-drawing-takeoff.zip`](dist/construction-drawing-takeoff.zip).
2. In Claude, open **Settings → Capabilities**, make sure code execution is on, and upload the zip under **Skills**.

### Python packages
The skill runs small Python scripts. Claude installs these when needed, or you can install them yourself:

```bash
pip install pymupdf ezdxf          # PDF + DXF
pip install ifcopenshell           # optional, for IFC models
```

## Try it

`examples/make_samples.py` creates a small test set with known answers (a vector plan, the same plan as a scan, a DXF and an IFC):

```bash
cd examples
python make_samples.py
```

Then ask Claude something like:

- *"How long is wall W-3 on examples/samples/sample_plan.pdf, and what's the area of Office 104?"*
- *"Is sample_scan.pdf good enough for a take-off?"*
- *"Count the doors in sample_plan.dxf and check the dimensions."*
- *"Check samples/measurements.csv against samples/requirements.csv."*

Expected: wall W-3 **12.450 m**, Office 104 **91.58 m²**, **3 doors**, one dimension flagged as wrong, and the scan rejected for measurement.

## What's inside

```
construction-drawing-takeoff/
├── SKILL.md                       # the instructions Claude follows
├── scripts/
│   ├── inspect_drawing.py         # vector or scan? units? layers?
│   ├── pdf_extract.py             # calibrate scale, measure, find tags, render regions
│   ├── dxf_extract.py             # per-layer lengths/areas, blocks, dimension checks
│   ├── ifc_extract.py             # BIM counts and base quantities
│   ├── sheet_index.py             # index + combine a drawing set
│   ├── check_against_spec.py      # requirements vs. measurements
│   └── drawing_utils.py
└── references/
    ├── file-formats.md            # what to ask designers for, how to convert
    └── scale-and-units.md         # scale maths, multi-viewport sheets, DXF/IFC units
```

## Limits (read before relying on it)

- Scale calibration and dimension matching are heuristics. They work well on standard CAD exports and report their confidence. Always spot-check one known dimension before pricing off a number.
- Sheets with several viewports at different scales need measuring per viewport (`--region`). The skill explains how.
- Curved geometry is measured by flattening curves into short straight segments (sub-millimetre error on typical drawings).
- Nothing here replaces a professional's check. It makes the check faster and shows you where to look.

## License

MIT. Use it, change it, share it.
