import csv
import json
from pathlib import Path

from hydro_agent.graphs.hydrologist import build_hydrologist_tune_graph
from hydro_agent.modeling.hydrologist import (
    HydrologistTuneService,
    recommend_unit_scheme,
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


def test_hydrologist_shared_params_apply_to_all_units(tmp_path):
    plans = FakePlans(tmp_path / "plans")
    case = plans.root / "plan-demo" / "case" / "parameters" / "parameters.csv"
    with case.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0].keys())
    second = dict(rows[0], rivid="2", area="50")
    with case.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows([rows[0], second])
    service = HydrologistTuneService(tmp_path / "sessions", plans)
    session = service.create(plan_id="plan-demo")
    assert session["unit_count"] == 2
    service._write_parameters_csv(session["session_id"], {**session["baseline_params"], "K": 1.1})
    with (service.directory(session["session_id"]) / "case" / "parameters" / "parameters.csv").open(
        encoding="utf-8", newline=""
    ) as fh:
        written = list(csv.DictReader(fh))
    assert len(written) == 2
    assert float(written[0]["kc"]) == 1.1
    assert float(written[1]["kc"]) == 1.1
    assert written[0]["rivid"] == "1"
    assert written[1]["rivid"] == "2"
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



def _unit_candidates():
    return [
        {
            "candidate_id": "units-lumped",
            "kind": "lumped",
            "unit_ids": ["basin"],
            "unit_count": 1,
            "area_distribution_km2": [100.0],
            "evidence_refs": ["drainage.area_km2"],
            "preserved_contrasts": [],
            "lost_contrasts": ["elevation"],
        },
        {
            "candidate_id": "units-topology",
            "kind": "topology_subbasin",
            "unit_ids": ["1", "2", "3"],
            "unit_count": 3,
            "area_distribution_km2": [20.0, 30.0, 50.0],
            "evidence_refs": ["topology.unit_ids", "topology.area_distribution_km2"],
            "preserved_contrasts": ["drainage_topology"],
            "lost_contrasts": [],
        },
        {
            "candidate_id": "units-heterogeneity",
            "kind": "heterogeneity_aware",
            "unit_ids": ["1", "2", "3"],
            "unit_count": 3,
            "area_distribution_km2": [20.0, 30.0, 50.0],
            "evidence_refs": ["elevation.std", "topology.unit_ids"],
            "preserved_contrasts": ["elevation"],
            "lost_contrasts": [],
        },
    ]


def test_unit_recommendation_accepts_only_registered_candidate_and_evidence():
    recommendation = recommend_unit_scheme(
        candidates=_unit_candidates(),
        spatial_profile={
            "elevation": {"status": "available"},
            "slope": {"status": "available"},
            "precipitation": {"status": "unknown"},
            "land_cover": {"status": "unknown"},
            "soil": {"status": "unknown"},
            "drainage": {"status": "available"},
        },
        proposed={
            "candidate_id": "units-heterogeneity",
            "confidence": 0.78,
            "rationale": "高程差异明显，保留现有拓扑单元。",
            "evidence_refs": ["elevation.std", "topology.unit_ids"],
            "uncertainties": ["precipitation"],
        },
    )

    assert recommendation.candidate_id == "units-heterogeneity"
    assert recommendation.source == "agent"
    assert recommendation.evidence_refs == ("elevation.std", "topology.unit_ids")
    assert "precipitation" in recommendation.uncertainties


def test_unit_recommendation_rejects_unknown_candidate_id():
    import pytest

    with pytest.raises(ValueError, match="candidate_id"):
        recommend_unit_scheme(
            candidates=_unit_candidates(),
            spatial_profile={},
            proposed={
                "candidate_id": "invented-polygon",
                "confidence": 0.9,
                "rationale": "自行切一个新边界。",
                "evidence_refs": [],
            },
        )


def test_unit_recommendation_rejects_invented_evidence_and_geometry():
    import pytest

    with pytest.raises(ValueError, match="evidence"):
        recommend_unit_scheme(
            candidates=_unit_candidates(),
            spatial_profile={},
            proposed={
                "candidate_id": "units-topology",
                "confidence": 0.8,
                "rationale": "采用已有拓扑。",
                "evidence_refs": ["soil.fake_score"],
            },
        )

    with pytest.raises(ValueError, match="geometry"):
        recommend_unit_scheme(
            candidates=_unit_candidates(),
            spatial_profile={},
            proposed={
                "candidate_id": "units-topology",
                "confidence": 0.8,
                "rationale": "采用已有拓扑。",
                "evidence_refs": ["topology.unit_ids"],
                "geometry": {"type": "Polygon", "coordinates": []},
            },
        )


def test_unit_recommendation_fallback_is_deterministic_and_surfaces_unknown_sources():
    recommendation = recommend_unit_scheme(
        candidates=_unit_candidates(),
        spatial_profile={
            "elevation": {"status": "available"},
            "slope": {"status": "available"},
            "precipitation": {"status": "unknown"},
            "land_cover": {"status": "unknown"},
            "soil": {"status": "unknown"},
            "drainage": {"status": "available"},
        },
        proposed=None,
    )

    assert recommendation.candidate_id == "units-topology"
    assert recommendation.source == "deterministic_fallback"
    assert recommendation.confidence <= 0.5
    assert set(recommendation.uncertainties) >= {"precipitation", "land_cover", "soil"}
