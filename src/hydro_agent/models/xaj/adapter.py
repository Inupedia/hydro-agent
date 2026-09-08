import sys
from pathlib import Path

from hydro_agent.execution.contracts import ExecutionRequest


class XajRuntimeAdapter:
    model_id = "xaj"
    capabilities = frozenset({"validate", "rebuild_state", "forecast", "calibrate"})

    def command(self, request: ExecutionRequest, workspace: Path) -> list[str]:
        if request.model_id != "xaj" or request.policy.device != "cpu":
            raise ValueError("unsupported XAJ capability or device")
        if request.capability == "forecast":
            module = "hydro_agent.models.xaj.runtime"
        elif request.capability == "calibrate":
            module = "hydro_agent.models.xaj.calibrate_runtime"
        else:
            raise ValueError("unsupported XAJ capability or device")
        return [sys.executable, "-m", module, "--workspace", str(workspace)]
