"""Quantity takeoff from IFC (BIM) models.

Quantities come from the model's base quantity sets (Qto_*) where the authoring
tool exported them, converted to SI units. Where they're missing, the element
geometry is tessellated and measured instead. Elements are then grouped by
class, type, material and measure so the result reads like a BoQ.
"""
from __future__ import annotations

import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel
import ifcopenshell.util.shape as ush
import ifcopenshell.util.unit as uunit

from .models import TAKEOFF_COLUMNS, new_item

FRIENDLY = {
    "IfcWall": "Wall", "IfcWallStandardCase": "Wall", "IfcSlab": "Slab", "IfcFooting": "Footing",
    "IfcBeam": "Beam", "IfcColumn": "Column", "IfcMember": "Member", "IfcPile": "Pile",
    "IfcRoof": "Roof", "IfcCovering": "Covering", "IfcDoor": "Door", "IfcWindow": "Window",
    "IfcCurtainWall": "Curtain wall", "IfcPlate": "Plate", "IfcStair": "Stair",
    "IfcRailing": "Railing", "IfcRamp": "Ramp", "IfcSpace": "Room",
    "IfcSanitaryTerminal": "Sanitary fixture", "IfcLightFixture": "Light fitting",
    "IfcOutlet": "Outlet", "IfcAirTerminal": "Air terminal", "IfcFlowTerminal": "Fixture",
    "IfcBuildingElementProxy": "Proxy element",
}

TAKEOFF_CLASSES = list(FRIENDLY)

# Parents whose own quantity already covers their parts.
_COUNTED_PARENTS = {"IfcCurtainWall", "IfcStair", "IfcRailing", "IfcRamp"}

# Indicative reinforcement densities (kg of reo per m3 of concrete).
REO_KG_PER_M3 = {"IfcSlab": 100, "IfcFooting": 80, "IfcWall": 120, "IfcColumn": 180, "IfcBeam": 160, "IfcPile": 100}

STEEL_DENSITY_T_PER_M3 = 7.85

_MATERIAL_CATEGORIES = [
    ("plasterboard", {"plasterboard", "gypsum", "stud", "drywall", "gyprock", "partition", "gib"}),
    ("concrete", {"concrete", "conc", "rc", "reinforced", "precast", "insitu"}),
    ("masonry", {"brick", "brickwork", "block", "blockwork", "masonry", "cmu"}),
    ("timber", {"timber", "wood", "lvl", "glulam", "pine", "mgp10", "hardwood", "softwood"}),
    ("steel", {"steel", "ub", "uc", "shs", "rhs", "pfc", "chs", "metal"}),
    ("glass", {"glass", "glazing", "glazed"}),
]


@dataclass
class IfcTakeoffResult:
    items: pd.DataFrame
    schema: str = ""
    project: str = ""
    storeys: list[str] = field(default_factory=list)
    element_counts: dict[str, int] = field(default_factory=dict)
    gross_floor_area: float = 0.0
    warnings: list[str] = field(default_factory=list)


def open_ifc(data: bytes) -> ifcopenshell.file:
    # ifcopenshell needs a real file path; write to a temp file and clean up.
    fd, path = tempfile.mkstemp(suffix=".ifc")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return ifcopenshell.open(path)
    finally:
        os.remove(path)


def _material_names(elem) -> list[str]:
    mat = uel.get_material(elem, should_skip_usage=True)
    if mat is None:
        return []
    if mat.is_a("IfcMaterial"):
        return [mat.Name or ""]
    if mat.is_a("IfcMaterialLayerSet"):
        return [l.Material.Name for l in mat.MaterialLayers if l.Material]
    if mat.is_a("IfcMaterialProfileSet"):
        return [p.Material.Name for p in mat.MaterialProfiles if p.Material]
    if mat.is_a("IfcMaterialConstituentSet"):
        return [c.Material.Name for c in mat.MaterialConstituents or [] if c.Material]
    if mat.is_a("IfcMaterialList"):
        return [m.Name for m in mat.Materials]
    return []


def _material_category(*texts: str) -> str:
    tokens = set(re.split(r"[^a-z0-9]+", " ".join(texts).lower()))
    for category, words in _MATERIAL_CATEGORIES:
        if tokens & words:
            return category
    return ""


