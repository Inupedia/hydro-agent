from __future__ import annotations

import json

import pytest

from hydro_agent.research.benchmark import BenchmarkRun, BenchmarkScenario
from hydro_agent.research.suite import (
    ResearchSuiteRunner,
    build_research_manifest,
    summarize_research_suite,
    validate_scenario_protocol,
    write_research_suite_bundle,
)


def _scenario(name: str, year: int = 2000) -> BenchmarkScenario:
    return BenchmarkScenario(
        scenario_id=name,
        basin_id="demo",
        calibration_start=f"{year}-01-01",
        calibration_end=f"{year}-12-31",
        development_start=f"{year + 1}-01-01",
        development_end=f"{year + 1}-01-31",
        final_test_start=f"{year + 1}-02-01",
        final_test_end=f"{year + 1}-02-28",
        tags=("normal-year",),
    )


def test_manifest_is_deterministic_and_expands_core_ablation_replicates():
    scenarios = (_scenario("s1"), _scenario("s2", 2002))
    left = build_research_manifest(
        scenarios,
        evaluation_budget=128,
        replicates=2,
        base_seed=42,
    )
    right = build_research_manifest(
        scenarios,
        evaluation_budget=128,
        replicates=2,
        base_seed=42,
    )

    assert left.manifest_id == right.manifest_id
    assert left.model_dump(mode="json") == right.model_dump(mode="json")
    assert len(left.variants) == 8
    assert {item.variant_id for item in left.variants} == {
        "O",
        "P",
        "A",
        "A+",
        "A+-no-memory",
        "A+-no-morris",
        "A+-no-evidence",
        "A+-no-expert",
    }
    assert len(left.cells) == 2 * 8 * 2
    assert {cell.arm.evaluation_budget for cell in left.cells} == {128}
    assert len({cell.cell_id for cell in left.cells}) == len(left.cells)


def test_protocol_preregistration_rejects_window_leakage():
    scenario = BenchmarkScenario(
        scenario_id="leaky",
        basin_id="demo",
        calibration_start="2000-01-01",
        calibration_end="2000-12-31",
        development_start="2000-12-31",
        development_end="2001-01-31",
        final_test_start="2001-02-01",
        final_test_end="2001-02-28",
    )
    with pytest.raises(ValueError, match="overlap"):
        validate_scenario_protocol(scenario)
    with pytest.raises(ValueError, match="overlap"):
        build_research_manifest((scenario,), evaluation_budget=64)


def test_runner_enforces_identity_budget_and_final_test_consumption():
    manifest = build_research_manifest((_scenario("s1"),), evaluation_budget=32, replicates=1)

    def good(cell):
        return BenchmarkRun(
            scenario_id=cell.scenario.scenario_id,
            arm_id=cell.arm.arm_id,
            evaluation_budget=cell.arm.evaluation_budget,
            model_evaluations=30,
            final_test_consumed=True,
            rolling_metrics={"NSE": 0.2, "KGE": 0.1},
            continuous_metrics={"NSE": 0.1, "KGE": 0.0},
            active_parameters=("K", "SM") if cell.variant_id == "A+" else (),
        )

    rows = ResearchSuiteRunner(good).execute(manifest)
    assert len(rows) == len(manifest.cells)
    assert all(row.result.model_evaluations <= 32 for row in rows)

    def leaks_final_test(cell):
        result = good(cell)
        return result.model_copy(update={"final_test_consumed": False})

    with pytest.raises(ValueError, match="did not consume final_test"):
        ResearchSuiteRunner(leaks_final_test).execute(manifest)


def test_summary_pairs_replicates_and_reports_ablation_delta_and_morris(tmp_path):
    manifest = build_research_manifest((_scenario("s1"),), evaluation_budget=16, replicates=2)

    def executor(cell):
        nse_by_variant = {
            "O": 0.20,
            "P": 0.25,
            "A": 0.30,
            "A+": 0.40,
            "A+-no-memory": 0.35,
            "A+-no-morris": 0.32,
            "A+-no-evidence": 0.31,
            "A+-no-expert": 0.33,
        }
        bump = cell.replicate * 0.01
        nse = nse_by_variant[cell.variant_id] + bump
        return BenchmarkRun(
            scenario_id=cell.scenario.scenario_id,
            arm_id=cell.arm.arm_id,
            evaluation_budget=cell.arm.evaluation_budget,
            model_evaluations=16,
            final_test_consumed=True,
            rolling_metrics={"NSE": nse, "KGE": nse - 0.05},
            continuous_metrics={"NSE": nse - 0.10, "KGE": nse - 0.15},
            active_parameters=(
                ("K", "SM", "KI") if cell.replicate == 0 else ("K", "SM", "KG")
            )
            if cell.variant_id == "A+"
            else (),
        )

    runs = ResearchSuiteRunner(executor).execute(manifest)
    summary = summarize_research_suite(manifest, runs)
    assert summary.successful_runs == len(manifest.cells)
    assert summary.failed_runs == 0
    assert summary.variant_metrics["A+"]["rolling_NSE"].mean == pytest.approx(0.405)
    assert summary.win_rates_vs_o["A+"]["rolling_NSE"] == pytest.approx(1.0)
    assert summary.ablation_delta_vs_full["A+-no-memory"]["rolling_NSE"] == pytest.approx(-0.05)
    assert summary.morris_stability is not None
    assert summary.morris_stability.active_frequency["K"] == pytest.approx(1.0)
    assert summary.morris_stability.active_frequency["SM"] == pytest.approx(1.0)

    manifest_path, runs_path, summary_path = write_research_suite_bundle(manifest, runs, tmp_path)
    assert json.loads(manifest_path.read_text())["manifest_id"] == manifest.manifest_id
    assert len(json.loads(runs_path.read_text())) == len(runs)
    assert json.loads(summary_path.read_text())["successful_runs"] == len(runs)
