"""Rate library loading and takeoff-to-rate matching."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .models import normalise_unit

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_RATES = DATA_DIR / "rates_au.csv"
CUSTOM_RATES = DATA_DIR / "rates_custom.csv"
LOCATION_FACTORS = DATA_DIR / "location_factors.csv"

RATE_COLUMNS = [
    "code", "trade", "description", "unit", "material", "labour", "plant",
    "waste_pct", "keywords", "ifc_class",
]

_STOPWORDS = {
    "and", "the", "to", "of", "in", "incl", "including", "with", "per", "for",
    "a", "an", "on", "x", "mm", "approx", "supply", "fix", "install", "type",
    "basic", "level", "generic",
}

# Minimum match score before a rate is auto-assigned. Neither a trade nor an IFC
# class match is enough alone (3 each); at least one shared word is also needed.
MATCH_THRESHOLD = 4.0


def load_rates(path: Path | str | None = None) -> pd.DataFrame:
    if path is None:
        path = CUSTOM_RATES if CUSTOM_RATES.exists() else DEFAULT_RATES
    return clean_rates(pd.read_csv(path, dtype=str))


def clean_rates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in RATE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[RATE_COLUMNS]
    for col in ("material", "labour", "plant", "waste_pct"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in ("code", "trade", "description", "unit", "keywords", "ifc_class"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["unit"] = df["unit"].map(normalise_unit)
    df = df[df["code"] != ""].drop_duplicates("code", keep="last")
    return df.reset_index(drop=True)


def save_rates(df: pd.DataFrame, path: Path | str = CUSTOM_RATES) -> None:
    clean_rates(df).to_csv(path, index=False)


def unit_rate(row: pd.Series | dict) -> float:
    """All-in unit rate: material (plus waste) + labour + plant."""
    material = float(row["material"]) * (1 + float(row["waste_pct"]) / 100)
    return material + float(row["labour"]) + float(row["plant"])


def with_unit_rates(rates: pd.DataFrame) -> pd.DataFrame:
    out = rates.copy()
    out["unit_rate"] = out.apply(unit_rate, axis=1).round(2) if not out.empty else []
    return out


def load_location_factors() -> dict[str, float]:
    df = pd.read_csv(LOCATION_FACTORS)
    return dict(zip(df["location"], df["factor"].astype(float)))


def _tokens(text: str) -> set[str]:
    words = re.split(r"[^a-z0-9.]+", (text or "").lower())
    return {w.strip(".") for w in words if len(w.strip(".")) > 1 and w not in _STOPWORDS}


def score_rate(item: dict | pd.Series, rate: dict | pd.Series) -> float:
    """Score how well a rate fits a takeoff item. Units must match exactly."""
    if normalise_unit(item["unit"]) != rate["unit"]:
        return 0.0
    item_tokens = _tokens(f"{item['description']} {item.get('notes', '')}")
    score = 2.0 * len(item_tokens & _tokens(rate["keywords"]))
    score += 1.0 * len(item_tokens & _tokens(rate["description"]))
    if rate["ifc_class"]:
        classes = {c.strip() for c in rate["ifc_class"].split(";") if c.strip()}
        ref = str(item.get("ref", ""))
        if any(re.search(rf"\b{re.escape(c)}\b", ref) for c in classes):
            score += 3.0
    if item.get("trade") and item["trade"] == rate["trade"]:
        score += 3.0
    return score


def best_match(item: dict | pd.Series, rates: pd.DataFrame) -> tuple[str, float]:
    best_code, best_score = "", 0.0
    for _, rate in rates.iterrows():
        s = score_rate(item, rate)
        if s > best_score:
            best_code, best_score = rate["code"], s
    if best_score < MATCH_THRESHOLD:
        return "", best_score
    return best_code, best_score


def auto_match(takeoff: pd.DataFrame, rates: pd.DataFrame, overwrite: bool = False) -> pd.DataFrame:
    """Fill rate_code for takeoff rows that don't have one (or all rows if overwrite)."""
    out = takeoff.copy()
    valid_codes = set(rates["code"])
    for idx, row in out.iterrows():
        current = str(row.get("rate_code") or "")
        if current and current in valid_codes and not overwrite:
            continue
        code, _ = best_match(row, rates)
        out.at[idx, "rate_code"] = code
    return out
