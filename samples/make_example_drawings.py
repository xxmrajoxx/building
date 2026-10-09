"""Generate a realistic example drawing set for testing the PDF tools.

    python samples/make_example_drawings.py

Writes samples/example_drawing_set.pdf: six A3 sheets for a 15 x 10 m single
storey house, plus an answer key printed to the console (also in the README).

  A-001  Cover sheet and drawing register
  A-101  Ground floor plan 1:100 - double-line walls, doors, windows, dimensions
  A-201  Roof plan 1:100 - roof outline (fill) and gutters
  S-101  Slab and footing plan 1:100 - slab, edge beams, pad footings (fills)
  A-601  Door, window and room finish schedules (ruled tables)
  A-101S Ground floor plan as a scanned image (no vectors or text) - for the AI tool
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
OUT = HERE / "example_drawing_set.pdf"

MM = 72 / 25.4                     # PDF points per paper mm
A3 = (420 * MM, 297 * MM)
SCALE = 100
S = MM * 1000 / SCALE              # points per real metre at 1:100
ORIGIN = (55 * MM, 60 * MM)        # where the building's (0, 0) sits on the sheet

# Building geometry (real metres)
L, W = 15.0, 10.0                  # external wall outer face
EXT_T = 0.25                       # external wall thickness
INT_T = 0.11                       # internal wall thickness
EAVES = 0.6
PARTITIONS = [                     # centrelines: (x1, y1, x2, y2)
    (6.0, EXT_T, 6.0, W - EXT_T),          # 9.50 m
    (EXT_T, 5.0, 6.0, 5.0),                # 5.75 m
    (6.0, 5.0, L - EXT_T, 5.0),            # 8.75 m
    (10.5, 5.0, 10.5, W - EXT_T),          # 4.75 m
]
DOORS = [(6.0, 2.0, "v"), (3.0, 5.0, "h"), (8.0, 5.0, "h"), (12.5, 5.0, "h"), (2.0, 0.0, "h")]
WINDOWS = [(3.0, 10.0), (8.25, 10.0), (12.75, 10.0), (15.0, 2.5), (10.0, 0.0), (0.0, 7.5)]

BLACK, GREY, BLUE, CYAN, GREEN = (0, 0, 0), (0.35, 0.35, 0.35), (0, 0.3, 0.8), (0, 0.6, 0.7), (0, 0.55, 0.2)


def P(x: float, y: float) -> pymupdf.Point:
    """Real-world metres -> page point (y up on the drawing, down on the page)."""
    return pymupdf.Point(ORIGIN[0] + x * S, ORIGIN[1] + (W - y) * S)


def lines(page, segments, color, width):
    shape = page.new_shape()
    for a, b in segments:
        shape.draw_line(P(*a), P(*b))
    shape.finish(color=color, width=width, closePath=False)
    shape.commit()


def fill_rect(page, x0, y0, x1, y1, fill, color=None, width=0.3):
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(P(x0, y1), P(x1, y0)))
    shape.finish(color=color, fill=fill, width=width)
    shape.commit()


def title_block(page, number: str, title: str, scale: str = "1:100 @ A3") -> None:
    x0, y0 = 280 * MM, 255 * MM
    page.draw_rect(pymupdf.Rect(10 * MM, 10 * MM, 410 * MM, 287 * MM), color=BLACK, width=1.0)
    page.draw_rect(pymupdf.Rect(x0, y0, 410 * MM, 287 * MM), color=BLACK, width=0.5)
    page.insert_text((x0 + 3 * MM, y0 + 7 * MM), "EXAMPLE RESIDENCE - 12 SAMPLE ST, PARRAMATTA NSW", fontsize=7)
    page.insert_text((x0 + 3 * MM, y0 + 15 * MM), title, fontsize=11)
    page.insert_text((x0 + 3 * MM, y0 + 23 * MM), f"SCALE {scale}", fontsize=8)
    page.insert_text((x0 + 55 * MM, y0 + 23 * MM), f"DWG {number}   REV B", fontsize=8)
    page.insert_text((x0 + 3 * MM, y0 + 29 * MM), "FOR TENDER - NOT FOR CONSTRUCTION", fontsize=6)


def dimension(page, a, b, offset, text):
    """Horizontal or vertical dimension line offset from the building (green, thin)."""
    (x1, y1), (x2, y2) = a, b
    if y1 == y2:
        y = y1 + offset
        lines(page, [((x1, y), (x2, y)), ((x1, y - 0.2), (x1, y + 0.2)), ((x2, y - 0.2), (x2, y + 0.2))], GREEN, 0.3)
        page.insert_text(P((x1 + x2) / 2 - 0.4, y + 0.15), text, fontsize=7, color=GREEN)
    else:
        x = x1 + offset
        lines(page, [((x, y1), (x, y2)), ((x - 0.2, y1), (x + 0.2, y1)), ((x - 0.2, y2), (x + 0.2, y2))], GREEN, 0.3)
        page.insert_text(P(x + 0.15, (y1 + y2) / 2), text, fontsize=7, color=GREEN, rotate=90)


def draw_plan(page) -> None:
    # External walls: two lines per wall (outer and inner faces)
    o, i = (0, 0, L, W), (EXT_T, EXT_T, L - EXT_T, W - EXT_T)
    for x0, y0, x1, y1 in (o, i):
        lines(page, [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))], BLACK, 0.7)
    # Internal walls: two lines per partition (each face), dark grey
    segs = []
    for x1, y1, x2, y2 in PARTITIONS:
        h = INT_T / 2
        if x1 == x2:
            segs += [((x1 - h, y1), (x2 - h, y2)), ((x1 + h, y1), (x2 + h, y2))]
        else:
            segs += [((x1, y1 - h), (x2, y2 - h)), ((x1, y1 + h), (x2, y2 + h))]
    lines(page, segs, GREY, 0.5)
    # Doors: leaf line plus swing arc (blue)
    for x, y, d in DOORS:
        shape = page.new_shape()
        if d == "h":
            shape.draw_line(P(x, y), P(x, y + 0.82))
            shape.draw_curve(P(x, y + 0.82), P(x + 0.82, y + 0.82), P(x + 0.82, y))
        else:
            shape.draw_line(P(x, y), P(x + 0.82, y))
            shape.draw_curve(P(x + 0.82, y), P(x + 0.82, y + 0.82), P(x, y + 0.82))
        shape.finish(color=BLUE, width=0.3, closePath=False)
        shape.commit()
    # Windows: three lines across the wall opening (cyan)
    for x, y in WINDOWS:
        half = 0.6
        if y in (0.0, W):
            yy = [y, y + (EXT_T / 2 if y == 0 else -EXT_T / 2), y + (EXT_T if y == 0 else -EXT_T)]
            lines(page, [((x - half, v), (x + half, v)) for v in yy], CYAN, 0.4)
        else:
            xx = [x, x + (EXT_T / 2 if x == 0 else -EXT_T / 2), x + (EXT_T if x == 0 else -EXT_T)]
            lines(page, [((v, y - half), (v, y + half)) for v in xx], CYAN, 0.4)
    # Room labels
    for name, area, (x, y) in [
        ("LIVING / KITCHEN", "27.3 m²", (1.5, 2.5)), ("BED 1", "40.6 m²", (8.5, 2.5)),
        ("BED 2", "27.3 m²", (1.5, 7.5)), ("BED 3", "20.5 m²", (7.5, 7.5)), ("BATH / LDRY", "19.6 m²", (11.7, 7.5)),
    ]:
        page.insert_text(P(x, y), name, fontsize=7)
        page.insert_text(P(x, y - 0.5), area, fontsize=6)
    dimension(page, (0, 0), (L, 0), -1.5, "15000")
    dimension(page, (0, 0), (0, W), -1.5, "10000")
    dimension(page, (0, 0), (6.0, 0), -0.8, "6000")
    page.insert_text(P(0, W + 1.2), "WALLS: EXTERNAL 250 BRICK VENEER, INTERNAL 110 STUD + 10mm PLASTERBOARD. CEILING 2700",
                     fontsize=7)


def cover(doc) -> None:
    page = doc.new_page(width=A3[0], height=A3[1])
    title_block(page, "A-001", "COVER SHEET", "NTS")
    page.insert_text((30 * MM, 50 * MM), "EXAMPLE RESIDENCE", fontsize=28)
    page.insert_text((30 * MM, 62 * MM), "Single storey dwelling - tender documentation", fontsize=12)
    rows = [
        ("A-001", "Cover sheet and drawing register"), ("A-101", "Ground floor plan"), ("A-201", "Roof plan"),
        ("S-101", "Slab and footing plan"), ("A-601", "Door, window and finish schedules"),
        ("A-101S", "Ground floor plan (scanned copy)"),
    ]
    y = 85 * MM
    page.insert_text((30 * MM, y), "DRAWING REGISTER", fontsize=11)
    for num, title in rows:
        y += 7 * MM
        page.insert_text((30 * MM, y), f"{num:<8} {title}", fontsize=9)
    page.insert_text((30 * MM, 150 * MM), "GENERAL NOTES", fontsize=11)
    notes = [
        "1. Concrete: slab 100 thick N32, SL82 mesh top. Edge beams 300 wide x 500 deep. Pads 1000x1000x600 N25.",
        "2. Roof: Colorbond corrugated sheet on battens with sarking, 22.5 deg pitch, 600 eaves, quad gutter.",
        "3. Walls: 250 brick veneer (110 brick, cavity, 90x45 MGP10 stud). Internal 90x45 stud + 10mm plasterboard.",
        "4. Ceilings: 10mm plasterboard, 2700 high, R4.0 batts. Paint 3 coat acrylic to walls and ceilings.",
    ]
    for k, n in enumerate(notes):
        page.insert_text((30 * MM, (158 + 7 * k) * MM), n, fontsize=8)


def roof(doc) -> None:
    page = doc.new_page(width=A3[0], height=A3[1])
    title_block(page, "A-201", "ROOF PLAN")
    fill_rect(page, -EAVES, -EAVES, L + EAVES, W + EAVES, fill=(0.93, 0.87, 0.75))
    e = EAVES
    lines(page, [((-e, -e), (L + e, -e)), ((L + e, -e), (L + e, W + e)), ((L + e, W + e), (-e, W + e)),
                 ((-e, W + e), (-e, -e))], BLUE, 1.0)                           # gutters
    lines(page, [((-e, -e), (5.0, W / 2)), ((L + e, -e), (10.0, W / 2)), ((-e, W + e), (5.0, W / 2)),
                 ((L + e, W + e), (10.0, W / 2)), ((5.0, W / 2), (10.0, W / 2))], BLACK, 0.4)  # hips and ridge
    page.insert_text(P(5.5, 2.5), "COLORBOND ROOF 22.5°", fontsize=8)
    page.insert_text(P(0, -2.0), "ROOF OUTLINE SHOWN IN PLAN. QUAD GUTTER TO PERIMETER. 4 No. 90 DIA DOWNPIPES.", fontsize=7)


def slab(doc) -> None:
    page = doc.new_page(width=A3[0], height=A3[1])
    title_block(page, "S-101", "SLAB AND FOOTING PLAN")
    fill_rect(page, 0, 0, L, W, fill=(0.85, 0.85, 0.85), color=BLACK, width=0.7)      # slab 150 m2
    b = 0.3
    for x0, y0, x1, y1 in [(0, 0, L, b), (0, W - b, L, W), (0, b, b, W - b), (L - b, b, L, W - b)]:
        fill_rect(page, x0, y0, x1, y1, fill=(0.55, 0.55, 0.55))                   # edge beams
    for x, y in [(6.0, 5.0), (10.5, 5.0), (3.0, 5.0), (12.5, 5.0)]:
        fill_rect(page, x - 0.5, y - 0.5, x + 0.5, y + 0.5, fill=(0.8, 0.3, 0.3))  # pad footings
    page.insert_text(P(0, -1.2), "SLAB 100 THK N32 WITH SL82 TOP. EDGE BEAM 300W x 500D, 3-N12 T&B. "
                     "PADS 1000x1000x600 N25 (4 No.). 0.2mm VAPOUR BARRIER.", fontsize=7)


def schedules(doc) -> None:
    page = doc.new_page(width=A3[0], height=A3[1])
    title_block(page, "A-601", "SCHEDULES", "NTS")

    def table(x_mm, y_mm, title, header, rows, widths):
        page.insert_text((x_mm * MM, (y_mm - 3) * MM), title, fontsize=11)
        y = y_mm * MM
        for r, row in enumerate([header] + rows):
            x = x_mm * MM
            for c, text in enumerate(row):
                rect = pymupdf.Rect(x, y, x + widths[c] * MM, y + 7 * MM)
                page.draw_rect(rect, color=BLACK, width=0.4)
                page.insert_text((rect.x0 + 1.5 * MM, rect.y1 - 2.2 * MM), text, fontsize=7.5)
                x += widths[c] * MM
            y += 7 * MM

    table(20, 30, "DOOR SCHEDULE", ["MARK", "TYPE", "DESCRIPTION", "WIDTH", "HEIGHT", "QTY"], [
        ["D01", "D1", "External solid core door", "920", "2040", "1"],
        ["D02-D05", "D2", "Internal hollow core door", "820", "2040", "4"],
        ["D06", "D3", "Aluminium sliding door", "2400", "2100", "1"],
    ], [20, 14, 70, 18, 18, 12])
    table(20, 80, "WINDOW SCHEDULE", ["MARK", "TYPE", "DESCRIPTION", "WIDTH", "HEIGHT", "QTY"], [
        ["W01-W04", "W1", "Aluminium window awning", "1200", "1200", "4"],
        ["W05", "W2", "Aluminium window sliding", "1800", "1200", "1"],
        ["W06", "W3", "Aluminium window obscure", "600", "900", "1"],
    ], [20, 14, 70, 18, 18, 12])
    table(20, 130, "ROOM FINISH SCHEDULE", ["ROOM", "FLOOR FINISH", "AREA m2", "WALLS", "CEILING"], [
        ["Living / Kitchen", "Timber floating floor", "27.3", "Paint", "Plasterboard"],
        ["Bed 1", "Carpet", "40.6", "Paint", "Plasterboard"],
        ["Bed 2", "Carpet", "27.3", "Paint", "Plasterboard"],
        ["Bed 3", "Carpet", "20.5", "Paint", "Plasterboard"],
        ["Bath / Laundry", "Porcelain floor tile", "19.6", "Tile to 1200", "Plasterboard"],
    ], [38, 45, 20, 28, 28])


def scanned_copy(doc, plan_page_no: int) -> None:
    """Rasterise the floor plan so it behaves like a scanned drawing."""
    pix = doc[plan_page_no].get_pixmap(dpi=110, alpha=False)
    page = doc.new_page(width=A3[0], height=A3[1])
    page.insert_image(page.rect, pixmap=pix)


def main() -> None:
    doc = pymupdf.open()
    cover(doc)
    plan = doc.new_page(width=A3[0], height=A3[1])
    title_block(plan, "A-101", "GROUND FLOOR PLAN")
    draw_plan(plan)
    roof(doc)
    slab(doc)
    schedules(doc)
    scanned_copy(doc, 1)
    doc.save(str(OUT), garbage=3, deflate=True)
    print(f"Wrote {OUT}")
    print(ANSWER_KEY)


ANSWER_KEY = """
Answer key (scale 1:100)
  p2 A-101  black lines (external walls, both faces) ...... 98.00 m  -> halved 49.00 m centreline
            x 2.7 m high (halved) ......................... 132.30 m2 wall area (gross, no opening deductions)
            dark grey lines (internal walls, both faces) .. 57.50 m  -> halved 28.75 m
            blue (doors) / cyan (windows) / green (dimensions) are separate groups to ignore
            black 1.0pt 135.40 m on every sheet is the sheet border - ignore it
  p3 A-201  roof fill ...................................... 181.44 m2 (16.2 x 11.2)
            blue gutter line ............................... 54.80 m
  p4 S-101  light grey slab fill ........................... 150.00 m2 -> x 0.1 = 15.00 m3
            dark grey edge beams ........................... 14.64 m2 -> x 0.5 = 7.32 m3
            red pad footings ............................... 4.00 m2  -> x 0.6 = 2.40 m3
  p5 A-601  doors: 1 external, 4 internal, 1 sliding; windows: 4 + 1 + 1
            finishes: timber 27.3 m2, carpet 88.4 m2, tile 19.6 m2
  p6        scanned copy of A-101 - the app flags it as scanned; use the AI-assisted tool
"""

if __name__ == "__main__":
    main()
