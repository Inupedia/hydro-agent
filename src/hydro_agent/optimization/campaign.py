"""Campaign-level calibration state rebuilt from the append-only Trial Ledger.

A Campaign is a derived research view, not a second mutable database. Restarting
Hydro-Agent reconstructs the same best archives, budget usage, plateau evidence
and stop reason from persisted A07/A08/A09 evidence.
"""

from __future__ import annotations

from typing import Literal, Mapping, Sequence

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.optimization.experiments import TrialRecord

CampaignMode = Literal["smoke", "target_quality", "convergence"]
CampaignStopReason = Literal[
    "TARGET_QUALITY_REACHED",
    "CONVERGED",
    "PLATEAUED",
    "BUDGET_EXHAUSTED",
    "UNSATISFIABLE",
    "HUMAN_HANDOVER",
]


class CampaignPolicy(FrozenModel):
    """Pre-registered campaign stopping policy.

    ``smoke`` may use a small trial cap to validate wiring, but that cap can only
    produce BUDGET_EXHAUSTED/not-converged. Formal modes use model-execution and
    convergence evidence rather than the legacy experiment-count lifetime.
    """

    mode: CampaignMode = "smoke"
    smoke_max_trials: int | None = Field(default=None, ge=1)
    max_model_evaluations: int | None = Field(default=None, ge=1)
    min_model_evaluations: int | None = Field(default=None, ge=1)
    plateau_window: int | None = Field(default=None, ge=2)
    plateau_abs_epsilon: float | None = Field(default=None, ge=0.0)
    restart_distinct_strategies: int = Field(default=2, ge=2, le=8)
    max_no_gain_gates: int | None = Field(default=None, ge=1)

    @property
    def convergence_registered(self) -> bool:
        return (
            self.mode == "convergence"
            and self.max_model_evaluations is not None
            and self.min_model_evaluations is not None
            and self.plateau_window is not None
            and self.plateau_abs_epsilon is not None
        )


class CampaignSnapshot(FrozenModel):
    mode: CampaignMode
    trial_count: int = 0
    resolved_trial_count: int = 0
    total_model_evaluations: int = 0
    search_best_scheme_id: str | None = None
    search_best_score: float | None = None
    selected_best_scheme_id: str | None = None
    selected_primary_score: float | None = None
    release_candidate_scheme_id: str | None = None
    plateau_candidate: bool = False
    restart_check_satisfied: bool = False
    no_gain_gate_count: int = 0
    stop_reason: CampaignStopReason | None = None
    converged: bool = False
    can_continue_search: bool = True
    notes: tuple[str, ...] = ()


def policy_from_workbench(workbench: Mapping[str, object] | None) -> CampaignPolicy:
    raw = dict(workbench or {})
    mode = str(raw.get("campaign_mode") or "smoke")
    return CampaignPolicy(
        mode=mode,  # type: ignore[arg-type]
        smoke_max_trials=(
            _optional_int(raw.get("max_optimization_cycles")) if mode == "smoke" else None
        ),
        max_model_evaluations=_optional_int(raw.get("campaign_max_model_evaluations")),
        min_model_evaluations=_optional_int(raw.get("campaign_min_model_evaluations")),
        plateau_window=_optional_int(raw.get("campaign_plateau_window")),
        plateau_abs_epsilon=_optional_float(raw.get("campaign_plateau_abs_epsilon")),
        restart_distinct_strategies=int(raw.get("campaign_restart_distinct_strategies") or 2),
        max_no_gain_gates=_optional_int(raw.get("campaign_max_no_gain_gates")),
    )


