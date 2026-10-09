"""Save and load a project (details, markups and takeoff) as JSON."""
from __future__ import annotations

import json

import pandas as pd

from .estimate import EstimateSettings
from .models import clean_takeoff

FORMAT_VERSION = 1


def dump_project(project: dict, settings: EstimateSettings, takeoff: pd.DataFrame) -> bytes:
    data = {
        "format_version": FORMAT_VERSION,
        "project": project,
        "settings": settings.to_dict(),
        "takeoff": clean_takeoff(takeoff).to_dict(orient="records"),
    }
    return json.dumps(data, indent=2).encode("utf-8")


def load_project(raw: bytes) -> tuple[dict, EstimateSettings, pd.DataFrame]:
    data = json.loads(raw.decode("utf-8"))
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported project file version.")
    takeoff = clean_takeoff(pd.DataFrame(data.get("takeoff", [])))
    return data.get("project", {}), EstimateSettings.from_dict(data.get("settings", {})), takeoff
