"""Shared sandbox I/O for model plugins (scheme + basin + daily forcing)."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from hydro_agent.models.forcing import FORCING_FIELD_BY_NAME, load_forcing_matrix


def load_workspace_rows(workspace: Path) -> tuple[dict, dict, list[date], list[dict[str, str]]]:
    scheme_payload, basin_payload, dates, rows, _fieldnames = load_workspace_table(workspace)
    return scheme_payload, basin_payload, dates, rows


def load_workspace_table(
    workspace: Path,
) -> tuple[dict, dict, list[date], list[dict[str, str]], list[str]]:
    scheme_payload = json.loads((workspace / "input/scheme/scheme.json").read_text(encoding="utf-8"))
    basin_payload = json.loads(
        (workspace / "input/snapshot/basin.json").read_text(encoding="utf-8")
    )
    with (workspace / "input/snapshot/forcing.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            raise ValueError("invalid forcing columns")
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    dates = [date.fromisoformat(row["date"]) for row in rows]
    warmup_days = int(scheme_payload["warmup_days"])
    if len(dates) < warmup_days + 3:
        raise ValueError("insufficient warmup and leads")
    if any(later - earlier != timedelta(days=1) for earlier, later in zip(dates, dates[1:])):
        raise ValueError("forcing must contain consecutive daily rows")
    return scheme_payload, basin_payload, dates, rows, fieldnames


def load_workspace_forcing(
    workspace: Path,
    *,
    required_forcings: Sequence[str],
):
    scheme_payload, basin_payload, dates, rows, fieldnames = load_workspace_table(workspace)
    required_cols = [FORCING_FIELD_BY_NAME[name] for name in required_forcings]
    if any(col not in fieldnames for col in required_cols):
        raise ValueError("forcing csv missing required column")
    array = load_forcing_matrix(rows, required_forcings=required_forcings)
    return scheme_payload, basin_payload, dates, array
