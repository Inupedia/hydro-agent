import csv
import json
from datetime import date, timedelta
from pathlib import Path

from hydro_agent.models.forcing import load_forcing_matrix

from .contracts import XajBasin, XajScheme


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def load_xaj_inputs(workspace: Path):
    scheme_payload = json.loads(
        (workspace / "input/scheme/scheme.json").read_text(encoding="utf-8")
    )
    # Ignore non-model keys that the workbench may embed for orchestration.
    scheme = XajScheme(
        model_id=scheme_payload.get("model_id", "xaj"),
        warmup_days=scheme_payload["warmup_days"],
        parameters=scheme_payload["parameters"],
        routing=scheme_payload.get("routing", {}),
    )
    basin = XajBasin.model_validate_json(
        (workspace / "input/snapshot/basin.json").read_text(encoding="utf-8")
    )
    with (workspace / "input/snapshot/forcing.csv").open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            raise ValueError("invalid forcing columns")
        required = ("precipitation_mm_day", "pet_mm_day")
        if any(col not in reader.fieldnames for col in required):
            raise ValueError("forcing csv missing required column")
        rows = list(reader)
    dates = [date.fromisoformat(r["date"]) for r in rows]
    if len(dates) < scheme.warmup_days + 3:
        raise ValueError("insufficient warmup and leads")
    if any(b - a != timedelta(days=1) for a, b in zip(dates, dates[1:])):
        raise ValueError("forcing must contain consecutive daily rows")
    array = load_forcing_matrix(rows, required_forcings=("precipitation", "pet"))
    return scheme, basin, dates, array
