import sys
from pathlib import Path

from hydro_agent.execution.contracts import ExecutionRequest


class SacSmaRuntimeAdapter:
    model_id = "sac-sma"
    capabilities = frozenset({"validate", "rebuild_state", "forecast", "calibrate"})

    def command(self, request: ExecutionRequest, workspace: Path) -> list[str]:
        if request.model_id != "sac-sma" or request.policy.device != "cpu":
            raise ValueError("unsupported SAC-SMA capability or device")
        if request.capability == "forecast":
            module = "hydro_agent.models.shared_forecast_runtime"
        elif request.capability == "calibrate":
            module = "hydro_agent.models.shared_calibrate_runtime"
        else:
            raise ValueError("unsupported SAC-SMA capability or device")
        return [sys.executable, "-m", module, "--workspace", str(workspace)]
