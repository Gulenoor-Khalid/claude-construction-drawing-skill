# Which files give exact answers

The format decides the accuracy ceiling. Same AI, same question: a scanned sheet gives a guess, a DXF gives the exact number.

| Format | What Claude gets | Exact measurement? | Notes |
|---|---|---|---|
| **DXF** | Real coordinates, layers, blocks, dimension entities | Yes, best | Open format. Export from any CAD package. |
| **IFC** (with base quantities) | Elements, types, storeys, quantities | Yes, for modelled elements | Export from Revit/ArchiCAD/Tekla with "base quantities" on. |
| **Vector PDF** (exported from CAD) | Lines and text as objects, sometimes CAD layers | Yes, once scale is verified | Good when CAD isn't available. |
| **Raster PDF** (scanned, printed and rescanned, "flattened") | Pixels | No | Only readable by eye. Ask for a better file. |
| **Images** (JPG/PNG/photos of sheets) | Pixels | No | Same as raster. |
| **DWG** | Nothing directly (closed format) | After conversion to DXF | See conversion below. |

## How to tell a vector PDF from a scan

Run `scripts/inspect_drawing.py`. By hand:
- Zoom to 800%. Vector lines stay sharp; scans go blurry or blocky.
- Try selecting a dimension string as text. In a vector PDF it selects character by character. In a scan it's either not selectable or OCR'd (selectable but often wrong).
- A sheet with a slight rotation, grey background or speckles is a scan.

## Getting a better file

### DWG to DXF
- **AutoCAD / BricsCAD / DraftSight / ZWCAD:** `Save As` → `DXF` (2013 or 2018 format is fine).
- **No CAD licence:** the free *ODA File Converter* from the Open Design Alliance converts DWG to DXF in batch. The user should download it from the official ODA website themselves.
- After converting, check `$INSUNITS` with `inspect_drawing.py`. Converted files sometimes lose units.

### Revit / ArchiCAD / Tekla to IFC
- Revit: `File → Export → IFC`, then under *Modify setup → Property Sets* tick **Export base quantities**.
- ArchiCAD: IFC translator → enable *IFC Base Quantities*.
- Tekla: IFC export → *Base quantities* checkbox.
Without base quantities you still get exact counts, but not areas/volumes.

### Vector PDFs from CAD
- Use the CAD package's own **Export/Plot to PDF** with a vector PDF driver (e.g. AutoCAD "DWG To PDF.pc3").
- Keep **layers** on if the option exists ("Include layer information"). Layers make wall/door/grid separation trivial.
- Plot at a **true scale** (1:100, 1:50), never "fit to paper".
- Don't print to paper and scan, and don't "flatten" or "optimise for web" (some tools rasterise).

### Coordinated sets
- Send plans, sections, elevations **and** schedules together, ideally combined into one PDF or one DXF/IFC per discipline.
- Cross-referencing (door count on plan vs. door schedule, slab thickness on section vs. spec) only works when the related sheets are in the same request. `scripts/sheet_index.py --combine` builds a bookmarked set.

## Message the user can send to a designer

> Could you send the drawings as DXF (or DWG and we'll convert), plus vector PDFs exported directly from CAD at their true scale, with layers on? If there's a model, an IFC export with base quantities would be ideal. Scanned or flattened PDFs won't work for our take-off. Thanks!
