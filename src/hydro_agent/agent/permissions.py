from __future__ import annotations

from hydro_agent.agent.contracts import (
    MAX_TECHNICAL_RETRIES,
    ActionCode,
    AgentDecision,
    WorldStateView,
)


class PermissionDenied(PermissionError):
    pass


# Reserve rounds for freeze → replay → evaluate so calibration KEEP loops cannot starve closeout.
CLOSEOUT_RESERVE_ROUNDS = 3

CLOSEOUT_ACTIONS = frozenset(
    {
        ActionCode.A08_GATE,
        ActionCode.A09_RESOLVE,
        ActionCode.A10_FREEZE,
        ActionCode.A11_REPLAY,
        ActionCode.A12_EVALUATE_REPORT,
    }
)

EXPLORATORY_ACTIONS = frozenset(
    {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A03_VALIDATE_SCHEME,
        ActionCode.A05_FORECAST,
        ActionCode.A06_DIAGNOSE,
        ActionCode.A07_OPTIMIZE,
    }
)

PHASE_ACTIONS = {
    "B": {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A03_VALIDATE_SCHEME,
        ActionCode.A05_FORECAST,
        ActionCode.A06_DIAGNOSE,
        ActionCode.A07_OPTIMIZE,
        ActionCode.A08_GATE,
        ActionCode.A09_RESOLVE,
        ActionCode.A10_FREEZE,
    },
    "F": {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A03_VALIDATE_SCHEME,
        ActionCode.A05_FORECAST,
        ActionCode.A09_RESOLVE,
        ActionCode.A11_REPLAY,
    },
    "E": {ActionCode.A12_EVALUATE_REPORT, ActionCode.A01_CHECK_DATA},
}

IMPLEMENTED = {
    ActionCode.A01_CHECK_DATA,
    ActionCode.A03_VALIDATE_SCHEME,
    ActionCode.A05_FORECAST,
    ActionCode.A06_DIAGNOSE,
    ActionCode.A07_OPTIMIZE,
    ActionCode.A08_GATE,
    ActionCode.A09_RESOLVE,
    ActionCode.A10_FREEZE,
    ActionCode.A11_REPLAY,
    ActionCode.A12_EVALUATE_REPORT,
}


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
            # Allow a fresh A07 after Gate KEEP/ROLLBACK without tripping "no new evidence".
            f"opt{optimize_attempt}",
        ]
    )


def evidence_actions(view: WorldStateView) -> set[str]:
    return {item.action.value for item in view.evidence_summary}


def closeout_pending(view: WorldStateView) -> bool:
    """True when freeze/replay/evaluate (or in-flight gate/resolve) still needed."""
    actions = evidence_actions(view)
    phase = view.task.phase
    if phase == "E":
        return ActionCode.A12_EVALUATE_REPORT.value not in actions
    if phase == "F":
        return ActionCode.A11_REPLAY.value not in actions
    if phase == "B":
        # Mid gate cycle must finish even if rounds are gone.
        if ActionCode.A07_OPTIMIZE.value in actions and ActionCode.A08_GATE.value not in actions:
            return True
        if ActionCode.A08_GATE.value in actions and ActionCode.A09_RESOLVE.value not in actions:
            return True
        # Opt budget gone or rounds reserved → must still be able to freeze.
        if ActionCode.A10_FREEZE.value not in actions:
            if view.budget.optimization_cycles_remaining <= 0 and ActionCode.A07_OPTIMIZE.value in actions:
                return True
            if view.budget.agent_rounds_remaining <= CLOSEOUT_RESERVE_ROUNDS:
                return True
        return False
    return False


class PermissionGate:
    def safe_actions(self, view: WorldStateView) -> tuple[ActionCode, ...]:
        if view.permissions.paused or view.task.terminal_status:
            return ()
        phase_set = set(PHASE_ACTIONS.get(view.task.phase, ()))
        allowed = phase_set & IMPLEMENTED
        remaining = int(view.budget.agent_rounds_remaining)

        if view.budget.optimization_cycles_remaining <= 0:
            allowed.discard(ActionCode.A07_OPTIMIZE)
        if not view.task.allow_optimization:
            allowed.discard(ActionCode.A07_OPTIMIZE)
        if "calibrate" not in view.model.capabilities and "adapt" not in view.model.capabilities:
            allowed.discard(ActionCode.A07_OPTIMIZE)

        # Reserve last rounds for closeout; at zero rounds still allow closeout.
        if remaining <= CLOSEOUT_RESERVE_ROUNDS:
            allowed -= EXPLORATORY_ACTIONS
        if remaining <= 0:
            allowed = (CLOSEOUT_ACTIONS & phase_set & IMPLEMENTED)
            # Mid-cycle gate/resolve still needed in B.
            if view.task.phase == "B":
                allowed |= {
                    ActionCode.A08_GATE,
                    ActionCode.A09_RESOLVE,
                    ActionCode.A10_FREEZE,
                } & IMPLEMENTED

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
