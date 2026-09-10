from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    BudgetSummary,
    EvidenceSummary,
    HydroContext,
    ModelSummary,
    PermissionSummary,
    ProblemHypothesis,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.workbench.calibration import HydrologistProtocolDecisionProvider


class Delegate:
    def __init__(self):
        self.calls = 0

    def decide(self, view):
        self.calls += 1
        return AgentDecision(
            action=ActionCode.A07_OPTIMIZE,
            hypothesis=ProblemHypothesis.MODEL,
            strategy_id="xaj-local-refine-v1",
            param_groups=("evap", "runoff"),
            objective="water_balance",
            rationale_summary="continue phase experiment",
        )


def _evidence(action: ActionCode, status: str = "succeeded", gates=None) -> EvidenceSummary:
    return EvidenceSummary(
        evidence_id=f"ev-{action.value.lower()}",
        action=action,
        status=status,
        new_information_hash=f"hash-{action.value.lower()}",
        gates=gates or {},
    )


def _view(*, evidence=(), counts=None, latest_gate=None, phase="P2_WATER_BALANCE"):
    safe = tuple(
        action
        for action in ActionCode
        if action
        in {
            ActionCode.A01_CHECK_DATA,
            ActionCode.A03_VALIDATE_SCHEME,
            ActionCode.A05_FORECAST,
            ActionCode.A06_DIAGNOSE,
            ActionCode.A07_OPTIMIZE,
            ActionCode.A08_GATE,
            ActionCode.A09_RESOLVE,
            ActionCode.A10_FREEZE,
        }
    )
    return WorldStateView(
        task=TaskSummary(
            task_id="task-1",
            basin_id="basin-1",
            phase="B",
            forcing_mode="R",
        ),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=SchemeSummary(scheme_id="scheme-base", status="base", content_hash="hash"),
        permissions=PermissionSummary(safe_actions=safe),
        budget=BudgetSummary(
            agent_rounds_remaining=50,
            optimization_cycles_remaining=10,
            max_agent_rounds=100,
            max_optimization_cycles=20,
        ),
        evidence_summary=tuple(evidence),
        hydro=HydroContext(
            calibration_phase=phase,
            action_counts=counts or {},
            latest_gate=latest_gate or {},
            available_objectives=("water_balance",),
        ),
    )


def test_initialization_does_not_repeat_when_old_rows_leave_prompt_window():
    delegate = Delegate()
    provider = HydrologistProtocolDecisionProvider(delegate)
    view = _view(
        evidence=(_evidence(ActionCode.A06_DIAGNOSE),),
        counts={
            ActionCode.A01_CHECK_DATA.value: 1,
            ActionCode.A03_VALIDATE_SCHEME.value: 1,
            ActionCode.A05_FORECAST.value: 1,
            ActionCode.A06_DIAGNOSE.value: 4,
            ActionCode.A07_OPTIMIZE.value: 3,
            ActionCode.A08_GATE.value: 3,
            ActionCode.A09_RESOLVE.value: 3,
        },
    )
    decision = provider.decide(view)
    assert decision.action == ActionCode.A07_OPTIMIZE
    assert delegate.calls == 1


def test_unmatched_optimization_forces_gate_from_lifetime_counts():
    provider = HydrologistProtocolDecisionProvider(Delegate())
    decision = provider.decide(
        _view(
            evidence=(_evidence(ActionCode.A01_CHECK_DATA),),
            counts={
                ActionCode.A01_CHECK_DATA.value: 1,
                ActionCode.A03_VALIDATE_SCHEME.value: 1,
                ActionCode.A05_FORECAST.value: 1,
                ActionCode.A06_DIAGNOSE.value: 1,
                ActionCode.A07_OPTIMIZE.value: 5,
                ActionCode.A08_GATE.value: 4,
                ActionCode.A09_RESOLVE.value: 4,
            },
        )
    )
    assert decision.action == ActionCode.A08_GATE


def test_unresolved_gate_forces_resolve_from_lifetime_counts():
    provider = HydrologistProtocolDecisionProvider(Delegate())
    decision = provider.decide(
        _view(
            evidence=(_evidence(ActionCode.A01_CHECK_DATA),),
            counts={
                ActionCode.A01_CHECK_DATA.value: 1,
                ActionCode.A03_VALIDATE_SCHEME.value: 1,
                ActionCode.A05_FORECAST.value: 1,
                ActionCode.A06_DIAGNOSE.value: 1,
                ActionCode.A07_OPTIMIZE.value: 5,
                ActionCode.A08_GATE.value: 5,
                ActionCode.A09_RESOLVE.value: 4,
            },
            latest_gate={"status": "CONTINUE"},
        )
    )
    assert decision.action == ActionCode.A09_RESOLVE


def test_plateau_fail_freezes_immediately_after_resolve():
    provider = HydrologistProtocolDecisionProvider(Delegate())
    gate = {"status": "PLATEAU_FAIL", "return_phase": ""}
    decision = provider.decide(
        _view(
            evidence=(_evidence(ActionCode.A09_RESOLVE, "PLATEAU_FAIL", gate),),
            counts={
                ActionCode.A01_CHECK_DATA.value: 1,
                ActionCode.A03_VALIDATE_SCHEME.value: 1,
                ActionCode.A05_FORECAST.value: 1,
                ActionCode.A06_DIAGNOSE.value: 10,
                ActionCode.A07_OPTIMIZE.value: 10,
                ActionCode.A08_GATE.value: 10,
                ActionCode.A09_RESOLVE.value: 10,
            },
            latest_gate=gate,
        )
    )
    assert decision.action == ActionCode.A10_FREEZE


def test_development_failure_returns_to_attributed_phase_before_new_experiment():
    provider = HydrologistProtocolDecisionProvider(Delegate())
    gate = {
        "status": "PLATEAU_FAIL",
        "return_phase": "P4_ROUTING_EVENT",
    }
    decision = provider.decide(
        _view(
            phase="P4_ROUTING_EVENT",
            evidence=(_evidence(ActionCode.A09_RESOLVE, "PLATEAU_FAIL", gate),),
            counts={
                ActionCode.A01_CHECK_DATA.value: 1,
                ActionCode.A03_VALIDATE_SCHEME.value: 1,
                ActionCode.A05_FORECAST.value: 1,
                ActionCode.A06_DIAGNOSE.value: 6,
                ActionCode.A07_OPTIMIZE.value: 5,
                ActionCode.A08_GATE.value: 6,
                ActionCode.A09_RESOLVE.value: 6,
            },
            latest_gate=gate,
        )
    )
    assert decision.action == ActionCode.A06_DIAGNOSE
