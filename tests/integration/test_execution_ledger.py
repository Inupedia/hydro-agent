"""Real subprocess -> durable ledger integration, using a labeled fixture runtime."""

import sys
from pathlib import Path

import pytest

from hydro_agent.execution.hashing import sha256_file
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.execution.workspace import WorkspaceManager
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


@pytest.mark.parametrize(
    "mode,status",
    [
        ("success", "succeeded"),
        ("fail", "failed"),
        ("sleep", "timed_out"),
        ("missing", "contract_error"),
    ],
)
def test_subprocess_result_survives_database_restart(tmp_path, execution_request, mode, status):
    database = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    database.create_schema()
    repo = HydroRepository(database)
    repo.create_task(task_id="task-1", basin_id="fixture", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-1",
        task_id="task-1",
        model_id="fixture",
        status="base",
        config={},
        content_hash="fixture-scheme",
    )
    repo.create_snapshot(
        snapshot_id="snapshot-1",
        task_id="task-1",
        source="synthetic-fixture",
        available_at=None,
        manifest={},
        content_hash="fixture-snapshot",
    )
    repo.create_action_run(**execution_request.model_dump(exclude={"parameters", "policy"}))
    request = repo.build_execution_request("run-1", {}, execution_request.policy)

    class Adapter:
        model_id = "fixture"
        capabilities = frozenset({"forecast"})

        def command(self, request, workspace):
            return [
                sys.executable,
                str(Path(__file__).parents[1] / "fixtures/fake_runtime.py"),
                str(workspace),
                mode,
            ]

    registry = RuntimeRegistry()
    registry.register(Adapter())
    manager = WorkspaceManager(tmp_path / "runs")
    result = SandboxRunner(registry, manager).run(request)
    assert result.status == status
    workspace = manager.root / "task-1/run-1"
    artifacts = []
    for index, relative in enumerate(
        (result.stdout_artifact, result.stderr_artifact, *result.output_artifacts)
    ):
        path = workspace / relative
        artifacts.append(
            dict(
                artifact_id=f"artifact-{index}",
                kind="execution",
                relative_path=relative,
                sha256=sha256_file(path),
                bytes=path.stat().st_size,
                promoted=relative in result.output_artifacts,
            )
        )
    repo.record_execution_result(result, artifacts)
    database.engine.dispose()
    reopened = HydroRepository(Database(str(database.engine.url)))
    assert reopened.get_action_run("run-1").status == status
    assert reopened.get_cost("run-1").wall_time_seconds > 0
    assert reopened.get_scheme("scheme-1").content_hash == "fixture-scheme"
    for artifact in reopened.list_artifacts("run-1"):
        assert artifact.sha256 == sha256_file(workspace / artifact.relative_path)
        if status != "succeeded":
            assert not artifact.promoted
