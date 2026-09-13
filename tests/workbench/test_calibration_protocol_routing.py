from datetime import date
from types import SimpleNamespace

import pytest

from hydro_agent.agent.contracts import ActionCode, AgentDecision, ProblemHypothesis
from hydro_agent.workbench.real import (
    _final_test_dates_from_config,
    _issue_from_config,
    _TaskAwareEvaluateHandler,
)
from hydro_agent.workbench.validation_gate import RealValidationGate


def test_gate_reads_development_window_not_final_test() -> None:
    task_configs = {
        "task-1": {
            "start_date": "2000-05-05",
            "end_date": "2000-05-07",
            "development_start_date": "2000-05-05",
            "development_end_date": "2000-05-07",
            "final_test_start_date": "2000-05-08",
            "final_test_end_date": "2000-05-10",
        }
    }
    gate = RealValidationGate(
        repository=None,
        forecast_service=None,
        source=None,
        policy=None,
        task_configs=task_configs,
    )

    window = gate.window_for("task-1")

    assert window.start == date(2000, 5, 5)
    assert window.end == date(2000, 5, 7)


def test_final_test_helpers_do_not_reuse_development_aliases() -> None:
    cfg = {
        "start_date": "2000-05-05",
        "end_date": "2000-05-07",
        "final_test_start_date": "2000-05-08",
        "final_test_end_date": "2000-05-10",
    }

    development_issue = _issue_from_config(cfg)
    final_start, final_end = _final_test_dates_from_config(cfg)

    assert development_issue.date() == date(2000, 5, 7)
    assert final_start == date(2000, 5, 8)
    assert final_end == date(2000, 5, 10)


def test_final_test_evaluation_can_only_be_consumed_once() -> None:
    repository = SimpleNamespace(
        list_evidence=lambda _task_id: [
            SimpleNamespace(
                action=ActionCode.A12_EVALUATE_REPORT.value,
                status="succeeded",
            )
        ]
    )
    kernel = SimpleNamespace(repository=repository)
    handler = _TaskAwareEvaluateHandler(
        kernel,
        {
            "task-1": {
                "final_test_start_date": "2000-05-08",
                "final_test_end_date": "2000-05-10",
            }
        },
    )
    decision = AgentDecision(
        action=ActionCode.A12_EVALUATE_REPORT,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="final test must not be evaluated twice",
    )

    with pytest.raises(RuntimeError, match="final_test already consumed"):
        handler.execute("task-1", decision)
