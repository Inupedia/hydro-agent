"""Sandbox I/O helpers for the GR4J runtime."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from .contracts import Gr4jBasin, Gr4jScheme


def load_gr4j_inputs(workspace: Path):
    import numpy as np

    scheme_payload = json.loads(
        (workspace / "input/scheme/scheme.json").read_text(encoding="utf-8")
    )
    scheme = Gr4jScheme(
        model_id=scheme_payload.get("model_id", "gr4j"),
        warmup_days=scheme_payload["warmup_days"],
        parameters=scheme_payload["parameters"],
    )
    basin = Gr4jBasin.model_validate_json(
        (workspace / "input/snapshot/basin.json").read_text(encoding="utf-8")
    )
    with (workspace / "input/snapshot/forcing.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["date", "precipitation_mm_day", "pet_mm_day"]:
            raise ValueError("invalid forcing columns")
        rows = list(reader)
    dates = [date.fromisoformat(row["date"]) for row in rows]
    if len(dates) < scheme.warmup_days + 3:
        raise ValueError("insufficient warmup and leads")
    if any(b - a != timedelta(days=1) for a, b in zip(dates, dates[1:])):
        raise ValueError("forcing must contain consecutive daily rows")
    array = np.asarray(
        [[float(row["precipitation_mm_day"]), float(row["pet_mm_day"])] for row in rows]
    )
    if not np.isfinite(array).all() or (array < 0).any():
        raise ValueError("forcing must be finite and nonnegative")
    return scheme, basin, dates, array[:, None, :]
