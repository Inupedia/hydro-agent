from __future__ import annotations

from hydro_agent.agent.contracts import (
    MAX_TECHNICAL_RETRIES,
    ActionCode,
    AgentDecision,
    WorldStateView,
)
from hydro_agent.workflow.catalog import (
    closeout_action_ids,
    exploratory_action_ids,
    implemented_action_ids,
    phase_action_ids,
)


class PermissionDenied(PermissionError):
    pass


# Reserve Agent calls for closeout. This is a resource boundary, not a scientific
# convergence claim.
CLOSEOUT_RESERVE_ROUNDS = 3


def _codes(ids: frozenset[str]) -> frozenset[ActionCode]:
    return frozenset(ActionCode(item) for item in ids)


def _closeout_actions() -> frozenset[ActionCode]:
    return _codes(closeout_action_ids())


def _exploratory_actions() -> frozenset[ActionCode]:
    return _codes(exploratory_action_ids())


def _phase_actions(phase: str) -> frozenset[ActionCode]:
    return _codes(phase_action_ids(phase))


def _implemented() -> frozenset[ActionCode]:
    return _codes(implemented_action_ids())


CLOSEOUT_ACTIONS = _closeout_actions()
EXPLORATORY_ACTIONS = _exploratory_actions()
PHASE_ACTIONS = {
    "B": set(_phase_actions("B")),
    "F": set(_phase_actions("F")),
    "E": set(_phase_actions("E")),
}
IMPLEMENTED = set(_implemented())


def _legacy_cycle_budget_exhausted(view: WorldStateView) -> bool:
    """Cycle-count budget is retained only for smoke wiring compatibility."""

    return (
        view.hydro.campaign.mode == "smoke"
        and view.budget.optimization_cycles_remaining <= 0
    )


def decision_fingerprint(
    decision: AgentDecision,
    scheme_id: str,
    *,
    optimize_attempt: int = 0,
) -> str:
    groups = ",".join(decision.param_groups or ())
    return "|".join(
        [
            decision.hypothesis.value,
            decision.action.value,
            decision.strategy_id or "",
            groups,
            decision.objective or "",
            scheme_id,
            f"opt{optimize_attempt}",
        ]
    )


def evidence_actions(view: WorldStateView) -> set[str]:
    return {item.action.value for item in view.evidence_summary}


def latest_action_index(view: WorldStateView, action: ActionCode) -> int:
    """Return the latest visible evidence position for an action, or -1."""

    return max(
        (index for index, item in enumerate(view.evidence_summary) if item.action == action),
        default=-1,
    )


def pending_calibration_action(view: WorldStateView) -> ActionCode | None:
    """Return the mandatory closeout action for the latest calibration cycle."""

    optimize_index = latest_action_index(view, ActionCode.A07_OPTIMIZE)
    gate_index = latest_action_index(view, ActionCode.A08_GATE)
    resolve_index = latest_action_index(view, ActionCode.A09_RESOLVE)
    if optimize_index > gate_index:
        return ActionCode.A08_GATE
    if gate_index > resolve_index:
        return ActionCode.A09_RESOLVE
    return None


def rediagnosis_required(view: WorldStateView) -> bool:
    """True when a rejected/kept cycle has not produced fresh A06 evidence."""

    resolve_index = latest_action_index(view, ActionCode.A09_RESOLVE)
    diagnose_index = latest_action_index(view, ActionCode.A06_DIAGNOSE)
    if resolve_index < 0 or resolve_index <= diagnose_index:
        return False
    status = view.evidence_summary[resolve_index].status
    return status in {"KEEP", "ROLLBACK"}


def closeout_pending(view: WorldStateView) -> bool:
    """True when a transaction or preregistered/resource closeout is still needed."""

    actions = evidence_actions(view)
    phase = view.task.phase
    if phase == "E":
        return ActionCode.A12_EVALUATE_REPORT.value not in actions
    if phase == "F":
        return ActionCode.A11_REPLAY.value not in actions
    if phase == "B":
        if pending_calibration_action(view) is not None:
            return True
        if ActionCode.A10_FREEZE.value not in actions:
            if view.hydro.campaign.stop_reason is not None:
                return True
            if _legacy_cycle_budget_exhausted(view) and ActionCode.A07_OPTIMIZE.value in actions:
                return True
            if view.budget.agent_rounds_remaining <= CLOSEOUT_RESERVE_ROUNDS:
                return True
        return False
    return False


