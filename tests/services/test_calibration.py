from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionResult
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.services.calibration import CalibrationService
from hydro_agent.services.workspace import MaterializingWorkspaceManager

PARAMS = {
    "K": 0.75,
    "B": 0.25,
    "IM": 0.06,
    "UM": 20.0,
    "LM": 60.0,
    "DM": 40.0,
    "C": 0.16,
    "SM": 20.0,
    "EX": 1.2,
    "KI": 0.3,
    "KG": 0.4,
    "CS": 0.9,
    "L": 2.0,
    "CI": 0.8,
    "CG": 0.98,
}
FIXTURE_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "lowman_reanalysis_source"
cpu_policy = ExecutionPolicy(
    timeout_seconds=120, network_access=False, max_output_bytes=5_000_000, device="cpu"
)


@pytest.fixture
def calibration_service(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    source = load_normalized_source(FIXTURE_SOURCE)
    repo.create_task(
        task_id="task-1",
        basin_id=str(source.basin["basin_id"]),
        phase="B",
        forcing_mode="R",
    )
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 1, "parameters": PARAMS},
        content_hash="scheme-hash",
    )
    snapshot_root = tmp_path / "snapshots"
    builder = SnapshotBuilder(snapshot_root, DataAccessPolicy(), repo)
    builder.build(
        SnapshotContext(
            task_id="task-1",
            snapshot_id="snap-cal",
            basin_id=str(source.basin["basin_id"]),
            phase="B",
            forcing_mode="R",
            capability="forecast",
            issue_time=datetime(2020, 5, 1, tzinfo=timezone.utc),
            history_days=4,
        ),
        forcing_rows=list(source.forcing_rows),
        flow_rows=list(source.flow_rows),
        basin=source.basin,
    )
    workspaces = MaterializingWorkspaceManager(tmp_path / "runs", repo, snapshot_root=snapshot_root)
    registry = RuntimeRegistry()
    registry.register(XajRuntimeAdapter())
    runner = SandboxRunner(registry, workspaces)
    return repo, CalibrationService(repo, runner=runner)


def test_calibration_service_returns_payload_without_registering_candidate(calibration_service):
    repository, service = calibration_service
    outcome = service.calibrate(
        task_id="task-1",
        base_scheme_id="scheme-base",
        calibration_snapshot_id="snap-cal",
        strategy_id="xaj-bounded-v1",
        policy=cpu_policy,
    )
    assert outcome.action_run_id
    assert outcome.strategy_id == "xaj-bounded-v1"
    assert outcome.candidate_parameters
    assert repository.list_schemes(status="candidate") == []


def test_calibration_service_passes_remaining_budget_to_runtime(calibration_service):
    _, service = calibration_service

    outcome = service.calibrate(
        task_id="task-1",
        base_scheme_id="scheme-base",
        calibration_snapshot_id="snap-cal",
        strategy_id="xaj-bounded-v1",
        policy=cpu_policy,
        evaluation_budget_override=34,
    )

    assert outcome.result_payload["evaluation_budget"] == 34
    assert 0 < outcome.result_payload["model_evaluations"] <= 34


class ResumeRunner:
    def __init__(self, root: Path):
        self.workspaces = SimpleNamespace(root=root)
        self.calls: list[tuple[str, bool]] = []

    def run(self, request, *, resume: bool = False):
        self.calls.append((request.action_run_id, resume))
        workspace = self.workspaces.root / request.task_id / request.action_run_id
        for name in ("work/calibration-state", "output", "logs"):
            (workspace / name).mkdir(parents=True, exist_ok=True)
        stdout = workspace / "logs/stdout.log"
        stderr = workspace / "logs/stderr.log"
        stdout.write_text("attempt\n", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")

        if not resume:
            (workspace / "work/calibration-state/dds-checkpoint.json").write_text(
                "{}", encoding="utf-8"
            )
            return ExecutionResult(
                action_run_id=request.action_run_id,
                status="timed_out",
                exit_code=None,
                wall_time_seconds=1.25,
                peak_memory_bytes=10,
                stdout_artifact="logs/stdout.log",
                stderr_artifact="logs/stderr.log",
                output_artifacts=(),
                result_payload={},
                error_code="timeout",
            )

        payload = {
            "strategy_id": "xaj-bounded-v1",
            "candidate_parameters": {**PARAMS, "K": 0.8},
            "objective_value": 0.42,
            "objective": "nse",
            "param_groups": ["evap", "runoff", "routing"],
            "model_evaluations": 123,
        }
        (workspace / "output/result.json").write_text("{}", encoding="utf-8")
        return ExecutionResult(
            action_run_id=request.action_run_id,
            status="succeeded",
            exit_code=0,
            wall_time_seconds=2.0,
            peak_memory_bytes=20,
            stdout_artifact="logs/stdout.log",
            stderr_artifact="logs/stderr.log",
            output_artifacts=("output/result.json",),
            result_payload=payload,
            error_code=None,
        )


def test_calibration_service_resumes_same_action_and_records_one_terminal_ledger(
    calibration_service, tmp_path
):
    repository, _ = calibration_service
    runner = ResumeRunner(tmp_path / "resume-runs")
    service = CalibrationService(repository, runner=runner, max_resume_attempts=2)

    outcome = service.calibrate(
        task_id="task-1",
        base_scheme_id="scheme-base",
        calibration_snapshot_id="snap-cal",
        strategy_id="xaj-bounded-v1",
        policy=cpu_policy,
    )

    assert len(runner.calls) == 2
    assert runner.calls[0][0] == runner.calls[1][0] == outcome.action_run_id
    assert runner.calls == [(outcome.action_run_id, False), (outcome.action_run_id, True)]
    assert outcome.result_payload["execution_attempts"] == 2
    assert outcome.result_payload["resume_attempts"] == 1

    action = repository.get_action_run(outcome.action_run_id)
    assert action.status == "succeeded"
    cost = repository.get_cost(outcome.action_run_id)
    assert cost.wall_time_seconds == pytest.approx(3.25)
    assert cost.peak_memory_bytes == 20