def rebuild_campaign(
    records: Sequence[TrialRecord],
    *,
    current_scheme_id: str | None,
    policy: CampaignPolicy,
) -> CampaignSnapshot:
    """Reconstruct the campaign deterministically from persisted trial records."""

    total_evaluations = sum(record.model_evaluations for record in records)
    search_candidates = [
        record
        for record in records
        if record.search_score is not None and record.candidate_scheme_id is not None
    ]
    search_best = (
        max(search_candidates, key=lambda record: float(record.search_score))
        if search_candidates
        else None
    )

    resolved = [record for record in records if record.resolve_recorded]
    selected_scores: list[float] = []
    if resolved and resolved[0].base_primary is not None:
        selected_scores.append(float(resolved[0].base_primary))
    for record in resolved:
        if record.selected_primary is not None:
            selected_scores.append(float(record.selected_primary))

    selected_score = selected_scores[-1] if selected_scores else None
    release_candidate = next(
        (
            record.candidate_scheme_id
            for record in reversed(resolved)
            if record.candidate_adopted
            and record.qualification_status == "QUALIFIED"
            and record.candidate_scheme_id
        ),
        None,
    )
    no_gain_count = 0
    for record in reversed(resolved):
        if record.candidate_adopted:
            break
        no_gain_count += 1

    plateau_candidate = False
    plateau_strategies: tuple[str, ...] = ()
    if (
        policy.convergence_registered
        and total_evaluations >= int(policy.min_model_evaluations or 0)
        and len(selected_scores) >= int(policy.plateau_window or 0) + 1
    ):
        window = int(policy.plateau_window or 0)
        epsilon = float(policy.plateau_abs_epsilon or 0.0)
        recent_scores = selected_scores[-(window + 1) :]
        improvements = [
            max(0.0, current - previous)
            for previous, current in zip(recent_scores, recent_scores[1:])
        ]
        plateau_candidate = all(delta <= epsilon for delta in improvements)
        plateau_strategies = tuple(record.strategy_id for record in resolved[-window:])

    restart_check_satisfied = bool(
        plateau_candidate
        and len(set(plateau_strategies)) >= policy.restart_distinct_strategies
    )

    stop_reason: CampaignStopReason | None = None
    converged = False
    notes: list[str] = []
    if policy.mode == "target_quality" and release_candidate is not None:
        stop_reason = "TARGET_QUALITY_REACHED"
    elif policy.mode == "convergence" and plateau_candidate and restart_check_satisfied:
        stop_reason = "CONVERGED"
        converged = True
    elif policy.max_no_gain_gates is not None and no_gain_count >= policy.max_no_gain_gates:
        stop_reason = "UNSATISFIABLE"
        notes.append("repeated development Gate checks produced no selected-best improvement")
    elif (
        policy.mode == "smoke"
        and policy.smoke_max_trials is not None
        and len(records) >= policy.smoke_max_trials
    ):
        stop_reason = "BUDGET_EXHAUSTED"
        notes.append("smoke wiring trial budget exhausted; convergence was not evaluated")
    elif (
        policy.max_model_evaluations is not None
        and total_evaluations >= policy.max_model_evaluations
    ):
        stop_reason = "BUDGET_EXHAUSTED"
        if plateau_candidate and not restart_check_satisfied:
            notes.append("budget exhausted before preregistered restart check was satisfied")
        elif policy.mode == "convergence":
            notes.append("budget exhausted without operational convergence")

    if policy.mode == "convergence" and not policy.convergence_registered:
        notes.append("convergence policy incomplete; CONVERGED cannot be reported")
    if plateau_candidate and not restart_check_satisfied and stop_reason is None:
        notes.append("plateau candidate requires a distinct registered restart/search check")

    return CampaignSnapshot(
        mode=policy.mode,
        trial_count=len(records),
        resolved_trial_count=len(resolved),
        total_model_evaluations=total_evaluations,
        search_best_scheme_id=search_best.candidate_scheme_id if search_best else None,
        search_best_score=float(search_best.search_score) if search_best else None,
        selected_best_scheme_id=current_scheme_id,
        selected_primary_score=selected_score,
        release_candidate_scheme_id=release_candidate,
        plateau_candidate=plateau_candidate,
        restart_check_satisfied=restart_check_satisfied,
        no_gain_gate_count=no_gain_count,
        stop_reason=stop_reason,
        converged=converged,
        can_continue_search=stop_reason is None,
        notes=tuple(notes),
    )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
