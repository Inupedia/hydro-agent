from datetime import datetime, timezone

import pytest

from hydro_agent.agent.contracts import ActionCode, EvidencePacket
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository

ISSUE = datetime(2020, 5, 1, tzinfo=timezone.utc)


@pytest.fixture
def database(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    return db


@pytest.fixture
def seeded_repository(database):
    repo = HydroRepository(database)
    repo.create_task(task_id="task-1", basin_id="camels_13235000", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": {"K": 0.7}},
        content_hash="scheme-hash",
    )
    repo.create_snapshot(
        snapshot_id="snap-1",
        task_id="task-1",
        source="fixture",
        available_at=ISSUE,
        manifest={"files": []},
        content_hash="snap-hash",
    )
    return repo


def test_world_state_contains_only_decision_relevant_projection(seeded_repository):
    view = WorldStateBuilder(seeded_repository).build("task-1")
    assert view.task.task_id == "task-1"
    assert view.model.model_id == "xaj"
    assert view.scheme.scheme_id == "scheme-base"
    assert view.permissions.safe_actions
    assert not hasattr(view, "database_url")
    assert not hasattr(view, "filesystem_root")


def test_world_state_surfaces_audited_basin_prior_from_diagnosis(seeded_repository):
    seeded_repository.ensure_task_state("task-1", current_scheme_id="scheme-base")
    seeded_repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-diagnosis-1",
            task_id="task-1",
            action=ActionCode.A06_DIAGNOSE,
            status="succeeded",
            observations=(
                'basin_attributes_json={"aridity": 0.62, "runoff_ratio": 0.41}',
            ),
            metrics={"nse": 0.2},
            gates={
                "hypothesis": "MODEL",
                "recommended_action": "A07_OPTIMIZE",
                "recommended_strategy_id": "xaj-bounded-v1",
            },
            new_information_hash="hash-diagnosis-1",
        )
    )

    view = WorldStateBuilder(seeded_repository).build("task-1")
    attrs = view.hydro.diagnosis["basin_attributes"]
    assert attrs == {"aridity": 0.62, "runoff_ratio": 0.41}
    assert view.hydro.diagnosis["metrics"]["nse"] == 0.2


def test_agent_budget_survives_repository_reopen(database, seeded_repository):
    seeded_repository.ensure_task_state("task-1", current_scheme_id="scheme-base")
    seeded_repository.update_task_state(
        "task-1",
        current_scheme_id="scheme-base",
        agent_rounds_used=3,
        optimization_cycles_used=1,
        paused=False,
        needs_follow_up=True,
    )
    reopened = HydroRepository(database)
    state = reopened.get_task_state("task-1")
    assert state.agent_rounds_used == 3
    assert state.optimization_cycles_used == 1
