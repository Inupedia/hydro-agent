import csv
import json
from pathlib import Path

from hydro_agent.graphs.hydrologist import build_hydrologist_tune_graph
from hydro_agent.modeling.hydrologist import (
    HydrologistTuneService,
    apply_product_to_native_row,
    product_from_native_row,
)


class FakePlans:
    def __init__(self, root: Path):
        self.root = root
        plan = root / "plan-demo"
        case = plan / "case"
        (case / "parameters").mkdir(parents=True)
        (case / "source").mkdir(parents=True)
        (case / "results").mkdir(parents=True)
        (case / "config").mkdir(parents=True)
        row = {
            "kc": "0.9",
            "b": "0.3",
            "imp": "0.02",
            "wum": "20",
            "wlm": "70",
            "c": "0.15",
            "sm": "25",
            "ex": "1.2",
            "ki": "0.4",
            "kg": "0.3",
            "cs": "0.65",
            "lag": "1",
            "ci": "0.85",
            "cg": "0.98",
            "wm": "150",
            "rivid": "1",
            "area": "100",
            "dp": "1",
            "ke": "24",
            "xe": "0.2",
        }
        with (case / "parameters" / "parameters.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        self._plan = {
            "plan_id": "plan-demo",
            "status": "ready",
            "boundary_reviewed": True,
            "area_km2": 100.0,
            "files": {},
        }

    def require_ready(self, plan_id: str):
        assert plan_id == "plan-demo"
        return self._plan

    def directory(self, plan_id: str) -> Path:
        return self.root / plan_id


def test_product_native_roundtrip():
    row = {"kc": "0.9", "wum": "20", "wlm": "70", "wm": "150", "b": "0.3", "imp": "0.01",
           "c": "0.1", "sm": "25", "ex": "1.2", "ki": "0.4", "kg": "0.3", "cs": "0.6",
           "lag": "1", "ci": "0.8", "cg": "0.98"}
    product = product_from_native_row(row)
    assert abs(product["DM"] - 60.0) < 1e-9
    updated = apply_product_to_native_row(row, {**product, "K": 1.0})
    assert float(updated["kc"]) == 1.0


def test_hydrologist_graph_update_and_compare_without_native_run(tmp_path, monkeypatch):
    plans = FakePlans(tmp_path / "plans")
    service = HydrologistTuneService(tmp_path / "sessions", plans)
    session = service.create(plan_id="plan-demo")
    assert session["stage"] == "created"

    def fake_run(session_id, *, label):
        return {
            "nse": 0.1 if label == "baseline" else 0.4,
            "rmse_m3s": 10.0 if label == "baseline" else 7.0,
            "pbias_percent": -20.0 if label == "baseline" else -5.0,
            "observed_peak_m3s": 50.0,
            "simulated_peak_m3s": 30.0 if label == "baseline" else 45.0,
            "count": 100,
            "label": label,
        }

    monkeypatch.setattr(service, "_run_case", fake_run)
    graph = build_hydrologist_tune_graph(service)
    baseline = graph.invoke({"session_id": session["session_id"], "step": "baseline"})
    assert baseline["session"]["stage"] == "baseline_ready"
    updated = graph.invoke(
        {
            "session_id": session["session_id"],
            "step": "update_params",
            "params": {"CS": 0.55},
            "note": "降低 CS",
        }
    )
    assert updated["session"]["stage"] == "params_updated"
    assert abs(updated["session"]["current_params"]["CS"] - 0.55) < 1e-9
    compared = graph.invoke({"session_id": session["session_id"], "step": "compare"})
    assert compared["session"]["stage"] == "compared"
    assert compared["session"]["comparison"]["improved_nse"] is True
    path = service.directory(session["session_id"]) / "session.json"
    assert path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["notes"] == ["降低 CS"]
