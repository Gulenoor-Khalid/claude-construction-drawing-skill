#!/usr/bin/env python3
"""Build small sample drawings with known answers, for trying the skill.

    python make_samples.py            # writes into ./samples/

Creates:
  sample_plan.pdf    vector PDF, 1:100 on A3, one room 12,450 x 8,000 mm, 200 mm walls,
                     a dimension chain and ONE dimension whose text doesn't match the geometry
  sample_scan.pdf    the same sheet as a 100 dpi image: unmeasurable, for the triage demo
  sample_plan.dxf    the same room in DXF (mm): walls, 3 door blocks with tags, room hatch,
                     dimensions incl. one overridden ("12500" on a 12,450 line)
  sample_model.ifc   tiny IFC: 1 wall and 3 doors with base quantities (needs ifcopenshell)

Known answers:
  Wall W-3 (top, outside face) ....... 12.450 m
  Room internal area .................. 12.050 x 7.600 = 91.580 m2
  Doors ............................... 3 (D01, D02, D03)
  Wrong dimension ..................... text "5000" on a 4,850 mm segment (PDF), "12500" on 12,450 (DXF)
"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
os.makedirs(OUT, exist_ok=True)

L, Wd, T = 12450.0, 8000.0, 200.0  # room outer length, width, wall thickness (mm)


# ----------------------------------------------------------------------------- PDF
def make_pdf():
    import fitz
    PT_PER_MM_REAL = 1 / 100 / (25.4 / 72)  # 1:100
    ox, oy = 180.0, 260.0

    def P(x, y):  # real mm (y up) -> page pt (y down)
        return fitz.Point(ox + x * PT_PER_MM_REAL, oy + (Wd - y) * PT_PER_MM_REAL)

    doc = fitz.open()
    page = doc.new_page(width=1190.55, height=841.89)  # A3 landscape
    oc_wall = doc.add_ocg("A-WALL")
    oc_dim = doc.add_ocg("A-DIMS")
    oc_anno = doc.add_ocg("A-ANNO")
    oc_area = doc.add_ocg("A-AREA")

    # room fill (hatch stand-in)
    page.draw_rect(fitz.Rect(P(T, Wd - T), P(L - T, T)), color=None, fill=(0.92, 0.95, 1), oc=oc_area)
    # walls: outer + inner faces
    page.draw_rect(fitz.Rect(P(0, Wd), P(L, 0)), color=(0, 0, 0), width=0.7, oc=oc_wall)
    page.draw_rect(fitz.Rect(P(T, Wd - T), P(L - T, T)), color=(0, 0, 0), width=0.7, oc=oc_wall)

    blue = (0, 0.3, 0.7)

    def hdim(x0, x1, y, text, fs=7):
        a, b = P(x0, y), P(x1, y)
        page.draw_line(a, b, color=blue, width=0.25, oc=oc_dim)
        for x in (x0, x1):
            page.draw_line(P(x, y - 300), P(x, y + 300), color=blue, width=0.25, oc=oc_dim)       # extension
            page.draw_line(P(x - 150, y - 150), P(x + 150, y + 150), color=blue, width=0.5, oc=oc_dim)  # tick
        tw = fitz.get_text_length(text, fontsize=fs)
        mid = (a.x + b.x) / 2
        page.insert_text(fitz.Point(mid - tw / 2, a.y - 2), text, fontsize=fs, color=blue, oc=oc_dim)

    def vdim(y0, y1, x, text, fs=7):
        a, b = P(x, y0), P(x, y1)
        page.draw_line(a, b, color=blue, width=0.25, oc=oc_dim)
        for y in (y0, y1):
            page.draw_line(P(x - 300, y), P(x + 300, y), color=blue, width=0.25, oc=oc_dim)
            page.draw_line(P(x - 150, y - 150), P(x + 150, y + 150), color=blue, width=0.5, oc=oc_dim)
        tw = fitz.get_text_length(text, fontsize=fs)
        mid = (a.y + b.y) / 2
        page.insert_text(fitz.Point(a.x - 2, mid + tw / 2), text, fontsize=fs, color=blue, rotate=90, oc=oc_dim)

    hdim(0, L, Wd + 1500, "12450")                 # overall
    hdim(0, 3600, Wd + 700, "3600")                # chain
    hdim(3600, 8450, Wd + 700, "5000")             # WRONG: geometry is 4850
    hdim(8450, L, Wd + 700, "4000")
    vdim(0, Wd, -1200, "8000")
    hdim(0, 6000, -900, "6000")
    hdim(6000, L, -900, "6450")

    # tags
    def tag(x, y, text):
        c = P(x, y)
        r = fitz.Rect(c.x - 14, c.y - 7, c.x + 14, c.y + 7)
        page.draw_rect(r, color=(0, 0, 0), width=0.4, oc=oc_anno)
        tw = fitz.get_text_length(text, fontsize=7)
        page.insert_text(fitz.Point(c.x - tw / 2, c.y + 2.5), text, fontsize=7, oc=oc_anno)

    tag(L / 2, Wd - 600, "W-3")
    for i, x in enumerate((2000, 6200, 10400), 1):
        tag(x, 600, f"D0{i}")
    page.insert_text(P(L / 2 - 900, Wd / 2), "OFFICE 104", fontsize=9, oc=oc_anno)

    # title block
    page.draw_rect(fitz.Rect(880, 640, 1170, 820), color=(0, 0, 0), width=0.8)
    page.insert_text((895, 680), "GROUND FLOOR PLAN", fontsize=14)
    page.insert_text((895, 710), "SCALE 1:100 @ A3", fontsize=9)
    page.insert_text((895, 790), "A-101", fontsize=22)

    path = os.path.join(OUT, "sample_plan.pdf")
    doc.save(path)

    # raster version
    pix = page.get_pixmap(dpi=100)
    scan = fitz.open()
    sp = scan.new_page(width=page.rect.width, height=page.rect.height)
    sp.insert_image(sp.rect, pixmap=pix)
    scan.save(os.path.join(OUT, "sample_scan.pdf"))
    print("PDFs written")


# ----------------------------------------------------------------------------- DXF
def make_dxf():
    import ezdxf
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    for name, color in (("A-WALL", 7), ("A-DOOR", 3), ("A-AREA", 8), ("A-DIMS", 5), ("A-ANNO", 2)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()

    msp.add_lwpolyline([(0, 0), (L, 0), (L, Wd), (0, Wd)], close=True, dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline([(T, T), (L - T, T), (L - T, Wd - T), (T, Wd - T)], close=True,
                       dxfattribs={"layer": "A-WALL"})
    hatch = msp.add_hatch(color=8, dxfattribs={"layer": "A-AREA"})
    hatch.paths.add_polyline_path([(T, T), (L - T, T), (L - T, Wd - T), (T, Wd - T)], is_closed=True, flags=1)

    door = doc.blocks.new("DOOR_900")
    door.add_line((0, 0), (900, 0))
    door.add_arc((0, 0), 900, 0, 90)
    door.add_attdef("TAG", (0, -300), dxfattribs={"height": 150})
    for i, x in enumerate((2000, 6200, 10400), 1):
        ins = msp.add_blockref("DOOR_900", (x, 0), dxfattribs={"layer": "A-DOOR"})
        ins.add_auto_attribs({"TAG": f"D0{i}"})

    mm = {"dimlfac": 1.0, "dimtxt": 250, "dimasz": 150}  # plain mm dimensions
    d1 = msp.add_linear_dim(base=(0, Wd + 1500), p1=(0, Wd), p2=(L, Wd), dimstyle="EZDXF",
                            override=mm, dxfattribs={"layer": "A-DIMS"})
    d1.render()
    d2 = msp.add_linear_dim(base=(0, Wd + 700), p1=(0, Wd), p2=(L, Wd), text="12500", dimstyle="EZDXF",
                            override=mm, dxfattribs={"layer": "A-DIMS"})  # overridden text, geometry is 12450
    d2.render()
    d3 = msp.add_linear_dim(base=(-1200, 0), p1=(0, 0), p2=(0, Wd), angle=90, dimstyle="EZDXF",
                            override=mm, dxfattribs={"layer": "A-DIMS"})
    d3.render()
    msp.add_text("W-3", dxfattribs={"layer": "A-ANNO", "height": 250, "insert": (L / 2, Wd - 600)})
    msp.add_text("OFFICE 104", dxfattribs={"layer": "A-ANNO", "height": 300, "insert": (L / 2 - 900, Wd / 2)})
    doc.saveas(os.path.join(OUT, "sample_plan.dxf"))
    print("DXF written")


# ----------------------------------------------------------------------------- IFC
def make_ifc():
    try:
        import ifcopenshell
        import ifcopenshell.api as api
    except ImportError:
        print("ifcopenshell not installed: skipping IFC sample")
        return
    f = ifcopenshell.file(schema="IFC4")
    project = api.run("root.create_entity", f, ifc_class="IfcProject", name="Sample")
    api.run("unit.assign_unit", f)  # defaults: millimetres, m2, m3
    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    bldg = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Building")
    gf = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Ground Floor")
    api.run("aggregate.assign_object", f, relating_object=project, products=[site])
    api.run("aggregate.assign_object", f, relating_object=site, products=[bldg])
    api.run("aggregate.assign_object", f, relating_object=bldg, products=[gf])

    wall = api.run("root.create_entity", f, ifc_class="IfcWall", name="W-3")
    api.run("spatial.assign_container", f, relating_structure=gf, products=[wall])
    q = api.run("pset.add_qto", f, product=wall, name="Qto_WallBaseQuantities")
    api.run("pset.edit_qto", f, qto=q, properties={"Length": 12450.0, "Height": 3000.0, "Width": 200.0,
                                                   "NetSideArea": 37.35})
    for i in range(1, 4):
        d = api.run("root.create_entity", f, ifc_class="IfcDoor", name=f"D0{i}")
        api.run("spatial.assign_container", f, relating_structure=gf, products=[d])
        q = api.run("pset.add_qto", f, product=d, name="Qto_DoorBaseQuantities")
        api.run("pset.edit_qto", f, qto=q, properties={"Width": 900.0, "Height": 2100.0, "Area": 1.89})
    f.write(os.path.join(OUT, "sample_model.ifc"))
    print("IFC written")


if __name__ == "__main__":
    make_pdf()
    make_dxf()
    make_ifc()
    print(f"Samples in {OUT}")
