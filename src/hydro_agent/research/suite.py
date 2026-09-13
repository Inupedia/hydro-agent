"""Executable, auditable research-suite manifests for O/P/A/A+ experiments.

The suite is intentionally agnostic to where a cell runs. A caller injects the
isolated task executor; this module owns preregistration, fair budgets, deterministic
replicates/seeds, validation and export. Empirical superiority is never inferred
from configuration alone: only returned successful runs are summarized.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.research.benchmark import (
    BenchmarkRun,
    BenchmarkScenario,
    MetricAggregate,
    MorrisStability,
    ResearchArm,
    default_research_arms,
    morris_active_set_stability,
    validate_fair_budget,
)


class ResearchVariant(FrozenModel):
    variant_id: str = Field(min_length=1, max_length=96)
    arm: ResearchArm
    description: str = Field(min_length=1, max_length=240)


class ExperimentCell(FrozenModel):
    cell_id: str = Field(min_length=1, max_length=128)
    scenario: BenchmarkScenario
    variant_id: str = Field(min_length=1, max_length=96)
    arm: ResearchArm
    replicate: int = Field(ge=0)
    seed: int = Field(ge=0)


class ResearchSuiteManifest(FrozenModel):
    schema_version: str = "research-suite/v1"
    manifest_id: str = Field(min_length=1, max_length=96)
    evaluation_budget: int = Field(ge=1, le=10_000)
    replicates: int = Field(ge=1, le=100)
    base_seed: int = Field(ge=0)
    scenarios: tuple[BenchmarkScenario, ...]
    variants: tuple[ResearchVariant, ...]
    cells: tuple[ExperimentCell, ...]


class ResearchSuiteRun(FrozenModel):
    cell_id: str
    variant_id: str
    replicate: int
    seed: int
    result: BenchmarkRun


class ResearchSuiteSummary(FrozenModel):
    manifest_id: str
    successful_runs: int
    failed_runs: int
    variant_metrics: dict[str, dict[str, MetricAggregate]]
    win_rates_vs_o: dict[str, dict[str, float]]
    ablation_delta_vs_full: dict[str, dict[str, float]]
    morris_stability: MorrisStability | None = None


def default_research_variants(evaluation_budget: int = 512) -> tuple[ResearchVariant, ...]:
    """Core paper arms plus one-factor A+ ablations under the same budget."""

    core = {arm.arm_id: arm for arm in default_research_arms(evaluation_budget)}
    full = core["A+"]
    return (
        ResearchVariant(
            variant_id="O",
            arm=core["O"],
            description="Optimizer-only numerical calibration baseline.",
        ),
        ResearchVariant(
            variant_id="P",
            arm=core["P"],
            description="Expert-prior constrained calibration without agent diagnosis.",
        ),
        ResearchVariant(
            variant_id="A",
            arm=core["A"],
            description="Agent diagnosis with expert prior and numerical optimizer.",
        ),
        ResearchVariant(
            variant_id="A+",
            arm=full,
            description="Full agent + evidence + Morris + case-memory configuration.",
        ),
        ResearchVariant(
            variant_id="A+-no-memory",
            arm=full.model_copy(update={"use_case_memory": False}),
            description="A+ ablation with case memory disabled.",
        ),
        ResearchVariant(
            variant_id="A+-no-morris",
            arm=full.model_copy(update={"use_morris_screening": False}),
            description="A+ ablation with Morris screening disabled.",
        ),
        ResearchVariant(
            variant_id="A+-no-evidence",
            arm=full.model_copy(update={"use_evidence_builder": False}),
            description="A+ ablation with multi-scale evidence builder disabled.",
        ),
        ResearchVariant(
            variant_id="A+-no-expert",
            arm=full.model_copy(update={"use_expert_prior": False}),
            description="A+ ablation with expert prior disabled.",
        ),
    )


def _parse_day(raw: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {raw}") from exc


def validate_scenario_protocol(scenario: BenchmarkScenario) -> None:
    """Reject overlap or chronology errors before any model budget is spent."""

    cal_start = _parse_day(scenario.calibration_start, field_name="calibration_start")
    cal_end = _parse_day(scenario.calibration_end, field_name="calibration_end")
    dev_start = _parse_day(scenario.development_start, field_name="development_start")
    dev_end = _parse_day(scenario.development_end, field_name="development_end")
    final_start = _parse_day(scenario.final_test_start, field_name="final_test_start")
    final_end = _parse_day(scenario.final_test_end, field_name="final_test_end")
    if cal_end < cal_start or dev_end < dev_start or final_end < final_start:
        raise ValueError(f"scenario {scenario.scenario_id} contains an inverted window")
    if not cal_end < dev_start:
        raise ValueError(f"scenario {scenario.scenario_id} calibration/development overlap")
    if not dev_end < final_start:
        raise ValueError(f"scenario {scenario.scenario_id} development/final_test overlap")


def _cell_id(
    *,
    scenario_id: str,
    variant_id: str,
    replicate: int,
    seed: int,
    evaluation_budget: int,
) -> str:
    payload = f"{scenario_id}|{variant_id}|{replicate}|{seed}|{evaluation_budget}"
    return "cell-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def build_research_manifest(
    scenarios: Sequence[BenchmarkScenario],
    *,
    evaluation_budget: int = 512,
    replicates: int = 3,
    base_seed: int = 20260913,
    variants: Sequence[ResearchVariant] | None = None,
) -> ResearchSuiteManifest:
    if not scenarios:
        raise ValueError("research suite requires at least one scenario")
    if replicates < 1 or replicates > 100:
        raise ValueError("replicates must be between 1 and 100")
    if base_seed < 0:
        raise ValueError("base_seed must be non-negative")

    scenario_rows = tuple(scenarios)
    if len({item.scenario_id for item in scenario_rows}) != len(scenario_rows):
        raise ValueError("scenario ids must be unique")
    for scenario in scenario_rows:
        validate_scenario_protocol(scenario)

    variant_rows = tuple(variants or default_research_variants(evaluation_budget))
    if len({item.variant_id for item in variant_rows}) != len(variant_rows):
        raise ValueError("variant ids must be unique")
    budget = validate_fair_budget(tuple(item.arm for item in variant_rows))
    if budget != evaluation_budget:
        raise ValueError("variant budget does not match manifest evaluation_budget")

    cells: list[ExperimentCell] = []
    ordinal = 0
    for scenario in scenario_rows:
        for variant in variant_rows:
            for replicate in range(replicates):
                seed = base_seed + ordinal * 1009 + replicate
                cells.append(
                    ExperimentCell(
                        cell_id=_cell_id(
                            scenario_id=scenario.scenario_id,
                            variant_id=variant.variant_id,
                            replicate=replicate,
                            seed=seed,
                            evaluation_budget=evaluation_budget,
                        ),
                        scenario=scenario,
                        variant_id=variant.variant_id,
                        arm=variant.arm,
                        replicate=replicate,
                        seed=seed,
                    )
                )
            ordinal += 1

    fingerprint = {
        "schema_version": "research-suite/v1",
        "evaluation_budget": evaluation_budget,
        "replicates": replicates,
        "base_seed": base_seed,
        "scenarios": [item.model_dump(mode="json") for item in scenario_rows],
        "variants": [item.model_dump(mode="json") for item in variant_rows],
        "cells": [item.model_dump(mode="json") for item in cells],
    }
    manifest_id = "manifest-" + hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return ResearchSuiteManifest(
        manifest_id=manifest_id,
        evaluation_budget=evaluation_budget,
        replicates=replicates,
        base_seed=base_seed,
        scenarios=scenario_rows,
        variants=variant_rows,
        cells=tuple(cells),
    )


class ResearchSuiteRunner:
    """Execute preregistered cells through an injected isolated-task executor."""

    def __init__(self, executor: Callable[[ExperimentCell], BenchmarkRun]):
        self.executor = executor

    def execute(self, manifest: ResearchSuiteManifest) -> tuple[ResearchSuiteRun, ...]:
        rows: list[ResearchSuiteRun] = []
        for cell in manifest.cells:
            result = self.executor(cell)
            if result.scenario_id != cell.scenario.scenario_id:
                raise ValueError(f"executor changed scenario for {cell.cell_id}")
            if result.arm_id != cell.arm.arm_id:
                raise ValueError(f"executor changed arm for {cell.cell_id}")
            if result.evaluation_budget != manifest.evaluation_budget:
                raise ValueError(f"executor changed budget for {cell.cell_id}")
            if result.model_evaluations > result.evaluation_budget:
                raise ValueError(f"executor exceeded budget for {cell.cell_id}")
            if result.status == "succeeded" and not result.final_test_consumed:
                raise ValueError(f"successful run did not consume final_test for {cell.cell_id}")
            rows.append(
                ResearchSuiteRun(
                    cell_id=cell.cell_id,
                    variant_id=cell.variant_id,
                    replicate=cell.replicate,
                    seed=cell.seed,
                    result=result,
                )
            )
        return tuple(rows)


def _iqr(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    qs = statistics.quantiles(sorted(float(item) for item in values), n=4, method="inclusive")
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


def _metric_map(result: BenchmarkRun) -> dict[str, float]:
    out = {f"rolling_{key}": float(value) for key, value in result.rolling_metrics.items()}
    out.update(
        {f"continuous_{key}": float(value) for key, value in result.continuous_metrics.items()}
    )
    return out


def summarize_research_suite(
    manifest: ResearchSuiteManifest,
    runs: Sequence[ResearchSuiteRun],
) -> ResearchSuiteSummary:
    known_cells = {cell.cell_id: cell for cell in manifest.cells}
    if len({run.cell_id for run in runs}) != len(runs):
        raise ValueError("suite runs contain duplicate cell ids")
    for run in runs:
        cell = known_cells.get(run.cell_id)
        if cell is None:
            raise ValueError(f"run references unknown cell: {run.cell_id}")
        if run.variant_id != cell.variant_id or run.replicate != cell.replicate:
            raise ValueError(f"run metadata does not match manifest: {run.cell_id}")

    successful = [run for run in runs if run.result.status == "succeeded"]
    variant_values: dict[str, dict[str, list[float]]] = {}
    for run in successful:
        store = variant_values.setdefault(run.variant_id, {})
        for metric, value in _metric_map(run.result).items():
            store.setdefault(metric, []).append(value)
    variant_metrics = {
        variant: {
            metric: _aggregate_metric(metric, values)
            for metric, values in sorted(metric_map.items())
        }
        for variant, metric_map in sorted(variant_values.items())
    }

    index = {
        (run.result.scenario_id, run.variant_id, run.replicate): run
        for run in successful
    }
    higher_is_better = ("rolling_NSE", "rolling_KGE", "continuous_NSE", "continuous_KGE")
    win_rates: dict[str, dict[str, float]] = {}
    for variant in sorted(variant_values):
        if variant == "O" or variant.startswith("A+-"):
            continue
        metric_wins: dict[str, float] = {}
        for metric in higher_is_better:
            wins = 0
            pairs = 0
            for scenario in manifest.scenarios:
                for replicate in range(manifest.replicates):
                    baseline = index.get((scenario.scenario_id, "O", replicate))
                    candidate = index.get((scenario.scenario_id, variant, replicate))
                    if baseline is None or candidate is None:
                        continue
                    base_metrics = _metric_map(baseline.result)
                    cand_metrics = _metric_map(candidate.result)
                    if metric not in base_metrics or metric not in cand_metrics:
                        continue
                    pairs += 1
                    if cand_metrics[metric] > base_metrics[metric]:
                        wins += 1
            if pairs:
                metric_wins[metric] = float(wins / pairs)
        win_rates[variant] = metric_wins

    ablation_delta: dict[str, dict[str, float]] = {}
    for variant in sorted(item for item in variant_values if item.startswith("A+-")):
        deltas: dict[str, list[float]] = {}
        for scenario in manifest.scenarios:
            for replicate in range(manifest.replicates):
                full = index.get((scenario.scenario_id, "A+", replicate))
                ablated = index.get((scenario.scenario_id, variant, replicate))
                if full is None or ablated is None:
                    continue
                full_metrics = _metric_map(full.result)
                ablated_metrics = _metric_map(ablated.result)
                for metric in higher_is_better:
                    if metric in full_metrics and metric in ablated_metrics:
                        deltas.setdefault(metric, []).append(
                            ablated_metrics[metric] - full_metrics[metric]
                        )
        ablation_delta[variant] = {
            metric: float(statistics.fmean(values))
            for metric, values in sorted(deltas.items())
            if values
        }

    active_sets = [
        run.result.active_parameters
        for run in successful
        if run.variant_id == "A+" and run.result.active_parameters
    ]
    morris = morris_active_set_stability(active_sets) if active_sets else None
    return ResearchSuiteSummary(
        manifest_id=manifest.manifest_id,
        successful_runs=len(successful),
        failed_runs=len(runs) - len(successful),
        variant_metrics=variant_metrics,
        win_rates_vs_o=win_rates,
        ablation_delta_vs_full=ablation_delta,
        morris_stability=morris,
    )


def write_research_suite_bundle(
    manifest: ResearchSuiteManifest,
    runs: Sequence[ResearchSuiteRun],
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    """Write deterministic preregistration, empirical rows and aggregate summary."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "research-manifest.json"
    runs_path = output_dir / "research-runs.json"
    summary_path = output_dir / "research-summary.json"
    summary = summarize_research_suite(manifest, runs)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    runs_path.write_text(
        json.dumps(
            [run.model_dump(mode="json") for run in runs],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path, runs_path, summary_path
