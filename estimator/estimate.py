"""Turn a priced takeoff into a tender estimate with markups and GST."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .models import TRADES
from .rates import unit_rate


@dataclass
class EstimateSettings:
    location: str = "Sydney"
    location_factor: float = 1.0
    preliminaries_pct: float = 12.0  # site establishment, supervision, insurances
    contingency_pct: float = 5.0
    escalation_pct: float = 0.0
    overhead_pct: float = 5.0
    profit_pct: float = 6.0
    gst_pct: float = 10.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EstimateSettings":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in fields})


def build_lines(takeoff: pd.DataFrame, rates: pd.DataFrame, location_factor: float = 1.0) -> pd.DataFrame:
    """Price every takeoff row. Unmatched rows stay in with rate 0 and priced=False."""
    by_code = {r["code"]: r for _, r in rates.iterrows()}
    rows = []
    for _, item in takeoff.iterrows():
        rate = by_code.get(str(item["rate_code"]))
        qty = float(item["quantity"] or 0)
        # A rate only applies if its unit matches the measured unit.
        priced = rate is not None and rate["unit"] == item["unit"]
        r = round(unit_rate(rate) * location_factor, 2) if priced else 0.0
        rows.append({
            "trade": item["trade"],
            "description": item["description"],
            "unit": item["unit"],
            "quantity": qty,
            "rate": r,
            "amount": round(qty * r, 2),
            "rate_code": item["rate_code"],
            "rate_description": rate["description"] if rate is not None else "",
            "priced": priced,
            "issue": "" if priced else (
                "no rate assigned" if rate is None else f"unit mismatch (rate is per {rate['unit']})"
            ),
            "source": item["source"],
            "ref": item["ref"],
        })
    lines = pd.DataFrame(rows, columns=[
        "trade", "description", "unit", "quantity", "rate", "amount", "rate_code",
        "rate_description", "priced", "issue", "source", "ref",
    ])
    order = {t: i for i, t in enumerate(TRADES)}
    lines["_order"] = lines["trade"].map(order).fillna(len(TRADES))
    return lines.sort_values(["_order", "description"]).drop(columns="_order").reset_index(drop=True)


def possible_duplicates(takeoff: pd.DataFrame) -> pd.DataFrame:
    """Rows from different sources with the same rate, unit and quantity.

    Typical cause: doors counted from both the IFC model and the PDF schedule.
    """
    df = takeoff[takeoff["rate_code"] != ""]
    keys = ["rate_code", "unit", "quantity"]
    multi_source = df.groupby(keys)["source"].transform("nunique") > 1
    return df[multi_source].sort_values(keys)


def summarise(lines: pd.DataFrame, settings: EstimateSettings) -> dict:
    """Apply the markup cascade.

    Direct cost -> + preliminaries (% of direct) -> + contingency and escalation
    (% of direct + prelims) -> + overhead and profit (% of everything before it)
    -> + GST.
    """
    by_trade = (
        lines.groupby("trade", sort=False)["amount"].sum().reset_index()
        if not lines.empty else pd.DataFrame(columns=["trade", "amount"])
    )
    direct = float(lines["amount"].sum()) if not lines.empty else 0.0
    prelims = direct * settings.preliminaries_pct / 100
    base = direct + prelims
    contingency = base * settings.contingency_pct / 100
    escalation = base * settings.escalation_pct / 100
    cost = base + contingency + escalation
    overhead = cost * settings.overhead_pct / 100
    profit = cost * settings.profit_pct / 100
    total_ex = cost + overhead + profit
    gst = total_ex * settings.gst_pct / 100
    cascade = [
        ("Direct trade costs", direct),
        (f"Preliminaries ({settings.preliminaries_pct:g}%)", prelims),
        (f"Contingency ({settings.contingency_pct:g}%)", contingency),
        (f"Escalation ({settings.escalation_pct:g}%)", escalation),
        (f"Overheads ({settings.overhead_pct:g}%)", overhead),
        (f"Profit ({settings.profit_pct:g}%)", profit),
        ("Tender price (excl. GST)", total_ex),
        (f"GST ({settings.gst_pct:g}%)", gst),
        ("Tender price (incl. GST)", total_ex + gst),
    ]
    return {
        "by_trade": by_trade,
        "cascade": pd.DataFrame(cascade, columns=["item", "amount"]).round(2),
        "direct": round(direct, 2),
        "total_ex_gst": round(total_ex, 2),
        "gst": round(gst, 2),
        "total_inc_gst": round(total_ex + gst, 2),
        "unpriced_count": int((~lines["priced"]).sum()) if not lines.empty else 0,
    }
