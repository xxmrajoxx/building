"""Shared constants and the takeoff table schema.

A takeoff is a pandas DataFrame with TAKEOFF_COLUMNS. Every source (IFC, PDF
schedules, PDF linework, AI, manual entry) produces rows in this shape so the
pricing and estimate steps don't care where a quantity came from.
"""
from __future__ import annotations

import uuid

import pandas as pd

# Trade breakdown roughly following the order of an Australian trade-based BoQ.
TRADES = [
    "Demolition",
    "Site Preparation & Earthworks",
    "Concrete",
    "Reinforcement",
    "Masonry",
    "Structural Steel",
    "Carpentry",
    "Roofing",
    "External Cladding",
    "Windows & Glazing",
    "Doors & Hardware",
    "Plasterboard & Partitions",
    "Insulation",
    "Wall & Floor Tiling",
    "Floor Finishes",
    "Painting",
    "Joinery",
    "Stairs & Balustrades",
    "Hydraulics",
    "Electrical",
    "Mechanical",
    "External Works",
    "Other",
]

UNITS = ["m", "m2", "m3", "t", "kg", "no", "item"]

TAKEOFF_COLUMNS = [
    "id",
    "trade",
    "description",
    "unit",
    "quantity",
    "source",
    "ref",
    "confidence",
    "rate_code",
    "notes",
]

_UNIT_ALIASES = {
    "m²": "m2", "sqm": "m2", "sq m": "m2", "m^2": "m2",
    "m³": "m3", "cum": "m3", "cu m": "m3", "m^3": "m3",
    "lm": "m", "l/m": "m", "lin m": "m", "metre": "m", "meter": "m",
    "nr": "no", "no.": "no", "ea": "no", "each": "no", "pcs": "no", "qty": "no",
    "tonne": "t", "tonnes": "t", "tn": "t",
    "sum": "item", "ls": "item", "lump sum": "item", "allow": "item",
}


def normalise_unit(unit: str | None) -> str:
    u = (unit or "").strip().lower()
    return _UNIT_ALIASES.get(u, u)


def new_item(
    trade: str,
    description: str,
    unit: str,
    quantity: float,
    source: str,
    ref: str = "",
    confidence: str = "high",
    rate_code: str = "",
    notes: str = "",
) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "trade": trade if trade in TRADES else "Other",
        "description": description,
        "unit": normalise_unit(unit),
        "quantity": round(float(quantity), 3),
        "source": source,
        "ref": ref,
        "confidence": confidence,
        "rate_code": rate_code,
        "notes": notes,
    }


def empty_takeoff() -> pd.DataFrame:
    return pd.DataFrame(columns=TAKEOFF_COLUMNS).astype(
        {"quantity": "float64"}
    )


def items_to_frame(items: list[dict]) -> pd.DataFrame:
    if not items:
        return empty_takeoff()
    return pd.DataFrame(items, columns=TAKEOFF_COLUMNS)


def append_items(takeoff: pd.DataFrame, items: list[dict]) -> pd.DataFrame:
    if not items:
        return takeoff
    new = items_to_frame(items)
    if takeoff.empty:
        return new.reset_index(drop=True)
    return pd.concat([takeoff, new], ignore_index=True)


def clean_takeoff(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce an edited takeoff (e.g. from the UI grid) back into a valid shape."""
    df = df.copy()
    for col in TAKEOFF_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[TAKEOFF_COLUMNS]
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    for col in ("trade", "description", "unit", "source", "ref", "confidence", "rate_code", "notes", "id"):
        df[col] = df[col].fillna("").astype(str)
    df["unit"] = df["unit"].map(normalise_unit)
    missing_id = df["id"] == ""
    df.loc[missing_id, "id"] = [uuid.uuid4().hex[:8] for _ in range(int(missing_id.sum()))]
    return df.reset_index(drop=True)
