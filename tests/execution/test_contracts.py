import pytest
from pydantic import ValidationError


def test_frozen(execution_request):
    with pytest.raises(ValidationError):
        execution_request.capability = "shell"


@pytest.mark.parametrize(
    "updates",
    [
        {"capability": "shell"},
        {"task_id": "../escape"},
        {"action_run_id": "/tmp/escape"},
        {"unexpected": True},
    ],
)
def test_rejects_invalid_request(execution_request, updates):
    from hydro_agent.execution.contracts import ExecutionRequest

    with pytest.raises(ValidationError):
        ExecutionRequest(**(execution_request.model_dump() | updates))
