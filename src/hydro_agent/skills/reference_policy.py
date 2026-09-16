"""Choose optional Skill references from current evidence, not catalog loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydro_agent.agent.contracts import WorldStateView
    from hydro_agent.skills.loader import LoadedSkill


def _filter_declared(declared: tuple[str, ...], selected: list[str]) -> tuple[str, ...]:
    seen: list[str] = []
    allowed = set(declared)
    for relative in selected:
        if relative in allowed and relative not in seen:
            seen.append(relative)
    return tuple(seen)


def _param_groups(view: WorldStateView) -> list[str]:
    diagnosis = dict(view.hydro.diagnosis or {})
    groups = diagnosis.get("recommended_param_groups") or []
    if isinstance(groups, str):
        return [item.strip() for item in groups.split(",") if item.strip()]
    if isinstance(groups, (tuple, list)):
        return [str(item).strip() for item in groups if str(item).strip()]
    return []


def _has_action(view: WorldStateView, *codes: str) -> bool:
    values = {item.action.value for item in view.evidence_summary}
    return any(code in values for code in codes)


def _xaj_calibration_refs(view: WorldStateView, declared: tuple[str, ...]) -> tuple[str, ...]:
    groups = _param_groups(view)
    selected = ["references/xaj-calibration-workflow.md"]
    if groups:
        selected.append("references/xaj-calibration-parameter-semantics.md")
    if len(groups) > 1:
        selected.append("references/xaj-calibration-parameter-relations.md")
    if "evap" in groups:
        selected.extend(
            (
                "references/xaj-water-balance-water-balance.md",
                "references/xaj-water-balance-evap-runoff-semantics.md",
            )
        )
    if "runoff" in groups:
        selected.extend(
            (
                "references/xaj-runoff-generation-runoff-generation.md",
                "references/xaj-runoff-generation-source-partition.md",
            )
        )
    if "routing" in groups:
        selected.extend(
            (
                "references/xaj-routing-diagnosis-routing.md",
                "references/xaj-routing-diagnosis-recession-and-lag.md",
            )
        )
    if _has_action(view, "A07_RESOLVE") or (view.hydro.diagnosis or {}).get(
        "absolute_boundary_hits"
    ):
        selected.append("references/xaj-calibration-escalation.md")
    return _filter_declared(declared, selected)


def _evidence_review_refs(view: WorldStateView, declared: tuple[str, ...]) -> tuple[str, ...]:
    selected = ["references/hydro-error-diagnosis-metric-patterns.md"]
    if view.hydro.diagnosis or _has_action(view, "A04_DIAGNOSE", "A06_GATE", "A07_RESOLVE"):
        selected.append("references/hydro-error-diagnosis-diagnosis-routing.md")
    if view.model.model_id == "openhydronet":
        selected.append("references/openhydronet-diagnosis-openhydronet-diagnosis.md")
    return _filter_declared(declared, selected)


def _data_review_refs(view: WorldStateView, declared: tuple[str, ...]) -> tuple[str, ...]:
    selected = ["references/hydro-data-readiness-data-semantics.md"]
    if view.task.phase in {"A", "B"} or _has_action(view, "A01_CHECK_DATA", "A02_VALIDATE_SCHEME"):
        selected.append("references/hydro-data-readiness-leakage-checks.md")
    if not view.latest_forecast_id or _has_action(view, "M01_CHECK_MATERIALS"):
        selected.append("references/hydro-modeling-prep-modeling-checklist.md")
    return _filter_declared(declared, selected)


def _experiment_design_refs(view: WorldStateView, declared: tuple[str, ...]) -> tuple[str, ...]:
    selected = [
        "references/hydro-experiment-design-experiment-strategies.md",
        "references/hydro-experiment-design-hypothesis-testing.md",
    ]
    budget = view.budget
    low_budget = (
        budget.optimization_cycles_remaining <= 1
        or budget.agent_rounds_remaining <= max(3, budget.max_agent_rounds // 5)
    )
    if low_budget or _has_action(view, "A05_OPTIMIZE"):
        selected.append("references/hydro-experiment-design-budget-allocation.md")
    if view.hydro.campaign.stop_reason or _has_action(view, "A07_RESOLVE", "A08_FREEZE"):
        selected.extend(
            (
                "references/hydro-campaign-design-period-splitting.md",
                "references/hydro-campaign-design-objective-locking.md",
                "references/hydro-campaign-design-convergence-policy.md",
            )
        )
    elif view.task.allow_optimization:
        selected.append("references/hydro-campaign-design-objective-locking.md")
    return _filter_declared(declared, selected)


def _result_review_refs(view: WorldStateView, declared: tuple[str, ...]) -> tuple[str, ...]:
    selected: list[str] = []
    if _has_action(view, "A06_GATE", "A07_RESOLVE", "A10_EVALUATE_REPORT") or view.task.phase in {
        "E",
        "F",
    }:
        selected.append("references/gbt-22482-accuracy-evaluation-workflow.md")
    if not selected:
        selected.append("references/gbt-22482-accuracy-evaluation-workflow.md")
    return _filter_declared(declared, selected)


def _reporting_refs(view: WorldStateView, declared: tuple[str, ...]) -> tuple[str, ...]:
    del view  # checklist is the only portable reporting reference today
    return _filter_declared(declared, ["references/hydro-report-closeout-report-checklist.md"])


def references_for_view(skill: LoadedSkill, view: WorldStateView) -> tuple[str, ...]:
    declared = skill.meta_list("prompt_references")
    selectors = {
        "xaj-calibration-diagnosis": _xaj_calibration_refs,
        "hydrologic-evidence-review": _evidence_review_refs,
        "hydrology-data-review": _data_review_refs,
        "calibration-experiment-design": _experiment_design_refs,
        "calibration-result-review": _result_review_refs,
        "hydrology-reporting": _reporting_refs,
    }
    selector = selectors.get(skill.skill_id)
    if selector is None:
        return declared
    selected = selector(view, declared)
    # Custom/test packages may declare alternate reference names; keep them usable.
    return selected if selected else declared