def _is_external(psets: dict) -> bool | None:
    for name, props in psets.items():
        if name.endswith("Common") and "IsExternal" in props:
            return bool(props["IsExternal"])
    return None


class _Measurer:
    """Reads Qto quantities (unit-converted) and falls back to geometry."""

    _KIND_UNIT = {"length": "LENGTHUNIT", "area": "AREAUNIT", "volume": "VOLUMEUNIT", "mass": "MASSUNIT"}

    def __init__(self, model: ifcopenshell.file):
        self.model = model
        self.scale = {}
        for kind, unit_type in self._KIND_UNIT.items():
            try:
                self.scale[kind] = uunit.calculate_unit_scale(model, unit_type)
            except Exception:
                self.scale[kind] = 1.0
        self.settings = ifcopenshell.geom.settings()
        self.settings.set("use-world-coords", True)
        self.geometry_failures = 0

    def qto(self, qtos: dict, names: list[str], kind: str) -> float | None:
        for qset in qtos.values():
            for name in names:
                value = qset.get(name)
                if isinstance(value, (int, float)) and value > 0:
                    return float(value) * self.scale[kind]
        return None

    def geometry(self, elem):
        try:
            return ifcopenshell.geom.create_shape(self.settings, elem).geometry
        except Exception:
            self.geometry_failures += 1
            return None

    def length_scale(self) -> float:
        return self.scale["length"]


def _geom_value(geom, how: str) -> float | None:
    if geom is None:
        return None
    try:
        if how == "volume":
            return float(ush.get_volume(geom))
        if how == "side_area":
            return float(ush.get_max_side_area(geom))
        if how == "footprint":
            return float(ush.get_footprint_area(geom))
        if how == "top_area":
            return float(ush.get_top_area(geom))
        if how == "length":
            verts = np.asarray(ush.get_vertices(geom))
            return float(np.ptp(verts, axis=0).max()) if len(verts) else None
    except Exception:
        return None
    return None


