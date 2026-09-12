from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

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
