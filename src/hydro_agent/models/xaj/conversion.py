import csv
import json
import re
from datetime import date, timedelta
from pathlib import Path

from .contracts import XajBasin, XajScheme


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def _forcing_layout(fieldnames: list[str] | None, scheme: XajScheme) -> tuple[int, ...]:
    if fieldnames == ["date", "precipitation_mm_day", "pet_mm_day"]:
        if scheme.units:
            raise ValueError("distributed XAJ scheme requires unit forcing columns")
        return ()
    if not fieldnames or fieldnames[0] != "date":
        raise ValueError("invalid forcing columns")
    if not scheme.units:
        raise ValueError("invalid forcing columns")

    pattern = re.compile(r"^unit_(\d+)_precipitation_mm_day$")
    unit_ids: list[int] = []
    expected_columns = ["date"]
    for name in fieldnames[1:]:
        match = pattern.match(name)
        if not match:
            continue
        unit_id = int(match.group(1))
        unit_ids.append(unit_id)
        expected_columns.extend(
            [
                f"unit_{unit_id}_precipitation_mm_day",
                f"unit_{unit_id}_pet_mm_day",
            ]
        )
    if fieldnames != expected_columns or not unit_ids:
        raise ValueError("invalid distributed forcing columns")

    scheme_ids = tuple(int(unit.unit_id) for unit in scheme.units)
    if tuple(unit_ids) != scheme_ids:
        raise ValueError(
            f"distributed forcing unit order mismatch: csv={tuple(unit_ids)}, scheme={scheme_ids}"
        )
    return tuple(unit_ids)


def load_xaj_inputs(workspace: Path):
    import numpy as np

    scheme_payload = json.loads(
        (workspace / "input/scheme/scheme.json").read_text(encoding="utf-8")
    )
    scheme = XajScheme(
        model_id=scheme_payload.get("model_id", "xaj"),
        warmup_days=scheme_payload["warmup_days"],
        parameters=scheme_payload["parameters"],
        routing=scheme_payload.get("routing", {}),
        units=tuple(scheme_payload.get("units") or ()),
    )
    basin = XajBasin.model_validate_json(
        (workspace / "input/snapshot/basin.json").read_text(encoding="utf-8")
    )
    with (workspace / "input/snapshot/forcing.csv").open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        unit_ids = _forcing_layout(reader.fieldnames, scheme)
        rows = list(reader)

    dates = [date.fromisoformat(row["date"]) for row in rows]
    if len(dates) < scheme.warmup_days + 3:
        raise ValueError("insufficient warmup and leads")
    if any(right - left != timedelta(days=1) for left, right in zip(dates, dates[1:])):
        raise ValueError("forcing must contain consecutive daily rows")

    if not unit_ids:
        array = np.asarray(
            [
                [float(row["precipitation_mm_day"]), float(row["pet_mm_day"])]
                for row in rows
            ],
            dtype=float,
        )[:, None, :]
    else:
        array = np.asarray(
            [
                [
                    [
                        float(row[f"unit_{unit_id}_precipitation_mm_day"]),
                        float(row[f"unit_{unit_id}_pet_mm_day"]),
                    ]
                    for unit_id in unit_ids
                ]
                for row in rows
            ],
            dtype=float,
        )
    if not np.isfinite(array).all() or (array < 0).any():
        raise ValueError("forcing must be finite and nonnegative")
    return scheme, basin, dates, array
