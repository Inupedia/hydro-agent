"""Named transition conditions. JSON stores the name; this module owns the implementation."""

from __future__ import annotations

from collections.abc import Callable

from hydro_agent.agent.contracts import ActionCode, WorldStateView
from hydro_agent.agent.permissions import CLOSEOUT_RESERVE_ROUNDS
from hydro_agent.skills import DEFAULT_NSE_GOOD_ENOUGH

ConditionFn = Callable[[WorldStateView], bool]


def _evidence_actions(view: WorldStateView) -> set[str]:
    return {item.action.value for item in view.evidence_summary}


def _latest_status(view: WorldStateView, action: str) -> str | None:
    for item in reversed(view.evidence_summary):
        if item.action.value == action:
            return item.status
    return None


def _diagnosis_nse(view: WorldStateView) -> float | None:
    diagnosis = dict(view.hydro.diagnosis or {})
    metrics = diagnosis.get("metrics") if isinstance(diagnosis.get("metrics"), dict) else {}
    raw = metrics.get("nse")
    if raw is None:
        raw = diagnosis.get("nse")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return value


def _gbt_ok(view: WorldStateView) -> bool:
    diagnosis = dict(view.hydro.diagnosis or {})
    metrics = diagnosis.get("metrics") if isinstance(diagnosis.get("metrics"), dict) else {}
    if "scheme_grade_rank" not in metrics:
        return False
    try:
        return float(metrics["scheme_grade_rank"]) >= 1.0
    except (TypeError, ValueError):
        return False


def always(_view: WorldStateView) -> bool:
    return True


def forecast_done(view: WorldStateView) -> bool:
    return (
        view.latest_forecast_id is not None
        or ActionCode.A05_FORECAST.value in _evidence_actions(view)
    )


def needs_calibration(view: WorldStateView) -> bool:
    if not view.task.allow_optimization:
        return False
    if view.budget.optimization_cycles_remaining <= 0:
        return False
    if view.budget.agent_rounds_remaining <= CLOSEOUT_RESERVE_ROUNDS:
        return False
    if ActionCode.A06_DIAGNOSE.value not in _evidence_actions(view):
        return False
    nse = _diagnosis_nse(view)
    return not (_gbt_ok(view) or (nse is not None and nse >= DEFAULT_NSE_GOOD_ENOUGH))


def calibration_good_enough(view: WorldStateView) -> bool:
    if ActionCode.A06_DIAGNOSE.value not in _evidence_actions(view):
        return False
    if ActionCode.A07_OPTIMIZE.value in _evidence_actions(view):
        return False
    nse = _diagnosis_nse(view)
    return _gbt_ok(view) or (nse is not None and nse >= DEFAULT_NSE_GOOD_ENOUGH)


def candidate_ready(view: WorldStateView) -> bool:
    actions = _evidence_actions(view)
    return ActionCode.A07_OPTIMIZE.value in actions and ActionCode.A08_GATE.value not in actions


def gate_retry_allowed(view: WorldStateView) -> bool:
    status = _latest_status(view, ActionCode.A08_GATE.value) or _latest_status(
        view, ActionCode.A09_RESOLVE.value
    )
    if status not in {"KEEP", "ROLLBACK"}:
        return False
    if not view.task.allow_optimization:
        return False
    if view.budget.optimization_cycles_remaining <= 0:
        return False
    return view.budget.agent_rounds_remaining > CLOSEOUT_RESERVE_ROUNDS


def gate_accept_or_stop(view: WorldStateView) -> bool:
    status = _latest_status(view, ActionCode.A09_RESOLVE.value) or _latest_status(
        view, ActionCode.A08_GATE.value
    )
    if status == "ACCEPT":
        return True
    if status in {"KEEP", "ROLLBACK"}:
        return not gate_retry_allowed(view)
    return False


def blocked(view: WorldStateView) -> bool:
    if not view.evidence_summary:
        return False
    return view.evidence_summary[-1].status in {"blocked", "failed"}


# Modeling / UI conditions stay named-only: they are not WorldStateView predicates.
NAMED_ONLY = frozenset(
    {
        "new_build",
        "reuse_plan",
        "materials_ok",
        "delineate_ok",
        "boundary_confirmed",
        "inputs_ok",
        "reuse_valid",
        "plan_bound",
    }
)

PREDICATES: dict[str, ConditionFn] = {
    "always": always,
    "forecast_done": forecast_done,
    "needs_calibration": needs_calibration,
    "calibration_good_enough": calibration_good_enough,
    "candidate_ready": candidate_ready,
    "gate_retry_allowed": gate_retry_allowed,
    "gate_accept_or_stop": gate_accept_or_stop,
    "blocked": blocked,
}


def known_condition_names() -> frozenset[str]:
    return frozenset(PREDICATES) | NAMED_ONLY


def evaluate_condition(name: str, view: WorldStateView) -> bool:
    fn = PREDICATES.get(name)
    if fn is None:
        raise KeyError(f"condition {name} is not implemented in code")
    return fn(view)
