"""Generate a small sample IFC model and PDF drawing set for trying the app.

    python samples/make_samples.py

Creates samples/sample_house.ifc and samples/sample_plans.pdf. The house is a
10 x 8 m single storey with brick external walls, stud partitions, a concrete
ground slab, doors, windows and two rooms. Some elements carry Qto base
quantities and some don't, so both the Qto and geometry paths get exercised.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

import pymupdf as fitz
import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.api.unit

HERE = Path(__file__).resolve().parent

WALL_HEIGHT = 2.7
EXT_THICKNESS = 0.25
INT_THICKNESS = 0.11


def _placement(x: float, y: float, z: float = 0.0, angle_deg: float = 0.0) -> np.ndarray:
    a = np.radians(angle_deg)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = np.cos(a), -np.sin(a), np.sin(a), np.cos(a)
    m[:3, 3] = (x, y, z)
    return m


def make_ifc(path: Path) -> None:
    api = ifcopenshell.api
    model = api.project.create_file(version="IFC4")
    project = api.root.create_entity(model, ifc_class="IfcProject", name="Sample House")
    api.unit.assign_unit(model)  # millimetres, m2, m3 - exercises unit conversion
    model_ctx = api.context.add_context(model, context_type="Model")
    body = api.context.add_context(
        model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model_ctx
    )
    site = api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    building = api.root.create_entity(model, ifc_class="IfcBuilding", name="House")
    storey = api.root.create_entity(model, ifc_class="IfcBuildingStorey", name="Ground Floor")
    api.aggregate.assign_object(model, relating_object=project, products=[site])
    api.aggregate.assign_object(model, relating_object=site, products=[building])
    api.aggregate.assign_object(model, relating_object=building, products=[storey])

    brick = api.material.add_material(model, name="Face Brick")
    stud = api.material.add_material(model, name="Steel stud and plasterboard")
    concrete = api.material.add_material(model, name="Concrete 32MPa")

    ext_type = api.root.create_entity(model, ifc_class="IfcWallType", name="Brick veneer 250")
    int_type = api.root.create_entity(model, ifc_class="IfcWallType", name="Stud partition 110")
    api.material.assign_material(model, products=[ext_type], material=brick)
    api.material.assign_material(model, products=[int_type], material=stud)

    def wall(name, wall_type, x, y, length, thickness, angle, external, with_qto):
        w = api.root.create_entity(model, ifc_class="IfcWall", name=name)
        api.type.assign_type(model, related_objects=[w], relating_type=wall_type)
        rep = api.geometry.add_wall_representation(
            model, context=body, length=length, height=WALL_HEIGHT, thickness=thickness
        )
        api.geometry.assign_representation(model, product=w, representation=rep)
        api.geometry.edit_object_placement(model, product=w, matrix=_placement(x, y, 0, angle))
        api.spatial.assign_container(model, relating_structure=storey, products=[w])
        common = api.pset.add_pset(model, product=w, name="Pset_WallCommon")
        api.pset.edit_pset(model, pset=common, properties={"IsExternal": external})
        if with_qto:
            qto = api.pset.add_qto(model, product=w, name="Qto_WallBaseQuantities")
            api.pset.edit_qto(model, qto=qto, properties={
                "Length": length * 1000,  # project length unit is mm
                "Height": WALL_HEIGHT * 1000,
                "NetSideArea": length * WALL_HEIGHT,
                "NetVolume": length * WALL_HEIGHT * thickness,
            })
        return w

    # External walls (Qto present): perimeter 36 m, 2.7 high = 97.2 m2 gross side area
    wall("W1", ext_type, 0, 0, 10, EXT_THICKNESS, 0, True, True)
    wall("W2", ext_type, 10, 0, 8, EXT_THICKNESS, 90, True, True)
    wall("W3", ext_type, 10, 8, 10, EXT_THICKNESS, 180, True, True)
    wall("W4", ext_type, 0, 8, 8, EXT_THICKNESS, 270, True, True)
    # Internal partitions (no Qto - measured from geometry): 8 m + 4 m long
    wall("P1", int_type, 6, 0.25, 7.5, INT_THICKNESS, 90, False, False)
    wall("P2", int_type, 0.25, 4, 5.75, INT_THICKNESS, 0, False, False)

    # Ground slab 10 x 8 x 0.1 (no Qto - geometry fallback)
    slab = api.root.create_entity(model, ifc_class="IfcSlab", name="Ground slab", predefined_type="FLOOR")
    rep = api.geometry.add_slab_representation(model, context=body, depth=0.1, polyline=[(0, 0), (10, 0), (10, 8), (0, 8)])
    api.geometry.assign_representation(model, product=slab, representation=rep)
    api.geometry.edit_object_placement(model, product=slab, matrix=_placement(0, 0, -0.1))
    api.material.assign_material(model, products=[slab], material=concrete)
    api.spatial.assign_container(model, relating_structure=storey, products=[slab])

    # Roof slab with Qto only
    roof = api.root.create_entity(model, ifc_class="IfcSlab", name="Roof", predefined_type="ROOF")
    qto = api.pset.add_qto(model, product=roof, name="Qto_SlabBaseQuantities")
    api.pset.edit_qto(model, qto=qto, properties={"GrossArea": 96.0})
    api.spatial.assign_container(model, relating_structure=storey, products=[roof])

    # Doors and windows (counts)
    door_int = api.root.create_entity(model, ifc_class="IfcDoorType", name="Internal hollow core door")
    door_ext = api.root.create_entity(model, ifc_class="IfcDoorType", name="External solid core door")
    win_type = api.root.create_entity(model, ifc_class="IfcWindowType", name="Aluminium window")
    for i in range(3):
        d = api.root.create_entity(model, ifc_class="IfcDoor", name=f"D0{i + 1}")
        d.OverallWidth, d.OverallHeight = 820.0, 2040.0
        api.type.assign_type(model, related_objects=[d], relating_type=door_int)
        api.spatial.assign_container(model, relating_structure=storey, products=[d])
        api.pset.edit_pset(model, pset=api.pset.add_pset(model, product=d, name="Pset_DoorCommon"),
                           properties={"IsExternal": False})
    d = api.root.create_entity(model, ifc_class="IfcDoor", name="D04")
    d.OverallWidth, d.OverallHeight = 920.0, 2040.0
    api.type.assign_type(model, related_objects=[d], relating_type=door_ext)
    api.spatial.assign_container(model, relating_structure=storey, products=[d])
    api.pset.edit_pset(model, pset=api.pset.add_pset(model, product=d, name="Pset_DoorCommon"),
                       properties={"IsExternal": True})
    for i in range(5):
        w = api.root.create_entity(model, ifc_class="IfcWindow", name=f"W0{i + 1}")
        w.OverallWidth, w.OverallHeight = 1200.0, 1200.0
        api.type.assign_type(model, related_objects=[w], relating_type=win_type)
        api.spatial.assign_container(model, relating_structure=storey, products=[w])

    # Rooms
    for name, area in (("Living", 44.0), ("Bedroom", 22.0)):
        sp = api.root.create_entity(model, ifc_class="IfcSpace", name=name)
        sp.LongName = name
        api.aggregate.assign_object(model, relating_object=storey, products=[sp])
        qto = api.pset.add_qto(model, product=sp, name="Qto_SpaceBaseQuantities")
        api.pset.edit_qto(model, qto=qto, properties={"NetFloorArea": area})

    model.write(str(path))


MM = 72 / 25.4  # points per mm


def make_pdf(path: Path) -> None:
    """Two pages: a 1:100 floor plan and a door/window schedule table."""
    doc = fitz.open()

    # Page 1: A3 landscape floor plan at 1:100. 10 m x 8 m house = 100 x 80 mm on paper.
    page = doc.new_page(width=420 * MM, height=297 * MM)
    ox, oy = 60 * MM, 50 * MM
    s = MM * 1000 / 100  # paper points per real metre at 1:100

    def pt(x, y):
        return fitz.Point(ox + x * s, oy + y * s)

    # Slab outline fill (light grey) - 80 m2
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(pt(0, 0), pt(10, 8)))
    shape.finish(color=None, fill=(0.85, 0.85, 0.85))
    shape.commit()
    # External walls - black 1.4pt, perimeter 36 m
    shape = page.new_shape()
    shape.draw_polyline([pt(0, 0), pt(10, 0), pt(10, 8), pt(0, 8), pt(0, 0)])
    shape.finish(color=(0, 0, 0), width=1.4)
    shape.commit()
    # Internal partitions - red 0.7pt, 7.75 m + 5.75 m = 13.5 m
    shape = page.new_shape()
    shape.draw_line(pt(6, 0.25), pt(6, 8))
    shape.draw_line(pt(0.25, 4), pt(6, 4))
    shape.finish(color=(0.8, 0, 0), width=0.7, closePath=False)
    shape.commit()

    page.insert_text(pt(2, 2), "LIVING", fontsize=9)
    page.insert_text(pt(7, 2), "BEDROOM", fontsize=9)
    page.insert_text((300 * MM, 270 * MM), "GROUND FLOOR PLAN", fontsize=14)
    page.insert_text((300 * MM, 280 * MM), "SCALE 1:100 @ A3", fontsize=10)
    page.insert_text((300 * MM, 288 * MM), "DWG A-101  REV A", fontsize=10)

    # Page 2: door and window schedule as a ruled table
    page = doc.new_page(width=420 * MM, height=297 * MM)
    page.insert_text((20 * MM, 20 * MM), "DOOR AND WINDOW SCHEDULE", fontsize=14)
    header = ["MARK", "TYPE", "DESCRIPTION", "WIDTH", "HEIGHT", "QTY"]
    rows = [
        ["D01", "D1", "Internal hollow core door", "820", "2040", "3"],
        ["D02", "D2", "External solid core door", "920", "2040", "1"],
        ["W01", "W1", "Aluminium window", "1200", "1200", "5"],
        ["SD01", "SD1", "Aluminium sliding door", "2400", "2100", "1"],
    ]
    col_w = [25, 20, 90, 25, 25, 20]
    x0, y0, row_h = 20 * MM, 30 * MM, 8 * MM
    for r, row in enumerate([header] + rows):
        x = x0
        for c, text in enumerate(row):
            rect = fitz.Rect(x, y0 + r * row_h, x + col_w[c] * MM, y0 + (r + 1) * row_h)
            page.draw_rect(rect, color=(0, 0, 0), width=0.5)
            page.insert_text((rect.x0 + 2 * MM, rect.y1 - 2.5 * MM), text, fontsize=9)
            x += col_w[c] * MM

    doc.save(str(path))


if __name__ == "__main__":
    make_ifc(HERE / "sample_house.ifc")
    make_pdf(HERE / "sample_plans.pdf")
    print("Wrote", HERE / "sample_house.ifc")
    print("Wrote", HERE / "sample_plans.pdf")
