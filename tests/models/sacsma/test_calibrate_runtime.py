"""Fixture-backed SAC-SMA calibration runtime smoke test (16 official parameters)."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import date
from pathlib import Path

from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest
from hydro_agent.models.sacsma.adapter import SacSmaRuntimeAdapter
from hydro_agent.models.sacsma.calibrate_runtime import run as calibrate_run

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sacsma"

OFFICIAL_16 = {
    "UZTWM",
    "UZFWM",
    "UZK",
    "PCTIM",
    "ADIMP",
    "RIVA",
    "ZPERC",
    "REXP",
    "LZTWM",
    "LZFSM",
    "LZFPM",
    "LZSK",
    "LZPK",
    "PFREE",
    "SIDE",
    "RSERV",
}


def test_sacsma_calibrate_runtime_smoke(tmp_path):
    snapshot = tmp_path / "input" / "snapshot"
    scheme = tmp_path / "input" / "scheme"
    (tmp_path / "output").mkdir(parents=True)
    snapshot.mkdir(parents=True)
    scheme.mkdir(parents=True)
    shutil.copy(FIXTURES / "forcing.csv", snapshot / "forcing.csv")
    shutil.copy(FIXTURES / "basin.json", snapshot / "basin.json")
    shutil.copy(FIXTURES / "scheme.json", scheme / "scheme.json")

    with (FIXTURES / "forcing.csv").open(encoding="utf-8", newline="") as handle:
        dates = [date.fromisoformat(row["date"]) for row in csv.DictReader(handle)]
    with (snapshot / "streamflow.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "discharge_m3s"])
        writer.writeheader()
        for index, day in enumerate(dates):
            writer.writerow({"date": day.isoformat(), "discharge_m3s": 8.0 + (index % 7) * 0.4})

    request = ExecutionRequest(
        task_id="task-sac-sma",
        action_run_id="run-cal",
        model_id="sac-sma",
        capability="calibrate",
        data_snapshot_id="snapshot-1",
        scheme_id="scheme-base",
        issue_time=None,
        parameters={
            "strategy_id": "sac-sma-bounded-v1",
            "param_groups": ["upper", "lower", "percolation", "routing", "evap", "baseflow"],
            "objective": "nse",
            "evaluation_budget": 8,
        },
        policy=ExecutionPolicy(
            timeout_seconds=60, network_access=False, max_output_bytes=2_000_000, device="cpu"
        ),
    )
    (tmp_path / "execution-manifest.json").write_text(request.model_dump_json(), encoding="utf-8")

    adapter = SacSmaRuntimeAdapter()
    assert "calibrate_runtime" in " ".join(adapter.command(request, tmp_path))

    result = calibrate_run(tmp_path)
    assert result["model_id"] == "sac-sma"
    assert result["strategy_id"] == "sac-sma-bounded-v1"
    assert set(result["candidate_parameters"]) == OFFICIAL_16
    payload = json.loads((tmp_path / "output" / "result.json").read_text(encoding="utf-8"))
    assert payload["model_evaluations"] <= 8
    assert payload["model_evaluations"] >= 1
