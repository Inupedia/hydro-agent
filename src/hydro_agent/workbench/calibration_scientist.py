"""Calibration-scientist workbench built on the real deterministic XAJ stack."""

from __future__ import annotations

from hydro_agent.services.calibration_diagnostics import diagnose_prevalidation_window
from hydro_agent.workbench.real import POLICY, RealWorkbenchKernel


class CalibrationScientistWorkbenchKernel(RealWorkbenchKernel):
    """RealWorkbenchKernel with leakage-safe scientific diagnostics.

    The base workbench remains the deterministic executor. This subclass only
    changes *what evidence the Agent is allowed to reason from*: diagnosis is
    built entirely from truth preceding the held-out validation window.
    """

    def _diagnose(self, task_id: str) -> dict:
        state = self.repository.ensure_task_state(task_id)
        scheme_id = state.current_scheme_id
        if not scheme_id:
            return {
                "hypothesis": "DATA",
                "phenomenon": "尚无当前方案，无法诊断",
                "recommended_action": "A03_VALIDATE_SCHEME",
                "recommended_strategy_id": None,
                "recommended_param_groups": None,
                "recommended_objective": None,
                "hypotheses": [],
                "metrics": {},
                "notes": ["no current scheme"],
            }

        window = self.validation_gate.window_for(task_id)
        result = diagnose_prevalidation_window(
            repository=self.repository,
            forecast_service=self.forecast,
            source=self.source,
            policy=POLICY,
            task_id=task_id,
            scheme_id=scheme_id,
            validation_start=window.start,
            nse_good_enough=self.skills.nse_good_enough(),
        )
        notes = list(result.get("notes") or [])
        notes.insert(0, f"scheme_id={scheme_id}")
        notes.insert(
            1,
            f"held_out_validation_window={window.start.isoformat()}..{window.end.isoformat()}",
        )
        result["notes"] = notes
        return result
