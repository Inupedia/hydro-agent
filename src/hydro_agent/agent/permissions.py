from __future__ import annotations

from hydro_agent.agent.contracts import (
    MAX_TECHNICAL_RETRIES,
    ActionCode,
    AgentDecision,
    WorldStateView,
)


class PermissionDenied(PermissionError):
    pass


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


def decision_fingerprint(decision: AgentDecision, scheme_id: str) -> str:
    groups = ",".join(decision.param_groups or ())
    return "|".join(
        [
            decision.hypothesis.value,
            decision.action.value,
            decision.strategy_id or "",
            groups,
            decision.objective or "",
            scheme_id,
        ]
    )


class PermissionGate:
    def safe_actions(self, view: WorldStateView) -> tuple[ActionCode, ...]:
        if view.permissions.paused or view.task.terminal_status:
            return ()
        allowed = set(PHASE_ACTIONS.get(view.task.phase, ())) & IMPLEMENTED
        if view.budget.agent_rounds_remaining <= 0:
            allowed &= {ActionCode.A09_RESOLVE}
        if view.budget.optimization_cycles_remaining <= 0:
            allowed.discard(ActionCode.A07_OPTIMIZE)
        if "calibrate" not in view.model.capabilities and "adapt" not in view.model.capabilities:
            allowed.discard(ActionCode.A07_OPTIMIZE)
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
        fingerprint = decision_fingerprint(decision, view.scheme.scheme_id)
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
