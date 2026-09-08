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
from hydro_agent.agent.permissions import PermissionDenied, PermissionGate, decision_fingerprint


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
        action=ActionCode.A12_EVALUATE_REPORT,
        hypothesis=ProblemHypothesis.UNKNOWN,
        rationale_summary="Evaluate the frozen scheme.",
    )


@pytest.fixture
def repeated_decision():
    return AgentDecision(
        action=ActionCode.A05_FORECAST,
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
                    action=ActionCode.A05_FORECAST,
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
    assert ActionCode.A07_OPTIMIZE not in PermissionGate().safe_actions(exhausted)


def test_agent_cannot_evaluate_in_build_phase(world_view, evaluate_decision):
    with pytest.raises(PermissionDenied, match="phase"):
        PermissionGate().authorize(world_view, evaluate_decision)


def test_identical_no_progress_decision_is_rejected(no_progress_view, repeated_decision):
    with pytest.raises(PermissionDenied, match="no new evidence"):
        PermissionGate().authorize(no_progress_view, repeated_decision)
