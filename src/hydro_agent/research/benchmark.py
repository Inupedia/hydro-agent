"""Fair O/P/A/A+ calibration benchmark and multi-scenario aggregation.

The harness separates *running experiments* from *claiming empirical superiority*.
It enforces equal declared model-evaluation budgets and aggregates only returned
run records.  A caller supplies the executor that creates isolated Hydro-Agent
tasks, so every arm can preserve calibration/development/final-test boundaries.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable, Sequence
from itertools import combinations
from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel

ArmId = Literal["O", "P", "A", "A+"]


class ResearchArm(FrozenModel):
    arm_id: ArmId
    evaluation_budget: int = Field(ge=1, le=10_000)
    optimizer: Literal["dds", "sce-ua"]
    use_expert_prior: bool = False
    use_agent_diagnosis: bool = False
    use_evidence_builder: bool = False
    use_morris_screening: bool = False
    use_case_memory: bool = False


class BenchmarkScenario(FrozenModel):
    scenario_id: str = Field(min_length=1)
    basin_id: str = Field(min_length=1)
    calibration_start: str
    calibration_end: str
    development_start: str
    development_end: str
    final_test_start: str
    final_test_end: str
    tags: tuple[str, ...] = ()


class BenchmarkRun(FrozenModel):
    scenario_id: str
    arm_id: ArmId
    evaluation_budget: int = Field(ge=1)
    model_evaluations: int = Field(ge=0)
    final_test_consumed: bool = True
    rolling_metrics: dict[str, float] = Field(default_factory=dict)
    continuous_metrics: dict[str, float] = Field(default_factory=dict)
    active_parameters: tuple[str, ...] = ()
    status: Literal["succeeded", "failed", "insufficient_data"] = "succeeded"
    notes: tuple[str, ...] = ()


class MetricAggregate(FrozenModel):
    metric: str
    sample_count: int
    mean: float
    median: float
    minimum: float
    maximum: float
    iqr: float


class BenchmarkAggregate(FrozenModel):
    arms: tuple[ArmId, ...]
    scenario_count: int
    metrics: dict[str, dict[str, MetricAggregate]]
    win_rates_vs_o: dict[str, dict[str, float]]


class MorrisStability(FrozenModel):
    run_count: int
    active_frequency: dict[str, float]
    mean_pairwise_jaccard: float | None = None
    min_pairwise_jaccard: float | None = None


def default_research_arms(evaluation_budget: int = 512) -> tuple[ResearchArm, ...]:
    """Canonical paper arms under one shared hard model-evaluation budget."""

    return (
        ResearchArm(
            arm_id="O",
            evaluation_budget=evaluation_budget,
            optimizer="sce-ua",
        ),
        ResearchArm(
            arm_id="P",
            evaluation_budget=evaluation_budget,
            optimizer="dds",
            use_expert_prior=True,
        ),
        ResearchArm(
            arm_id="A",
            evaluation_budget=evaluation_budget,
            optimizer="dds",
            use_expert_prior=True,
            use_agent_diagnosis=True,
        ),
        ResearchArm(
            arm_id="A+",
            evaluation_budget=evaluation_budget,
            optimizer="dds",
            use_expert_prior=True,
            use_agent_diagnosis=True,
            use_evidence_builder=True,
            use_morris_screening=True,
            use_case_memory=True,
        ),
    )


def validate_fair_budget(arms: Sequence[ResearchArm]) -> int:
    if not arms:
        raise ValueError("benchmark requires at least one arm")
    budgets = {int(arm.evaluation_budget) for arm in arms}
    if len(budgets) != 1:
        raise ValueError("all benchmark arms must share the same evaluation budget")
    return next(iter(budgets))


class BenchmarkHarness:
    """Execute an arm/scenario matrix through an injected isolated-task runner."""

    def __init__(self, executor: Callable[[BenchmarkScenario, ResearchArm], BenchmarkRun]):
        self.executor = executor

    def execute(
        self,
        scenarios: Sequence[BenchmarkScenario],
        arms: Sequence[ResearchArm],
    ) -> tuple[BenchmarkRun, ...]:
        validate_fair_budget(arms)
        if not scenarios:
            raise ValueError("benchmark requires at least one scenario")
        rows: list[BenchmarkRun] = []
        for scenario in scenarios:
            for arm in arms:
                run = self.executor(scenario, arm)
                if run.scenario_id != scenario.scenario_id or run.arm_id != arm.arm_id:
                    raise ValueError("benchmark executor returned mismatched scenario/arm")
                if run.evaluation_budget != arm.evaluation_budget:
                    raise ValueError("benchmark executor changed the declared evaluation budget")
                if run.model_evaluations > run.evaluation_budget:
                    raise ValueError("benchmark run exceeded its hard evaluation budget")
                rows.append(run)
        return tuple(rows)


def _iqr(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    ordered = sorted(float(value) for value in values)
    # Inclusive quartiles are deterministic and behave sensibly for small N.
    qs = statistics.quantiles(ordered, n=4, method="inclusive")
    return float(qs[2] - qs[0])


def _aggregate_metric(metric: str, values: Sequence[float]) -> MetricAggregate:
    return MetricAggregate(
        metric=metric,
        sample_count=len(values),
        mean=float(statistics.fmean(values)),
        median=float(statistics.median(values)),
        minimum=float(min(values)),
        maximum=float(max(values)),
        iqr=_iqr(values),
    )


def aggregate_benchmark(runs: Sequence[BenchmarkRun]) -> BenchmarkAggregate:
    """Aggregate successful empirical runs without fabricating missing arms/scenarios."""

    successful = [row for row in runs if row.status == "succeeded"]
    if not successful:
        raise ValueError("no successful benchmark runs to aggregate")
    scenario_ids = sorted({row.scenario_id for row in successful})
    arms = tuple(sorted({row.arm_id for row in successful}, key=("O", "P", "A", "A+").index))

    by_arm_metric: dict[str, dict[str, list[float]]] = {}
    for row in successful:
        store = by_arm_metric.setdefault(row.arm_id, {})
        for prefix, payload in (
            ("rolling", row.rolling_metrics),
            ("continuous", row.continuous_metrics),
        ):
            for key, value in payload.items():
                store.setdefault(f"{prefix}_{key}", []).append(float(value))

    metrics: dict[str, dict[str, MetricAggregate]] = {}
    for arm, metric_map in by_arm_metric.items():
        metrics[arm] = {
            name: _aggregate_metric(name, values) for name, values in sorted(metric_map.items())
        }

    # Win rate is paired by scenario against optimizer-only O. Higher is better
    # only for skill metrics with explicit direction. Error/bias ratios are not
    # silently interpreted as wins here.
    higher_is_better = {"rolling_NSE", "rolling_KGE", "continuous_NSE", "continuous_KGE"}
    run_index = {(row.scenario_id, row.arm_id): row for row in successful}
    win_rates: dict[str, dict[str, float]] = {}
    for arm in arms:
        if arm == "O":
            continue
        arm_wins: dict[str, float] = {}
        for metric in sorted(higher_is_better):
            prefix, key = metric.split("_", 1)
            wins = 0
            pairs = 0
            for scenario_id in scenario_ids:
                baseline = run_index.get((scenario_id, "O"))
                candidate = run_index.get((scenario_id, arm))
                if baseline is None or candidate is None:
                    continue
                base_map = baseline.rolling_metrics if prefix == "rolling" else baseline.continuous_metrics
                cand_map = candidate.rolling_metrics if prefix == "rolling" else candidate.continuous_metrics
                if key not in base_map or key not in cand_map:
                    continue
                pairs += 1
                if float(cand_map[key]) > float(base_map[key]):
                    wins += 1
            if pairs:
                arm_wins[metric] = float(wins / pairs)
        win_rates[arm] = arm_wins

    return BenchmarkAggregate(
        arms=arms,
        scenario_count=len(scenario_ids),
        metrics=metrics,
        win_rates_vs_o=win_rates,
    )


def morris_active_set_stability(active_sets: Sequence[Sequence[str]]) -> MorrisStability:
    """Summarize repeated Morris screenings without claiming causal importance."""

    if not active_sets:
        raise ValueError("at least one Morris active set is required")
    normalized = [frozenset(str(item) for item in values) for values in active_sets]
    counts: Counter[str] = Counter()
    for values in normalized:
        counts.update(values)
    run_count = len(normalized)
    frequency = {name: float(count / run_count) for name, count in sorted(counts.items())}

    similarities: list[float] = []
    for left, right in combinations(normalized, 2):
        union = left | right
        similarities.append(float(len(left & right) / len(union)) if union else 1.0)
    return MorrisStability(
        run_count=run_count,
        active_frequency=frequency,
        mean_pairwise_jaccard=(float(statistics.fmean(similarities)) if similarities else None),
        min_pairwise_jaccard=(float(min(similarities)) if similarities else None),
    )
