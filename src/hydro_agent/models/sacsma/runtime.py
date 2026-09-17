"""SAC-SMA forecast runtime: NOAA-OWP core + daily routing."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from hydro_agent.execution.contracts import ExecutionRequest

from .contracts import SacSmaForecastRow
from .conversion import load_sacsma_inputs
from .engine import MODEL_SHA256, MODEL_VERSION, simulate


def run(workspace: Path):
    import numpy as np

    request = ExecutionRequest.model_validate_json(
        (workspace / "execution-manifest.json").read_text(encoding="utf-8")
    )
    if request.model_id != "sac-sma" or request.capability != "forecast":
        raise ValueError("unsupported SAC-SMA execution")
    scheme, basin, dates, inputs = load_sacsma_inputs(workspace)
    issue = datetime.fromisoformat(request.issue_time)
    if issue.tzinfo is None:
        raise ValueError("issue time requires timezone")
    issue_date = issue.astimezone(ZoneInfo(basin.day_timezone)).date()
    if dates[-3:] != [issue_date + timedelta(days=i) for i in (1, 2, 3)]:
        raise ValueError("forcing targets do not match issue date")
    values = simulate(scheme, basin, inputs)
    if len(values) < 3 or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid SAC-SMA numerical result")
    forecast = [
        SacSmaForecastRow(
            lead=i,
            target_date=dates[-4 + i],
            value=float(values[-4 + i]),
        ).model_dump(mode="json")
        for i in (1, 2, 3)
    ]
    with (workspace / "output/forecast.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["lead", "target_date", "value"])
        writer.writeheader()
        writer.writerows(forecast)
    payload = dict(
        model_id="sac-sma",
        scheme_id=request.scheme_id,
        data_snapshot_id=request.data_snapshot_id,
        issue_time=request.issue_time,
        unit="m3/s",
        forecast=forecast,
        model_version=MODEL_VERSION,
        model_source_sha256=MODEL_SHA256,
        day_timezone=basin.day_timezone,
    )
    (workspace / "output/result.json").write_text(
        json.dumps(payload, sort_keys=True, allow_nan=False), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace)


if __name__ == "__main__":
    main()
