import pytest

from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    BudgetSummary,
    ModelSummary,
    PermissionSummary,
    ProblemHypothesis,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.permissions import (
    CLOSEOUT_RESERVE_ROUNDS,
    PermissionDenied,
    PermissionGate,
    closeout_pending,
    decision_fingerprint,
)


@pytest.fixture
def world_view():
    return WorldStateView(
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
    )


@pytest.fixture
def evaluate_decision():
    return AgentDecision(
        action=ActionCode.A10_EVALUATE_REPORT,
        hypothesis=ProblemHypothesis.UNKNOWN,
        rationale_summary="Evaluate the frozen scheme.",
    )


@pytest.fixture
def repeated_decision():
    return AgentDecision(
        action=ActionCode.A03_FORECAST,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="Repeat the same forecast without new evidence.",
    )


@pytest.fixture
def no_progress_view(world_view, repeated_decision):
    from hydro_agent.agent.contracts import EvidenceSummary

    fingerprint = decision_fingerprint(repeated_decision, world_view.scheme.scheme_id)
    return world_view.model_copy(
        update={
            "last_information_hash": "same-hash",
            "last_decision_fingerprint": fingerprint,
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-1",
                    action=ActionCode.A03_FORECAST,
                    status="succeeded",
                    new_information_hash="same-hash",
                ),
            ),
            "permissions": PermissionSummary(
                safe_actions=PermissionGate().safe_actions(world_view), paused=False
            ),
        }
    )


def test_agent_cannot_optimize_after_budget_exhausted(world_view):
    exhausted = world_view.model_copy(
        update={
            "budget": world_view.budget.model_copy(
                update={"agent_rounds_remaining": 10, "optimization_cycles_remaining": 0}
            )
        }
    )
    assert ActionCode.A05_OPTIMIZE not in PermissionGate().safe_actions(exhausted)


def test_allow_optimization_false_removes_optimize(world_view):
    view = world_view.model_copy(
        update={"task": world_view.task.model_copy(update={"allow_optimization": False})}
    )
    safe = PermissionGate().safe_actions(view)
    assert ActionCode.A05_OPTIMIZE not in safe
    assert ActionCode.A03_FORECAST in safe


def test_reserve_rounds_strips_exploratory_actions(world_view):
    view = world_view.model_copy(
        update={
            "budget": world_view.budget.model_copy(
                update={"agent_rounds_remaining": CLOSEOUT_RESERVE_ROUNDS}
            )
        }
    )
    safe = PermissionGate().safe_actions(view)
    assert ActionCode.A05_OPTIMIZE not in safe
    assert ActionCode.A03_FORECAST not in safe
    assert ActionCode.A08_FREEZE in safe


def test_zero_rounds_still_allows_evaluate_in_phase_e(world_view):
    view = world_view.model_copy(
        update={
            "task": world_view.task.model_copy(update={"phase": "E"}),
            "budget": world_view.budget.model_copy(update={"agent_rounds_remaining": 0}),
        }
    )
    safe = PermissionGate().safe_actions(view)
    assert safe == (ActionCode.A10_EVALUATE_REPORT,)
    assert closeout_pending(view) is True


def test_zero_rounds_still_allows_freeze_in_phase_b(world_view):
    from hydro_agent.agent.contracts import EvidenceSummary

    view = world_view.model_copy(
        update={
            "budget": world_view.budget.model_copy(
                update={"agent_rounds_remaining": 0, "optimization_cycles_remaining": 0}
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-opt",
                    action=ActionCode.A05_OPTIMIZE,
                    status="succeeded",
                    new_information_hash="h-opt",
                ),
                EvidenceSummary(
                    evidence_id="ev-gate",
                    action=ActionCode.A06_GATE,
                    status="succeeded",
                    new_information_hash="h-gate",
                ),
                EvidenceSummary(
                    evidence_id="ev-resolve",
                    action=ActionCode.A07_RESOLVE,
                    status="succeeded",
                    new_information_hash="h-resolve",
                ),
            ),
        }
    )
    safe = PermissionGate().safe_actions(view)
    assert ActionCode.A08_FREEZE in safe
    assert ActionCode.A05_OPTIMIZE not in safe
    assert closeout_pending(view) is True


def test_agent_cannot_evaluate_in_build_phase(world_view, evaluate_decision):
    with pytest.raises(PermissionDenied, match="phase"):
        PermissionGate().authorize(world_view, evaluate_decision)


def test_identical_no_progress_decision_is_rejected(no_progress_view, repeated_decision):
    with pytest.raises(PermissionDenied, match="no new evidence"):
        PermissionGate().authorize(no_progress_view, repeated_decision)


def test_new_optimize_must_use_a_new_gate_even_when_old_cycle_exists(world_view):
    from hydro_agent.agent.contracts import EvidenceSummary

    evidence = tuple(
        EvidenceSummary(
            evidence_id=f"ev-{index}",
            action=action,
            status=status,
            new_information_hash=f"h-{index}",
        )
        for index, (action, status) in enumerate(
            (
                (ActionCode.A05_OPTIMIZE, "succeeded"),
                (ActionCode.A06_GATE, "KEEP"),
                (ActionCode.A07_RESOLVE, "KEEP"),
                (ActionCode.A04_DIAGNOSE, "succeeded"),
                (ActionCode.A05_OPTIMIZE, "succeeded"),
            )
        )
    )
    view = world_view.model_copy(update={"evidence_summary": evidence})
    assert PermissionGate().safe_actions(view) == (ActionCode.A06_GATE,)


def test_resolved_cycle_requires_diagnosis_before_retry_but_allows_freeze(world_view):
    from hydro_agent.agent.contracts import EvidenceSummary

    evidence = tuple(
        EvidenceSummary(
            evidence_id=f"ev-{index}",
            action=action,
            status=status,
            new_information_hash=f"h-{index}",
        )
        for index, (action, status) in enumerate(
            (
                (ActionCode.A04_DIAGNOSE, "succeeded"),
                (ActionCode.A05_OPTIMIZE, "succeeded"),
                (ActionCode.A06_GATE, "KEEP"),
                (ActionCode.A07_RESOLVE, "KEEP"),
            )
        )
    )
    view = world_view.model_copy(update={"evidence_summary": evidence})
    safe = PermissionGate().safe_actions(view)
    assert safe == (ActionCode.A04_DIAGNOSE, ActionCode.A08_FREEZE)
    assert ActionCode.A05_OPTIMIZE not in safe
