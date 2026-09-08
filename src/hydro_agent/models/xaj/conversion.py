import csv
import json
from datetime import date, timedelta
from pathlib import Path

from .contracts import XajBasin, XajScheme


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def load_xaj_inputs(workspace: Path):
    import numpy as np

    scheme_payload = json.loads(
        (workspace / "input/scheme/scheme.json").read_text(encoding="utf-8")
    )
    scheme_payload.pop("scheme_id", None)
    scheme = XajScheme(**scheme_payload)
    basin = XajBasin.model_validate_json(
        (workspace / "input/snapshot/basin.json").read_text(encoding="utf-8")
    )
    with (workspace / "input/snapshot/forcing.csv").open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["date", "precipitation_mm_day", "pet_mm_day"]:
            raise ValueError("invalid forcing columns")
        rows = list(reader)
    dates = [date.fromisoformat(r["date"]) for r in rows]
    if len(dates) < scheme.warmup_days + 3:
        raise ValueError("insufficient warmup and leads")
    if any(b - a != timedelta(days=1) for a, b in zip(dates, dates[1:])):
        raise ValueError("forcing must contain consecutive daily rows")
    array = np.asarray([[float(r["precipitation_mm_day"]), float(r["pet_mm_day"])] for r in rows])
    if not np.isfinite(array).all() or (array < 0).any():
        raise ValueError("forcing must be finite and nonnegative")
    return scheme, basin, dates, array[:, None, :]
