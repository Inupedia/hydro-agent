from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from hydro_agent.workbench.calibration_scientist import _apply_latest_gate_feedback
from hydro_agent.workbench.real import RealWorkbenchKernel


class _Repo:
    @staticmethod
    def ensure_task_state(_task_id):
        return SimpleNamespace(current_scheme_id="scheme-base")


def test_real_workbench_binds_a06_to_prevalidation_diagnosis():
    kernel = RealWorkbenchKernel.__new__(RealWorkbenchKernel)
    kernel.repository = _Repo()
    kernel.forecast = object()
    kernel.source = object()
    kernel.skills = SimpleNamespace(nse_good_enough=lambda: 0.5)
    kernel.validation_gate = SimpleNamespace(
        window_for=lambda _task_id: SimpleNamespace(
            start=date(2000, 5, 1),
            end=date(2000, 5, 10),
        )
    )

    with patch(
        "hydro_agent.workbench.real.diagnose_prevalidation_window",
        return_value={
            "hypothesis": "MODEL",
            "phenomenon": "fixture",
            "recommended_action": "A07_OPTIMIZE",
            "recommended_strategy_id": "xaj-water-balance-v1",
            "metrics": {},
            "notes": ["diagnostic_truth_strictly_precedes_validation=true"],
        },
    ) as diagnose:
        result = kernel._diagnose("task-1")

    kwargs = diagnose.call_args.kwargs
    assert kwargs["task_id"] == "task-1"
    assert kwargs["scheme_id"] == "scheme-base"
    assert kwargs["validation_start"] == date(2000, 5, 1)
    assert kwargs["nse_good_enough"] == 0.5
    assert "diagnostic_truth_strictly_precedes_validation=true" in result["notes"]
    assert "held_out_validation_window=2000-05-01..2000-05-10" in result["notes"]


def test_gate_failure_changes_the_next_diagnostic_experiment():
    result = {
        "hypothesis": "MODEL",
        "phenomenon": "old diagnosis",
        "recommended_strategy_id": "xaj-water-balance-v1",
        "recommended_param_groups": ["evap", "runoff"],
        "recommended_objective": "composite",
        "hypotheses": [],
        "metrics": {},
        "notes": [],
    }
    evidence = [
        SimpleNamespace(
            action="A08_GATE",
            status="KEEP",
            created_at=1,
            gates_json={"reasons": "insufficient_absolute_skill"},
            metrics_json={"candidate_primary": -2.0},
        ),
        SimpleNamespace(
            action="A09_RESOLVE",
            status="KEEP",
            created_at=2,
            gates_json={"status": "KEEP"},
            metrics_json={},
        ),
    ]

    updated = _apply_latest_gate_feedback(result, evidence)

    assert updated["recommended_strategy_id"] == "xaj-hydro-composite-v1"
    assert updated["recommended_param_groups"] == ["evap", "runoff", "routing"]
    assert updated["gate_feedback"]["reasons"] == ["insufficient_absolute_skill"]
