"""Structured experiment planning and trial ledger for calibration research.

The planner stores decisions that are safe to audit: hypothesis identifiers,
evidence references, registered strategy ids and budgets.  It intentionally does
not store private chain-of-thought or continuous parameter vectors.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Mapping, Sequence

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry

CanonicalObjective = Literal["nse", "kge", "peak"]
TrialOutcome = Literal["supported", "refuted", "inconclusive"]


def canonical_objective(value: str | None) -> CanonicalObjective:
    """Normalize the historical ``composite`` label to the metric it actually uses."""

    raw = str(value or "nse").strip().lower()
    if raw == "composite":
        return "kge"
    if raw not in {"nse", "kge", "peak"}:
        raise ValueError(f"unsupported objective: {value}")
    return raw  # type: ignore[return-value]


def runtime_objective(value: str | None) -> str:
    """Translate canonical objective to the current XAJ runtime compatibility label."""

    canonical = canonical_objective(value)
    return "composite" if canonical == "kge" else canonical


class HydrologicHypothesis(FrozenModel):
    hypothesis_id: str = Field(min_length=1, max_length=96)
    category: Literal["DATA", "TIMING", "STATE", "FORCING", "MODEL", "RESOURCE", "UNKNOWN"]
    phenomenon: str = Field(min_length=1, max_length=400)
    testable_claim: str = Field(min_length=1, max_length=600)
    evidence_refs: tuple[str, ...] = ()
    target_metrics: tuple[str, ...] = ()


class ExperimentPlan(FrozenModel):
    plan_id: str = Field(min_length=1, max_length=96)
    hypothesis_id: str = Field(min_length=1, max_length=96)
    strategy_id: str = Field(min_length=1)
    optimizer: Literal["dds", "sce-ua", "random-search", "manual"]
    objective: CanonicalObjective
    param_groups: tuple[Literal["evap", "runoff", "routing"], ...]
    evaluation_budget: int = Field(ge=1, le=10_000)
    evidence_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    planner: Literal["agent", "expert", "benchmark"] = "agent"

    @property
    def experiment_signature(self) -> str:
        payload = {
            "strategy_id": self.strategy_id,
            "objective": self.objective,
            "param_groups": list(self.param_groups),
            "evaluation_budget": self.evaluation_budget,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]


class TrialRecord(FrozenModel):
    trial_id: str = Field(min_length=1, max_length=128)
    plan_id: str = Field(min_length=1, max_length=96)
    experiment_signature: str = Field(min_length=1)
    strategy_id: str
    base_scheme_id: str | None = None
    candidate_scheme_id: str | None = None
    action_run_id: str | None = None
    model_evaluations: int = Field(default=0, ge=0)
    development_gate: str = "NOT_EVALUATED"
    adoption_status: str = "NOT_EVALUATED"
    qualification_status: str = "NOT_EVALUATED"
    metric_deltas: dict[str, float] = Field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    hypothesis_outcome: TrialOutcome = "inconclusive"
    reason_codes: tuple[str, ...] = ()


class TrialLedger:
    """Append-only in-memory ledger; callers may serialize ``as_dict`` as an artifact."""

    def __init__(self, records: Sequence[TrialRecord] = ()) -> None:
        self._records = list(records)
        self._ids = {record.trial_id for record in records}

    @property
    def records(self) -> tuple[TrialRecord, ...]:
        return tuple(self._records)

    def append(self, record: TrialRecord) -> None:
        if record.trial_id in self._ids:
            raise ValueError(f"duplicate trial_id: {record.trial_id}")
        self._records.append(record)
        self._ids.add(record.trial_id)

    def signatures(self, *, outcomes: set[TrialOutcome] | None = None) -> tuple[str, ...]:
        rows = self._records
        if outcomes is not None:
            rows = [row for row in rows if row.hypothesis_outcome in outcomes]
        return tuple(row.experiment_signature for row in rows)

    def as_dict(self) -> dict[str, object]:
        return {"trials": [record.model_dump(mode="json") for record in self._records]}


class ExperimentPlanner:
    """Evidence-conditioned deterministic guardrail for selecting registered experiments.

    This replaces "pick an unused strategy" rotation.  Repetition is allowed when
    fresh diagnosis still supports the same experiment; changes require an
    evidence reason (boundary hit, routing/peak diagnosis, or a refuted previous
    trial), not novelty for novelty's sake.
    """

    def __init__(self, registry: CalibrationStrategyRegistry | None = None) -> None:
        self.registry = registry or CalibrationStrategyRegistry()

    def plan(
        self,
        *,
        hypothesis: HydrologicHypothesis,
        diagnosis: Mapping[str, object],
        available_strategies: Sequence[str],
        prior_trials: Sequence[TrialRecord] = (),
        planner: Literal["agent", "expert", "benchmark"] = "agent",
    ) -> ExperimentPlan:
        available = tuple(
            strategy_id
            for strategy_id in available_strategies
            if strategy_id != "xaj-hydrologist-manual-v1"
        )
        if not available:
            raise ValueError("no automatic calibration strategy is available")

        recommended = str(diagnosis.get("recommended_strategy_id") or "").strip()
        groups = self._groups(diagnosis.get("recommended_param_groups"))
        objective = canonical_objective(str(diagnosis.get("recommended_objective") or "nse"))
        local_hits = self._tokens(diagnosis.get("local_boundary_hits"))
        latest = prior_trials[-1] if prior_trials else None
        reason_codes: list[str] = []

        strategy_id: str | None = recommended if recommended in available else None
        if strategy_id:
            reason_codes.append("diagnosis_recommendation")

        if local_hits and "xaj-broadened-refine-v1" in available:
            strategy_id = "xaj-broadened-refine-v1"
            reason_codes.append("local_boundary_hit")
        elif groups == ("routing",) and "xaj-routing-refine-v1" in available:
            strategy_id = "xaj-routing-refine-v1"
            reason_codes.append("routing_only_hypothesis")
        elif objective == "peak" and "xaj-peak-bias-v1" in available:
            strategy_id = "xaj-peak-bias-v1"
            reason_codes.append("peak_target")
        elif strategy_id is None and groups and set(groups) <= {"evap", "runoff"}:
            if "xaj-water-balance-v1" in available:
                strategy_id = "xaj-water-balance-v1"
                reason_codes.append("water_balance_groups")

        if strategy_id is None:
            for fallback in (
                "xaj-hydro-composite-v1",
                "xaj-bounded-v1",
                "xaj-local-refine-v1",
            ):
                if fallback in available:
                    strategy_id = fallback
                    reason_codes.append("registered_fallback")
                    break
        if strategy_id is None:
            strategy_id = available[0]
            reason_codes.append("available_strategy_fallback")

        # A refuted local/refine attempt with no explicit fresh recommendation is
        # evidence for widening the next search; this is not an unused-strategy rotation.
        if (
            latest is not None
            and latest.strategy_id == strategy_id
            and latest.hypothesis_outcome == "refuted"
            and not recommended
            and "xaj-broadened-refine-v1" in available
            and strategy_id != "xaj-broadened-refine-v1"
        ):
            strategy_id = "xaj-broadened-refine-v1"
            reason_codes.append("refuted_trial_widen_search")

        strategy = self.registry.get(strategy_id)
        selected_groups = groups or tuple(strategy.param_groups)
        selected_objective = objective if diagnosis.get("recommended_objective") else canonical_objective(
            strategy.objective
        )
        evidence_refs = tuple(dict.fromkeys(hypothesis.evidence_refs))
        fingerprint = {
            "hypothesis_id": hypothesis.hypothesis_id,
            "strategy_id": strategy_id,
            "objective": selected_objective,
            "param_groups": selected_groups,
            "evidence_refs": evidence_refs,
        }
        plan_id = "plan-" + hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return ExperimentPlan(
            plan_id=plan_id,
            hypothesis_id=hypothesis.hypothesis_id,
            strategy_id=strategy_id,
            optimizer=strategy.optimizer,
            objective=selected_objective,
            param_groups=selected_groups,
            evaluation_budget=strategy.evaluation_budget,
            evidence_refs=evidence_refs,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            planner=planner,
        )

    @staticmethod
    def _tokens(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        if isinstance(value, (list, tuple, set)):
            return tuple(str(item).strip() for item in value if str(item).strip())
        return ()

    def _groups(self, value: object) -> tuple[Literal["evap", "runoff", "routing"], ...]:
        raw = self._tokens(value)
        allowed = {"evap", "runoff", "routing"}
        return tuple(item for item in raw if item in allowed)  # type: ignore[return-value]


def infer_trial_outcome(
    *, adoption_status: str,
    qualification_status: str,
    primary_delta: float | None,
) -> TrialOutcome:
    """Map independent development evidence to a hypothesis outcome conservatively."""

    if qualification_status == "QUALIFIED" or adoption_status == "ADOPT":
        return "supported"
    if adoption_status == "REJECT" or (primary_delta is not None and primary_delta < 0):
        return "refuted"
    return "inconclusive"
