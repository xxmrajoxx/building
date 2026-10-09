"""Quantity takeoff helpers for PDF drawings.

Three deterministic tools, each suited to a different kind of drawing:

* schedules  - ruled tables (door/window/finish schedules) read with pdfplumber
* linework   - vector PDFs exported from CAD: stroke lengths and filled areas,
               grouped by colour and line weight, converted to real-world
               metres using the drawing scale
* rendering  - page images for preview, with a selected linework group highlighted

Scanned (raster) drawings have no vectors or text; use the AI-assisted takeoff
or manual entry for those.
"""
from __future__ import annotations

import io
import math
import re
from collections import defaultdict

import pandas as pd
import pdfplumber
import pymupdf

from .models import new_item

PT_TO_MM = 25.4 / 72


def page_count(pdf: bytes) -> int:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return doc.page_count


def page_info(pdf: bytes, page_no: int) -> dict:
    """page_no is 0-based."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[page_no]
        text = page.get_text()
        n_drawings = len(page.get_drawings())
        rect = page.rect
    w_mm, h_mm = rect.width * PT_TO_MM, rect.height * PT_TO_MM
    return {
        "text": text,
        "scales": detect_scales(text),
        "sheet_size": _sheet_size(w_mm, h_mm),
        "width_mm": round(w_mm), "height_mm": round(h_mm),
        "vector_paths": n_drawings,
        "looks_scanned": n_drawings < 5 and len(text.strip()) < 20,
    }


def _sheet_size(w_mm: float, h_mm: float) -> str:
    long_side, short_side = max(w_mm, h_mm), min(w_mm, h_mm)
    for name, (l, s) in {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}.items():
        if abs(long_side - l) < 15 and abs(short_side - s) < 15:
            return name
    return f"{w_mm:.0f}x{h_mm:.0f}mm"


def detect_scales(text: str) -> list[int]:
    """Find drawing scales like '1:100' or '1 : 50' in the page text."""
    found = re.findall(r"\b1\s*:\s*(\d{1,4})\b", text or "")
    scales = []
    for s in found:
        n = int(s)
        if n in (1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 200, 250, 500, 1000, 2000) and n not in scales:
            scales.append(n)
    return scales


def render_page(pdf: bytes, page_no: int, zoom: float = 1.5, highlight: list[dict] | None = None) -> bytes:
    """Render a page to PNG. `highlight` is a list of path dicts from linework_groups()."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[page_no]
        if highlight:
            shape = page.new_shape()
            for path in highlight:
                for item in path["items"]:
                    op = item[0]
                    if op == "l":
                        shape.draw_line(item[1], item[2])
                    elif op == "c":
                        shape.draw_bezier(item[1], item[2], item[3], item[4])
                    elif op == "re":
                        shape.draw_rect(item[1])
                    elif op == "qu":
                        shape.draw_quad(item[1])
            shape.finish(color=(1, 0, 0.8), width=3, closePath=False)
            shape.commit()
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")


# ---------------------------------------------------------------- linework

def _hex(color) -> str:
    if not color:
        return ""
    return "#" + "".join(f"{round(c * 255):02x}" for c in color[:3])


def _dist(a, b) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def _bezier_length(p0, p1, p2, p3, steps: int = 12) -> float:
    total, prev = 0.0, p0
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0.x + 3 * mt**2 * t * p1.x + 3 * mt * t**2 * p2.x + t**3 * p3.x
        y = mt**3 * p0.y + 3 * mt**2 * t * p1.y + 3 * mt * t**2 * p2.y + t**3 * p3.y
        cur = pymupdf.Point(x, y)
        total += _dist(prev, cur)
        prev = cur
    return total


def _segments(path: dict) -> list[tuple]:
    """Flatten a path to (kind, length_pt, dedupe_key) segments."""
    segs = []
    for item in path["items"]:
        op = item[0]
        if op == "l":
            a, b = item[1], item[2]
            key = tuple(sorted([(round(a.x, 1), round(a.y, 1)), (round(b.x, 1), round(b.y, 1))]))
            segs.append(("l", _dist(a, b), key))
        elif op == "c":
            segs.append(("c", _bezier_length(*item[1:5]), None))
        elif op == "re":
            r = item[1]
            segs.append(("re", 2 * (r.width + r.height), ("re", round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))))
        elif op == "qu":
            q = item[1]
            segs.append(("qu", _dist(q.ul, q.ur) + _dist(q.ur, q.lr) + _dist(q.lr, q.ll) + _dist(q.ll, q.ul), None))
    return segs