def _element_measures(elem, cls: str, category: str, external: bool | None, qtos: dict, m: _Measurer):
    """Return a list of (label, unit, value, trade, method) for one element."""
    geom_cache = {}

    def geom():
        if "g" not in geom_cache:
            geom_cache["g"] = m.geometry(elem)
        return geom_cache["g"]

    def measure(names, kind, geom_how):
        v = m.qto(qtos, names, kind)
        if v is not None:
            return v, "Qto"
        v = _geom_value(geom(), geom_how)
        return (v, "geometry") if v else (None, "")

    out = []
    volume_names = ["NetVolume", "GrossVolume"]

    if cls in ("IfcWall", "IfcWallStandardCase"):
        if category == "concrete":
            v, how = measure(volume_names, "volume", "volume")
            out.append(("volume", "m3", v, "Concrete", how))
        else:
            trade = {
                "masonry": "Masonry", "timber": "Carpentry", "plasterboard": "Plasterboard & Partitions",
                "steel": "Plasterboard & Partitions", "glass": "Windows & Glazing",
            }.get(category, "Masonry" if external else "Plasterboard & Partitions")
            v, how = measure(["NetSideArea", "GrossSideArea", "NetArea", "GrossArea"], "area", "side_area")
            out.append(("area", "m2", v, trade, how))
    elif cls == "IfcSlab":
        if str(getattr(elem, "PredefinedType", "")) == "ROOF":
            v, how = measure(["NetArea", "GrossArea"], "area", "top_area")
            out.append(("roof area", "m2", v, "Roofing", how))
        elif category in ("", "concrete"):
            v, how = measure(volume_names, "volume", "volume")
            out.append(("volume", "m3", v, "Concrete", how))
            a, how = measure(["NetArea", "GrossArea"], "area", "footprint")
            out.append(("area", "m2", a, "Concrete", how))
        else:
            a, how = measure(["NetArea", "GrossArea"], "area", "footprint")
            out.append(("area", "m2", a, "Carpentry" if category == "timber" else "Other", how))
    elif cls == "IfcFooting":
        v, how = measure(volume_names, "volume", "volume")
        out.append(("volume", "m3", v, "Concrete", how))
    elif cls in ("IfcBeam", "IfcColumn", "IfcMember"):
        if category == "steel":
            w = m.qto(qtos, ["NetWeight", "GrossWeight"], "mass")
            if w is not None:
                out.append(("weight", "t", w / 1000, "Structural Steel", "Qto"))
            else:
                v, how = measure(volume_names, "volume", "volume")
                out.append(("weight", "t", v * STEEL_DENSITY_T_PER_M3 if v else None, "Structural Steel", how))
        elif category == "timber":
            v, how = measure(["Length"], "length", "length")
            out.append(("length", "m", v, "Carpentry", how))
        else:
            v, how = measure(volume_names, "volume", "volume")
            out.append(("volume", "m3", v, "Concrete", how))
    elif cls == "IfcPile":
        v, how = measure(["Length"], "length", "length")
        out.append(("length", "m", v, "Concrete", how))
    elif cls == "IfcRoof":
        v, how = measure(["NetArea", "GrossArea", "ProjectedArea"], "area", "top_area")
        out.append(("roof area", "m2", v, "Roofing", how))
    elif cls == "IfcCovering":
        ptype = str(getattr(elem, "PredefinedType", "") or "")
        trade = {
            "FLOORING": "Floor Finishes", "CEILING": "Plasterboard & Partitions", "CLADDING": "External Cladding",
            "ROOFING": "Roofing", "INSULATION": "Insulation",
        }.get(ptype, "Other")
        geom_how = "side_area" if ptype == "CLADDING" else "footprint"
        v, how = measure(["NetArea", "GrossArea"], "area", geom_how)
        out.append((f"{ptype.lower()} area" if ptype else "area", "m2", v, trade, how))
    elif cls in ("IfcCurtainWall", "IfcPlate"):
        v, how = measure(["NetArea", "GrossArea", "NetSideArea", "GrossSideArea"], "area", "side_area")
        trade = "Windows & Glazing" if cls == "IfcCurtainWall" or category == "glass" else "External Cladding"
        out.append(("area", "m2", v, trade, how))
    elif cls in ("IfcRailing",):
        v, how = measure(["Length"], "length", "length")
        out.append(("length", "m", v, "Stairs & Balustrades", how))
    elif cls == "IfcSpace":
        v, how = measure(["NetFloorArea", "GrossFloorArea"], "area", "footprint")
        out.append(("floor area", "m2", v, "Floor Finishes", how))
    else:
        trade = {
            "IfcDoor": "Doors & Hardware", "IfcWindow": "Windows & Glazing", "IfcStair": "Stairs & Balustrades",
            "IfcRamp": "Stairs & Balustrades", "IfcSanitaryTerminal": "Hydraulics", "IfcFlowTerminal": "Hydraulics",
            "IfcLightFixture": "Electrical", "IfcOutlet": "Electrical", "IfcAirTerminal": "Mechanical",
        }.get(cls, "Other")
        out.append(("", "no", 1.0, trade, "count"))
    return out


def _size_label(elem, m: _Measurer) -> str:
    w, h = getattr(elem, "OverallWidth", None), getattr(elem, "OverallHeight", None)
    if w and h:
        mm = m.length_scale() * 1000
        return f"{w * mm:.0f}x{h * mm:.0f}"
    return ""


