import pytest


@pytest.fixture
def execution_request():
    from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest

    return ExecutionRequest(
        task_id="task-1",
        action_run_id="run-1",
        model_id="fixture",
        capability="forecast",
        data_snapshot_id="snapshot-1",
        scheme_id="scheme-1",
        issue_time="2026-01-01T00:00:00Z",
        parameters={},
        policy=ExecutionPolicy(
            timeout_seconds=1, network_access=False, max_output_bytes=1024, device="cpu"
        ),
    )