def _fill_area(path: dict) -> float:
    """Approximate enclosed area in pt^2 (rects/quads exact, polygons by shoelace)."""
    area, poly = 0.0, []
    for item in path["items"]:
        op = item[0]
        if op == "re":
            area += abs(item[1].width * item[1].height)
        elif op == "qu":
            q = item[1]
            pts = [q.ul, q.ur, q.lr, q.ll]
            area += abs(sum(pts[i].x * pts[i - 1].y - pts[i - 1].x * pts[i].y for i in range(4))) / 2
        elif op == "l":
            if not poly:
                poly.append(item[1])
            poly.append(item[2])
        elif op == "c":
            if not poly:
                poly.append(item[1])
            poly.append(item[4])
    if len(poly) >= 3:
        area += abs(sum(poly[i].x * poly[i - 1].y - poly[i - 1].x * poly[i].y for i in range(len(poly)))) / 2
    return area


def linework_groups(
    pdf: bytes,
    page_no: int,
    scale: float,
    clip: tuple[float, float, float, float] | None = None,
    min_length_m: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, list[dict]]]:
    """Group vector paths by colour and line weight and measure them at `scale` (1:scale).

    clip is (x0, y0, x1, y1) as fractions of the page, to exclude title blocks
    and legends. Returns (summary table, {group_id: [paths]}).
    """
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[page_no]
        drawings = page.get_drawings()
        prect = page.rect
    clip_rect = None
    if clip:
        x0, y0, x1, y1 = clip
        clip_rect = pymupdf.Rect(prect.x0 + x0 * prect.width, prect.y0 + y0 * prect.height,
                                 prect.x0 + x1 * prect.width, prect.y0 + y1 * prect.height)

    to_m = PT_TO_MM * scale / 1000  # paper points -> real metres
    groups: dict[tuple, dict] = defaultdict(lambda: {"length": 0.0, "area": 0.0, "segments": 0, "paths": [], "seen": set()})

    for path in drawings:
        r = path.get("rect")
        if clip_rect is not None and r is not None and not clip_rect.contains(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)):
            continue
        ptype = path.get("type") or ""
        if "s" in ptype and path.get("color"):
            key = ("stroke", _hex(path["color"]), round(path.get("width") or 0, 2))
            g = groups[key]
            for _, length, dedupe in _segments(path):
                if dedupe is not None:
                    if dedupe in g["seen"]:
                        continue
                    g["seen"].add(dedupe)
                g["length"] += length
                g["segments"] += 1
            g["paths"].append(path)
        if "f" in ptype and path.get("fill"):
            key = ("fill", _hex(path["fill"]), 0.0)
            g = groups[key]
            g["area"] += _fill_area(path)
            g["segments"] += 1
            g["paths"].append(path)

    rows, paths_by_group = [], {}
    for (kind, color, width), g in groups.items():
        length_m = g["length"] * to_m
        area_m2 = g["area"] * to_m * to_m
        if kind == "stroke" and length_m < min_length_m:
            continue
        gid = f"{kind}:{color}:{width:g}"
        rows.append({
            "group": gid, "kind": kind, "colour": color, "line_weight": width if kind == "stroke" else None,
            "paths": len(g["paths"]), "segments": g["segments"],
            "length_m": round(length_m, 2) if kind == "stroke" else None,
            "area_m2": round(area_m2, 2) if kind == "fill" else None,
        })
        paths_by_group[gid] = g["paths"]
    df = pd.DataFrame(rows, columns=["group", "kind", "colour", "line_weight", "paths", "segments", "length_m", "area_m2"])
    if not df.empty:
        df = df.sort_values(["kind", "length_m", "area_m2"], ascending=[False, False, False], na_position="last")
    return df.reset_index(drop=True), paths_by_group


# ---------------------------------------------------------------- schedules

def extract_tables(pdf: bytes, page_no: int) -> list[pd.DataFrame]:
    """Extract ruled tables from a page; the first row becomes the header."""
    out = []
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        page = doc.pages[page_no]
        for table in page.extract_tables():
            rows = [[(c or "").strip() for c in row] for row in table if row and any(c for c in row)]
            if len(rows) < 2:
                continue
            header = [h or f"col{i + 1}" for i, h in enumerate(rows[0])]
            # de-duplicate header names
            seen: dict[str, int] = {}
            for i, h in enumerate(header):
                if h in seen:
                    seen[h] += 1
                    header[i] = f"{h}_{seen[h]}"
                else:
                    seen[h] = 0
            out.append(pd.DataFrame(rows[1:], columns=header))
    return out


