"""Plugin-generic forecast runtime. Adapters pass ``request.model_id`` via the workspace."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from hydro_agent.execution.contracts import ExecutionRequest, FrozenModel
from hydro_agent.models.registry import default_model_registry
from hydro_agent.models.workspace_io import load_workspace_forcing


class ForecastRow(FrozenModel):
    lead: Literal[1, 2, 3]
    target_date: date
    value: float = Field(ge=0, allow_inf_nan=False)


def run(workspace: Path) -> None:
    import numpy as np

    request = ExecutionRequest.model_validate_json(
        (workspace / "execution-manifest.json").read_text(encoding="utf-8")
    )
    if request.capability != "forecast" or request.policy.device != "cpu":
        raise ValueError("unsupported forecast execution")
    plugin = default_model_registry().get(request.model_id)
    scheme_payload, basin_payload, dates, inputs = load_workspace_forcing(
        workspace,
        required_forcings=plugin.descriptor.required_forcings,
    )
    plugin.validate_scheme(scheme_payload)
    issue = datetime.fromisoformat(request.issue_time)
    if issue.tzinfo is None:
        raise ValueError("issue time requires timezone")
    day_timezone = str(basin_payload.get("day_timezone") or "UTC")
    issue_date = issue.astimezone(ZoneInfo(day_timezone)).date()
    if dates[-3:] != [issue_date + timedelta(days=i) for i in (1, 2, 3)]:
        raise ValueError("forcing targets do not match issue date")
    values = plugin.simulate(scheme_payload, basin_payload, inputs)
    if len(values) < 3 or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid numerical result")
    forecast = [
        ForecastRow(
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
        model_id=request.model_id,
        scheme_id=request.scheme_id,
        data_snapshot_id=request.data_snapshot_id,
        issue_time=request.issue_time,
        unit="m3/s",
        forecast=forecast,
        model_version=getattr(plugin, "MODEL_VERSION", plugin.descriptor.model_id),
        model_source_sha256=getattr(plugin, "MODEL_SHA256", ""),
        day_timezone=day_timezone,
    )
    manifest_path = workspace / "input/snapshot/snapshot-manifest.json"
    if not manifest_path.exists():
        manifest_path = workspace / "input/snapshot/manifest.json"
    if manifest_path.exists():
        payload["forcing_mode"] = json.loads(manifest_path.read_text(encoding="utf-8"))["context"][
            "forcing_mode"
        ]
    (workspace / "output/result.json").write_text(
        json.dumps(payload, sort_keys=True, allow_nan=False), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace)


if __name__ == "__main__":
    main()
