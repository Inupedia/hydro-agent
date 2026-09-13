from __future__ import annotations

import pytest

from hydro_agent.research.benchmark import (
    BenchmarkHarness,
    BenchmarkRun,
    BenchmarkScenario,
    ResearchArm,
    aggregate_benchmark,
    default_research_arms,
    morris_active_set_stability,
    validate_fair_budget,
)


def _scenario(name: str) -> BenchmarkScenario:
    return BenchmarkScenario(
        scenario_id=name,
        basin_id="demo",
        calibration_start="2000-01-01",
        calibration_end="2000-12-31",
        development_start="2001-01-01",
        development_end="2001-01-31",
        final_test_start="2001-02-01",
        final_test_end="2001-02-28",
        tags=("normal-year",),
    )


def test_default_arms_use_one_hard_budget_and_expected_capabilities():
    arms = default_research_arms(512)
    assert validate_fair_budget(arms) == 512
    assert [arm.arm_id for arm in arms] == ["O", "P", "A", "A+"]
    assert arms[0].use_agent_diagnosis is False
    assert arms[1].use_expert_prior is True
    assert arms[2].use_agent_diagnosis is True
    assert arms[3].use_evidence_builder is True
    assert arms[3].use_morris_screening is True
    assert arms[3].use_case_memory is True


def test_fair_budget_rejects_apples_to_oranges_comparison():
    with pytest.raises(ValueError, match="same evaluation budget"):
        validate_fair_budget(
            (
                ResearchArm(arm_id="O", evaluation_budget=256, optimizer="sce-ua"),
                ResearchArm(arm_id="A", evaluation_budget=512, optimizer="dds"),
            )
        )


def test_harness_checks_executor_budget_and_identity():
    scenario = _scenario("s1")
    arm = default_research_arms(100)[0]

    def executor(scenario, arm):
        return BenchmarkRun(
            scenario_id=scenario.scenario_id,
            arm_id=arm.arm_id,
            evaluation_budget=arm.evaluation_budget,
            model_evaluations=99,
            rolling_metrics={"NSE": 0.4},
            continuous_metrics={"NSE": 0.3},
        )

    rows = BenchmarkHarness(executor).execute((scenario,), (arm,))
    assert len(rows) == 1
    assert rows[0].model_evaluations == 99

    def over_budget(scenario, arm):
        return BenchmarkRun(
            scenario_id=scenario.scenario_id,
            arm_id=arm.arm_id,
            evaluation_budget=arm.evaluation_budget,
            model_evaluations=101,
        )

    with pytest.raises(ValueError, match="exceeded"):
        BenchmarkHarness(over_budget).execute((scenario,), (arm,))


def test_aggregate_is_empirical_and_paired_against_optimizer_only():
    rows = (
        BenchmarkRun(
            scenario_id="s1",
            arm_id="O",
            evaluation_budget=100,
            model_evaluations=100,
            rolling_metrics={"NSE": 0.2, "KGE": 0.1},
            continuous_metrics={"NSE": 0.1, "KGE": 0.0},
        ),
        BenchmarkRun(
            scenario_id="s1",
            arm_id="A+",
            evaluation_budget=100,
            model_evaluations=95,
            rolling_metrics={"NSE": 0.4, "KGE": 0.3},
            continuous_metrics={"NSE": 0.3, "KGE": 0.2},
        ),
        BenchmarkRun(
            scenario_id="s2",
            arm_id="O",
            evaluation_budget=100,
            model_evaluations=100,
            rolling_metrics={"NSE": 0.5, "KGE": 0.4},
            continuous_metrics={"NSE": 0.4, "KGE": 0.3},
        ),
        BenchmarkRun(
            scenario_id="s2",
            arm_id="A+",
            evaluation_budget=100,
            model_evaluations=98,
            rolling_metrics={"NSE": 0.3, "KGE": 0.2},
            continuous_metrics={"NSE": 0.2, "KGE": 0.1},
        ),
    )

    summary = aggregate_benchmark(rows)
    assert summary.scenario_count == 2
    assert summary.metrics["A+"]["rolling_NSE"].mean == pytest.approx(0.35)
    assert summary.win_rates_vs_o["A+"]["rolling_NSE"] == pytest.approx(0.5)
    assert summary.win_rates_vs_o["A+"]["continuous_KGE"] == pytest.approx(0.5)


def test_morris_stability_reports_frequency_and_pairwise_jaccard():
    result = morris_active_set_stability(
        (
            ("K", "SM", "KI"),
            ("K", "SM", "KG"),
            ("K", "SM"),
        )
    )

    assert result.run_count == 3
    assert result.active_frequency["K"] == pytest.approx(1.0)
    assert result.active_frequency["SM"] == pytest.approx(1.0)
    assert result.active_frequency["KI"] == pytest.approx(1 / 3)
    assert result.mean_pairwise_jaccard is not None
    assert 0.0 <= result.min_pairwise_jaccard <= result.mean_pairwise_jaccard <= 1.0
