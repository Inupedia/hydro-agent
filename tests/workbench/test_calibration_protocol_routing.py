from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, ProblemHypothesis
from hydro_agent.workbench.real import (
    _final_test_dates_from_config,
    _issue_from_config,
    _TaskAwareEvaluateHandler,
    _TaskAwareOptimizeHandler,
)
from hydro_agent.workbench.validation_gate import RealValidationGate, ValidationWindow


def test_optimize_waits_for_last_observation_without_extending_history(monkeypatch):
    captured = {}

    def resolve(task_id, capability, issue_time, **kwargs):
        captured.update(issue_time=issue_time, **kwargs)
        return "cal-snapshot"

    packet = EvidencePacket(
        evidence_id="ev-test",
        task_id="task-1",
        action=ActionCode.A07_OPTIMIZE,
        status="failed",
        new_information_hash="hash-test",
    )
    monkeypatch.setattr(
        "hydro_agent.workbench.real.OptimizeHandler",
        lambda *args, **kwargs: SimpleNamespace(execute=lambda *args: packet),
    )
    kernel = SimpleNamespace(
        validation_gate=SimpleNamespace(
            window_for=lambda _: ValidationWindow(date(2000, 5, 5), date(2000, 5, 7))
        ),
        _workbench_config=lambda _: {
            "calibration_start_date": "2000-05-01",
            "calibration_end_date": "2000-05-04",
        },
        source=SimpleNamespace(
            basin={"day_timezone": "Asia/Shanghai"},
            flow_rows=[
                SimpleNamespace(
                    valid_date=date(2000, 5, 4),
                    eligible_for_scoring=True,
                    available_at=datetime(2000, 5, 5, tzinfo=timezone.utc),
                )
            ],
        ),
        resolver=SimpleNamespace(resolve=resolve),
        repository=None,
        calibration=None,
        candidates=None,
    )
    _TaskAwareOptimizeHandler(kernel, {}).execute(
        "task-1",
        AgentDecision(
            action=ActionCode.A07_OPTIMIZE,
            hypothesis=ProblemHypothesis.MODEL,
            strategy_id="xaj-bounded-v1",
            param_groups=("evap",),
            objective="nse",
            rationale_summary="Test inclusive calibration boundary.",
        ),
    )
    assert captured["issue_time"] == "2000-05-05T00:00:00Z"
    assert captured["history_end_date"] == date(2000, 5, 4)


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