class PermissionGate:
    def safe_actions(self, view: WorldStateView) -> tuple[ActionCode, ...]:
        if view.permissions.paused or view.task.terminal_status:
            return ()
        phase_set = set(_phase_actions(view.task.phase))
        allowed = set(phase_set & _implemented())
        remaining = int(view.budget.agent_rounds_remaining)
        campaign_stopped = view.hydro.campaign.stop_reason is not None

        if _legacy_cycle_budget_exhausted(view) or campaign_stopped:
            allowed.discard(ActionCode.A07_OPTIMIZE)
        if not view.task.allow_optimization:
            allowed.discard(ActionCode.A07_OPTIMIZE)
        if "calibrate" not in view.model.capabilities and "adapt" not in view.model.capabilities:
            allowed.discard(ActionCode.A07_OPTIMIZE)

        # Agent-call limits remain explicit resource caps, never convergence evidence.
        if remaining <= CLOSEOUT_RESERVE_ROUNDS:
            allowed -= set(_exploratory_actions())
        if remaining <= 0:
            allowed = set(_closeout_actions() & phase_set & _implemented())
            if view.task.phase == "B":
                allowed |= {
                    ActionCode.A08_GATE,
                    ActionCode.A09_RESOLVE,
                    ActionCode.A10_FREEZE,
                } & _implemented()

        pending = pending_calibration_action(view)
        if view.task.phase == "B" and pending is not None:
            # An A07 transaction must always finish Gate/Resolve before any stop.
            allowed = {pending} if pending in _implemented() else set()
        elif view.task.phase == "B" and campaign_stopped:
            allowed = {ActionCode.A10_FREEZE} & _implemented()
        elif view.task.phase == "B" and rediagnosis_required(view):
            allowed = {ActionCode.A10_FREEZE} & _implemented()
            cycle_budget_available = not _legacy_cycle_budget_exhausted(view)
            if cycle_budget_available and remaining > CLOSEOUT_RESERVE_ROUNDS:
                allowed |= {ActionCode.A06_DIAGNOSE} & _implemented()

        return tuple(sorted(allowed, key=lambda item: item.value))

    def authorize(self, view: WorldStateView, decision: AgentDecision) -> None:
        if view.task.phase == "B" and decision.action == ActionCode.A12_EVALUATE_REPORT:
            raise PermissionDenied("phase forbids evaluate")
        if view.task.phase in ("F", "E") and decision.action == ActionCode.A07_OPTIMIZE:
            raise PermissionDenied("phase forbids optimize")
        if decision.action not in self.safe_actions(view):
            raise PermissionDenied(f"action {decision.action} is not safe")
        if decision.action == ActionCode.A07_OPTIMIZE and decision.strategy_id is None:
            raise PermissionDenied("optimize requires strategy_id")
        if decision.action == ActionCode.A07_OPTIMIZE:
            allowed_groups = set(view.hydro.available_param_groups or ("evap", "runoff", "routing"))
            if decision.param_groups:
                unknown = [g for g in decision.param_groups if g not in allowed_groups]
                if unknown:
                    raise PermissionDenied(f"unknown param_groups: {unknown}")
            if decision.objective and decision.objective not in set(
                view.hydro.available_objectives or ("nse", "peak", "composite")
            ):
                raise PermissionDenied(f"unknown objective: {decision.objective}")
        if decision.action == ActionCode.A06_DIAGNOSE and view.latest_forecast_id is None:
            raise PermissionDenied("diagnose requires a forecast first")
        optimize_attempt = sum(
            1 for item in view.evidence_summary if item.action == ActionCode.A07_OPTIMIZE
        )
        fingerprint = decision_fingerprint(
            decision, view.scheme.scheme_id, optimize_attempt=optimize_attempt
        )
        if (
            view.last_decision_fingerprint == fingerprint
            and view.last_information_hash is not None
            and (
                not view.evidence_summary
                or view.evidence_summary[-1].new_information_hash == view.last_information_hash
            )
        ):
            raise PermissionDenied("no new evidence")
        retries = sum(
            1
            for item in view.evidence_summary
            if item.action == decision.action and item.status == "failed"
        )
        if retries > MAX_TECHNICAL_RETRIES:
            raise PermissionDenied("technical retry budget exceeded")
