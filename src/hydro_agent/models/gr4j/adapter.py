import sys
from pathlib import Path

from hydro_agent.execution.contracts import ExecutionRequest


class Gr4jRuntimeAdapter:
    model_id = "gr4j"
    capabilities = frozenset({"validate", "rebuild_state", "forecast", "calibrate"})

    def command(self, request: ExecutionRequest, workspace: Path) -> list[str]:
        if request.model_id != "gr4j" or request.policy.device != "cpu":
            raise ValueError("unsupported GR4J capability or device")
        if request.capability == "forecast":
            module = "hydro_agent.models.gr4j.runtime"
        elif request.capability == "calibrate":
            module = "hydro_agent.models.gr4j.calibrate_runtime"
        else:
            raise ValueError("unsupported GR4J capability or device")
        return [sys.executable, "-m", module, "--workspace", str(workspace)]
