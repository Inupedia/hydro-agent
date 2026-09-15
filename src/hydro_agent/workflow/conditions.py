"""Named transition conditions. JSON stores the name; this module owns the implementation."""

from __future__ import annotations

from collections.abc import Callable

from hydro_agent.agent.contracts import ActionCode, WorldStateView
from hydro_agent.agent.permissions import (
    CLOSEOUT_RESERVE_ROUNDS,
    latest_action_index,
    pending_calibration_action,
)

ConditionFn = Callable[[WorldStateView], bool]


def _evidence_actions(view: WorldStateView) -> set[str]:
    return {item.action.value for item in view.evidence_summary}


def _latest_status(view: WorldStateView, action: str) -> str | None:
    for item in reversed(view.evidence_summary):
        if item.action.value == action:
            return item.status
    return None


def _campaign_closeout_required(view: WorldStateView) -> bool:
    """Return whether the current research loop must close out.

    Scientific stopping is owned by the preregistered Campaign policy.  The
    smoke-mode optimization-cycle guard is only a runtime safety handover and
    must never be interpreted as convergence or target quality.
    """

    if view.hydro.campaign.stop_reason is not None:
        return True
    if view.hydro.campaign.mode == "smoke" and view.budget.optimization_cycles_remaining <= 0:
        return True
    if view.budget.agent_rounds_remaining <= CLOSEOUT_RESERVE_ROUNDS:
        return True
    return False


def always(_view: WorldStateView) -> bool:
    return True


def forecast_done(view: WorldStateView) -> bool:
    return (
        view.latest_forecast_id is not None
        or ActionCode.A03_FORECAST.value in _evidence_actions(view)
    )


def needs_calibration(view: WorldStateView) -> bool:
    """Legacy workflow name: continue the Campaign with another experiment.

    This no longer means "NSE below a Skill threshold".  The runtime provider
    and this predicate both defer stopping to Campaign state and hard budgets.
    """

    if not view.task.allow_optimization:
        return False
    if ActionCode.A04_DIAGNOSE.value not in _evidence_actions(view):
        return False
    if view.hydro.campaign.stop_reason is not None or not view.hydro.campaign.can_continue_search:
        return False
    if view.budget.optimization_cycles_remaining <= 0:
        return False
    if view.budget.agent_rounds_remaining <= CLOSEOUT_RESERVE_ROUNDS:
        return False
    return True


def calibration_good_enough(view: WorldStateView) -> bool:
    """Legacy workflow name: Campaign has reached closeout/handover.

    Kept as a named transition for the v1 workflow definition.  It deliberately
    contains no NSE/GB-T/Skill threshold logic.
    """

    if ActionCode.A04_DIAGNOSE.value not in _evidence_actions(view):
        return False
    if latest_action_index(view, ActionCode.A04_DIAGNOSE) <= latest_action_index(
        view, ActionCode.A05_OPTIMIZE
    ):
        return False
    return _campaign_closeout_required(view) or not view.task.allow_optimization


def candidate_ready(view: WorldStateView) -> bool:
    return pending_calibration_action(view) == ActionCode.A06_GATE


def gate_retry_allowed(view: WorldStateView) -> bool:
    """Compatibility predicate for the v1 diagram.

    The current calibration-scientist runtime does not jump directly from
    Resolve to Optimize: it re-enters A04 diagnosis first.  Returning False here
    prevents the legacy diagram condition from authorizing a blind retry while
    the JSON transition is migrated separately.
    """

    _ = view
    return False


def gate_accept_or_stop(view: WorldStateView) -> bool:
    status = _latest_status(view, ActionCode.A07_RESOLVE.value) or _latest_status(
        view, ActionCode.A06_GATE.value
    )
    if status not in {"ACCEPT", "KEEP", "ROLLBACK"}:
        return False
    return _campaign_closeout_required(view)


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
