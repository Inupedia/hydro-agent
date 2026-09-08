from datetime import timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from hydro_agent.execution.contracts import ExecutionResult
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


@pytest.fixture
def repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="13235000", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-1",
        task_id="task-1",
        model_id="fixture",
        status="base",
        config={"warmup_days": 365},
        content_hash="abc",
    )
    repo.create_snapshot(
        snapshot_id="snapshot-1",
        task_id="task-1",
        source="fixture",
        available_at="2026-01-01T08:00:00+08:00",
        manifest={"files": []},
        content_hash="def",
    )
    return repo


def create_action(repo, request):
    repo.create_action_run(**request.model_dump(exclude={"parameters", "policy"}))


def result(status="succeeded"):
    return ExecutionResult(
        action_run_id="run-1",
        status=status,
        exit_code=0 if status == "succeeded" else 7,
        wall_time_seconds=1.25,
        peak_memory_bytes=4096,
        stdout_artifact="logs/stdout.log",
        stderr_artifact="logs/stderr.log",
        output_artifacts=("output/result.json",),
        result_payload={"value": 42},
        error_code=None,
    )


def artifact(promoted=True):
    return dict(
        artifact_id="a1",
        kind="result",
        relative_path="output/result.json",
        sha256="abc",
        bytes=100,
        promoted=promoted,
    )


def test_immutable_inputs(repository):
    assert repository.get_scheme("scheme-1").content_hash == "abc"
    snapshot = repository.get_snapshot("snapshot-1")
    assert snapshot.available_at.hour == 0
    assert snapshot.available_at.tzinfo == timezone.utc
    for sql in ["UPDATE schemes SET content_hash='changed'", "DELETE FROM data_snapshots"]:
        with pytest.raises(IntegrityError, match="immutable record"):
            with repository.database.session() as session:
                session.execute(text(sql))
    assert repository.get_scheme("scheme-1").content_hash == "abc"


def test_foreign_key_enforced(repository):
    with pytest.raises(IntegrityError):
        repository.create_scheme(
            scheme_id="orphan",
            task_id="missing",
            model_id="fixture",
            status="base",
            config={},
            content_hash="abc",
        )


def test_request_from_records(repository, execution_request):
    create_action(repository, execution_request)
    built = repository.build_execution_request(
        "run-1", parameters={}, policy=execution_request.policy
    )
    assert built.scheme_id == execution_request.scheme_id
    assert built.data_snapshot_id == execution_request.data_snapshot_id


@pytest.mark.parametrize("change", [{"model_id": "wrong"}, {"task_id": "other"}])
def test_reference_mismatch(repository, execution_request, change):
    repository.create_task(task_id="other", basin_id="13235000", phase="B", forcing_mode="R")
    with pytest.raises(ValueError):
        repository.create_action_run(
            **(execution_request.model_dump(exclude={"parameters", "policy"}) | change)
        )


def test_terminal_write_and_reopen(repository, execution_request):
    create_action(repository, execution_request)
    repository.record_execution_result(result(), [artifact()])
    reopened = HydroRepository(Database(str(repository.database.engine.url)))
    assert reopened.get_action_run("run-1").status == "succeeded"
    assert reopened.get_cost("run-1").wall_time_seconds == 1.25
    assert reopened.list_artifacts("run-1")[0].sha256 == "abc"
    with pytest.raises(ValueError, match="terminal"):
        reopened.record_execution_result(result(), [artifact()])
    with pytest.raises(ValueError, match="pending"):
        reopened.build_execution_request("run-1", {}, execution_request.policy)


def test_failed_promotion_rejected(repository, execution_request):
    create_action(repository, execution_request)
    with pytest.raises(ValueError, match="cannot promote"):
        repository.record_execution_result(result("failed"), [artifact()])
    assert repository.get_action_run("run-1").status == "pending"
    repository.record_execution_result(result("failed"), [artifact(False)])
    assert repository.get_action_run("run-1").status == "failed"


def test_atomic_rollback_on_duplicate_artifact(repository, execution_request):
    create_action(repository, execution_request)
    with pytest.raises(IntegrityError):
        repository.record_execution_result(result(), [artifact(), artifact()])
    assert repository.get_action_run("run-1").status == "pending"
    assert repository.list_artifacts("run-1") == []
    with pytest.raises(KeyError):
        repository.get_cost("run-1")


@pytest.mark.parametrize("phase", ["F", "E"])
def test_optimization_forbidden(repository, execution_request, phase):
    with repository.database.session() as session:
        session.execute(text("UPDATE tasks SET phase=:phase"), {"phase": phase})
    with pytest.raises(ValueError, match="optimization forbidden"):
        repository.create_action_run(
            **(
                execution_request.model_dump(exclude={"parameters", "policy"})
                | {"capability": "calibrate"}
            )
        )
