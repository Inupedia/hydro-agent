from hydro_agent.agent.contracts import (
    ActionCode,
    BudgetSummary,
    EvidenceSummary,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.permissions import (
    PermissionGate,
    closeout_pending,
    pending_calibration_action,
)


def test_failed_a07_consumes_ledger_budget_without_requiring_gate():
    view = WorldStateView(
        task=TaskSummary(task_id="task-1", basin_id="b1", phase="B", forcing_mode="R"),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate", "validate")),
        scheme=SchemeSummary(scheme_id="scheme-base", status="base", content_hash="h"),
        permissions=PermissionSummary(safe_actions=(), paused=False),
        budget=BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=2,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
        evidence_summary=(
            EvidenceSummary(
                evidence_id="ev-a07-failed",
                action=ActionCode.A07_OPTIMIZE,
                status="failed",
                new_information_hash="failed-hash",
                metrics={"model_evaluations": 53.0},
                gates={
                    "model_evaluations": "53",
                    "reason": "calibration_execution_failed",
                },
            ),
        ),
    )

    assert pending_calibration_action(view) is None
    safe = PermissionGate().safe_actions(view)
    assert ActionCode.A08_GATE not in safe
    assert ActionCode.A07_OPTIMIZE in safe
    assert closeout_pending(view) is False
