from hydro_agent.models.xaj.calibration_state import (
    evaluation_count,
    has_resumable_state,
    load_evaluation_cache,
    persist_evaluation,
)


def test_unscorable_completed_simulation_is_durable_resume_state(tmp_path):
    workspace = tmp_path / "task-1" / "run-1"
    (workspace / "work").mkdir(parents=True)
    key = (("K", 0.75), ("B", 0.25))

    assert evaluation_count(workspace) == 0
    assert has_resumable_state(workspace) is False

    persist_evaluation(
        workspace,
        key=key,
        score=None,
        full_values=[1.0, 2.0, 3.0],
        parameters={"K": 0.75, "B": 0.25},
    )

    assert evaluation_count(workspace) == 1
    assert has_resumable_state(workspace) is True
    cache = load_evaluation_cache(workspace)
    assert cache[key][0] is None
    assert cache[key][1] == [1.0, 2.0, 3.0]
    assert cache[key][2] == {"K": 0.75, "B": 0.25}

    # Content addressing makes a repeated persistence attempt idempotent.
    persist_evaluation(
        workspace,
        key=key,
        score=None,
        full_values=[99.0],
        parameters={"K": 0.75, "B": 0.25},
    )
    assert evaluation_count(workspace) == 1
    assert load_evaluation_cache(workspace)[key][1] == [1.0, 2.0, 3.0]