def _find_col(columns, patterns) -> str | None:
    for col in columns:
        name = str(col).strip().lower()
        if any(re.fullmatch(p, name) for p in patterns):
            return col
    return None


def _num(value) -> float | None:
    m = re.search(r"-?\d+(\.\d+)?", str(value or "").replace(",", ""))
    return float(m.group()) if m else None


def _schedule_trade(text: str) -> str:
    t = text.lower()
    if "window" in t or "glazing" in t or ("sliding" in t and "door" in t):
        return "Windows & Glazing"
    if "door" in t:
        return "Doors & Hardware"
    if "tile" in t or "tiling" in t:
        return "Wall & Floor Tiling"
    if any(w in t for w in ("carpet", "vinyl", "floor")):
        return "Floor Finishes"
    if "paint" in t:
        return "Painting"
    if any(w in t for w in ("light", "gpo", "power")):
        return "Electrical"
    if any(w in t for w in ("wc", "basin", "sink", "shower", "tap")):
        return "Hydraulics"
    return "Other"


def schedule_to_items(df: pd.DataFrame, page_no: int, table_no: int = 0) -> list[dict]:
    """Convert a schedule table into items.

    Count schedules (doors, windows, fixtures) give "no" items grouped by
    type/description/size. Schedules with an area column (room finishes) give
    m2 items summed per description.
    """
    cols = list(df.columns)
    desc_col = _find_col(cols, [r"desc.*", r"item", r"name", r".*finish.*", r"material", r"product", r"fixture"])
    area_col = _find_col(cols, [r"area.*", r".*m2", r".*m²"])
    if area_col and desc_col:
        return _area_schedule_items(df, desc_col, area_col, page_no, table_no)
    qty_col = _find_col(cols, [r"qty\.?", r"quantity", r"no\.?", r"count", r"number", r"nr"])
    type_col = _find_col(cols, [r"type.*", r"mark", r"ref.*", r"code", r"id", r"tag"])
    w_col = _find_col(cols, [r"width.*", r"w", r"w\s*\(mm\)"])
    h_col = _find_col(cols, [r"height.*", r"h", r"h\s*\(mm\)"])
    if not (type_col or desc_col):
        return []

    header_text = " ".join(map(str, cols))
    grouped: dict[tuple, float] = defaultdict(float)
    for _, row in df.iterrows():
        desc = str(row[desc_col]).strip() if desc_col else ""
        typ = str(row[type_col]).strip() if type_col else ""
        if not (desc or typ):
            continue
        size = ""
        if w_col and h_col and _num(row[w_col]) and _num(row[h_col]):
            size = f"{_num(row[w_col]):.0f}x{_num(row[h_col]):.0f}"
        qty = _num(row[qty_col]) if qty_col else 1.0
        if qty is None:
            qty = 1.0
        # A mark column (D01, D02...) identifies instances, so group on type/description instead.
        group_key_type = typ if (type_col and str(type_col).lower().startswith("type")) or not desc else ""
        grouped[(desc, group_key_type, size)] += qty

    items = []
    for (desc, typ, size), qty in grouped.items():
        label = desc or f"Type {typ}"
        if size:
            label += f" {size}"
        if typ and desc:
            label += f" (type {typ})"
        trade = _schedule_trade(f"{desc} {typ} {header_text}")
        items.append(new_item(trade, label, "no", qty, source="PDF schedule",
                              ref=f"PDF p.{page_no + 1} table {table_no + 1}", confidence="medium"))
    return items


def _area_schedule_items(df: pd.DataFrame, desc_col: str, area_col: str, page_no: int, table_no: int) -> list[dict]:
    areas: dict[str, float] = defaultdict(float)
    for _, row in df.iterrows():
        desc, area = str(row[desc_col]).strip(), _num(row[area_col])
        if desc and area:
            areas[desc] += area
    return [
        new_item(_schedule_trade(f"{desc} {desc_col}"), f"{desc} ({desc_col.strip().lower()})", "m2", area,
                 source="PDF schedule", ref=f"PDF p.{page_no + 1} table {table_no + 1}", confidence="medium")
        for desc, area in areas.items()
    ]
