import os
from pathlib import Path

import pytest

from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.execution.workspace import WorkspaceManager
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter

REAL_SNAPSHOT = os.getenv("HYDRO_AGENT_LOWMAN_SNAPSHOT")
SCHEME_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "xaj" / "lowman_scheme.json"
pytestmark = pytest.mark.skipif(
    not REAL_SNAPSHOT, reason="set HYDRO_AGENT_LOWMAN_SNAPSHOT to SP4 snapshot"
)


class SnapshotWorkspaceManager(WorkspaceManager):
    def __init__(self, root: Path, snapshot: Path, scheme: Path):
        super().__init__(root)
        self.snapshot = snapshot.resolve()
        self.scheme = scheme.resolve()

    def create(self, request: ExecutionRequest) -> Path:
        workspace = super().create(request)
        for name in ("forcing.csv", "basin.json", "snapshot-manifest.json"):
            self.materialize_file(self.snapshot / name, workspace / "input/snapshot" / name)
        self.materialize_file(self.scheme, workspace / "input/scheme/scheme.json")
        return workspace


@pytest.fixture
def real_xaj_request():
    return ExecutionRequest(
        task_id="lowman-r-001",
        action_run_id="real-run-0",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id="lowman-r-2020-05-01",
        scheme_id="xaj-base-lowman",
        issue_time="2020-05-01T00:00:00Z",
        parameters={},
        policy=ExecutionPolicy(
            timeout_seconds=120,
            network_access=False,
            max_output_bytes=5_000_000,
            device="cpu",
        ),
    )


@pytest.fixture
def real_xaj_runner(tmp_path):
    registry = RuntimeRegistry()
    registry.register(XajRuntimeAdapter())
    manager = SnapshotWorkspaceManager(tmp_path / "runs", Path(REAL_SNAPSHOT), SCHEME_PATH)
    return SandboxRunner(registry, manager)


def test_real_lowman_forecast_is_reproducible(real_xaj_runner, real_xaj_request):
    first = real_xaj_runner.run(real_xaj_request.model_copy(update={"action_run_id": "real-run-1"}))
    second = real_xaj_runner.run(
        real_xaj_request.model_copy(update={"action_run_id": "real-run-2"})
    )
    assert first.status == second.status == "succeeded", (first.error_code, first.result_payload)
    f1 = [x["value"] for x in first.result_payload["forecast"]]
    f2 = [x["value"] for x in second.result_payload["forecast"]]
    assert f1 == pytest.approx(f2, abs=1e-9)
    assert len(f1) == 3
    assert first.result_payload["unit"] == "m3/s"
    assert [item["lead"] for item in first.result_payload["forecast"]] == [1, 2, 3]