def takeoff_ifc(
    model: ifcopenshell.file,
    split_by_storey: bool = False,
    include_reo: bool = True,
) -> IfcTakeoffResult:
    m = _Measurer(model)
    groups: dict[tuple, dict] = defaultdict(lambda: {"value": 0.0, "count": 0, "methods": set(), "storeys": set()})
    element_counts: dict[str, int] = defaultdict(int)
    missing = 0

    elements = []
    for cls in TAKEOFF_CLASSES:
        try:
            # include_subtypes=False so IfcWallStandardCase isn't counted twice under IfcWall.
            elements.extend(model.by_type(cls, include_subtypes=False))
        except RuntimeError:
            pass  # class not in this schema (e.g. IfcWallStandardCase in IFC4X3)

    for elem in elements:
        cls = elem.is_a()
        if cls == "IfcRoof" and elem.IsDecomposedBy:
            continue  # roof slabs are measured individually
        parent = uel.get_aggregate(elem)
        if parent is not None and parent.is_a() in _COUNTED_PARENTS:
            continue
        element_counts[cls] += 1

        el_type = uel.get_type(elem)
        type_name = (el_type.Name if el_type else None) or elem.ObjectType or elem.Name or "Untyped"
        if cls == "IfcSpace":
            type_name = elem.LongName or elem.Name or "Unnamed room"
        materials = [n for n in _material_names(elem) if n]
        material = ", ".join(dict.fromkeys(materials))[:60]
        psets = uel.get_psets(elem)
        qtos = {k: v for k, v in psets.items() if k.startswith("Qto_") or "Quantities" in k}
        external = _is_external(psets)
        category = _material_category(material, type_name, elem.Name or "")
        container = uel.get_container(elem)
        storey = (container.Name or "") if container is not None else ""
        size = _size_label(elem, m) if cls in ("IfcDoor", "IfcWindow") else ""

        for label, unit, value, trade, method in _element_measures(elem, cls, category, external, qtos, m):
            if not value:
                missing += 1
                continue
            key = (cls, type_name, material, size, external, label, unit, trade, storey if split_by_storey else "")
            g = groups[key]
            g["value"] += value
            g["count"] += 1
            g["methods"].add(method)
            g["storeys"].add(storey)
            if include_reo and unit == "m3" and trade == "Concrete" and cls in REO_KG_PER_M3:
                kg = REO_KG_PER_M3[cls]
                reo_key = (cls, f"reo@{kg}", "", "", None, "reinforcement", "t", "Reinforcement",
                           storey if split_by_storey else "")
                r = groups[reo_key]
                r["value"] += value * kg / 1000
                r["count"] += 1
                r["methods"].add(f"allowance {kg} kg/m3")
                r["storeys"].add(storey)

    items = []
    include = []
    for (cls, type_name, material, size, external, label, unit, trade, storey), g in groups.items():
        friendly = FRIENDLY.get(cls, cls)
        if label == "reinforcement":
            kg = type_name.split("@")[1]
            desc = f"Reinforcement allowance to {friendly.lower()}s @ {kg} kg/m3"
        else:
            parts = [friendly]
            if external is True:
                parts.append("external")
            elif external is False and cls in ("IfcWall", "IfcWallStandardCase", "IfcDoor", "IfcWindow"):
                parts.append("internal")
            desc = " ".join(parts) + f" - {type_name}"
            if size and size not in type_name:
                desc += f" {size}"
            if material and material.lower() not in type_name.lower():
                desc += f" [{material}]"
            if label and unit != "no":
                desc += f" ({label})"
        storey_txt = storey or ", ".join(sorted(s for s in g["storeys"] if s))
        ref = f"{cls} x{g['count']} | {'/'.join(sorted(g['methods']))}" + (f" | {storey_txt}" if storey_txt else "")
        confidence = "high" if g["methods"] <= {"Qto", "count"} else "medium"
        if label == "reinforcement":
            confidence = "low"
        items.append(new_item(trade, desc, unit, g["value"], source="IFC", ref=ref, confidence=confidence))
        include.append(cls not in ("IfcSpace", "IfcBuildingElementProxy"))

    df = pd.DataFrame(items, columns=TAKEOFF_COLUMNS)
    df.insert(0, "include", include)
    df = df.sort_values(["trade", "description"]).reset_index(drop=True)

    gfa = sum(
        v["value"] for k, v in groups.items() if k[0] == "IfcSpace" and k[6] == "m2"
    )
    warnings = []
    if missing:
        warnings.append(f"{missing} element measurements had no Qto data and no measurable geometry; they were skipped.")
    if m.geometry_failures:
        warnings.append(f"Geometry could not be processed for {m.geometry_failures} elements.")
    if not any(k[0] == "IfcSpace" for k in groups):
        warnings.append("No IfcSpace (rooms) found - floor areas for finishes must come from slabs, coverings or drawings.")

    projects = model.by_type("IfcProject")
    return IfcTakeoffResult(
        items=df,
        schema=model.schema,
        project=(projects[0].Name or "") if projects else "",
        storeys=[s.Name or "" for s in model.by_type("IfcBuildingStorey")],
        element_counts=dict(sorted(element_counts.items())),
        gross_floor_area=round(gfa, 2),
        warnings=warnings,
    )
