from datetime import datetime, timezone

import pytest

from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.replay.freeze import FreezeService

ISSUE = datetime(2020, 5, 1, tzinfo=timezone.utc)


@pytest.fixture
def seeded_repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="b1", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": {"K": 0.7}},
        content_hash="scheme-hash",
    )
    repo.ensure_task_state("task-1", current_scheme_id="scheme-base")
    return repo


@pytest.fixture
def freeze_service(seeded_repository):
    return FreezeService(seeded_repository)


def test_freeze_creates_new_scheme_without_mutating_source(seeded_repository, freeze_service):
    before = seeded_repository.get_scheme("scheme-base").content_hash
    frozen_id = freeze_service.freeze(task_id="task-1", source_scheme_id="scheme-base")
    source = seeded_repository.get_scheme("scheme-base")
    frozen = seeded_repository.get_scheme(frozen_id)
    assert source.content_hash == before
    assert frozen.scheme_id != source.scheme_id
    assert frozen.status == "frozen"
    assert frozen.config_json["provenance"]["source_scheme_id"] == "scheme-base"


def test_freeze_rejects_missing_warmup(seeded_repository, freeze_service):
    seeded_repository.create_scheme(
        scheme_id="scheme-bad",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "parameters": {"K": 0.7}},
        content_hash="bad-hash",
    )
    with pytest.raises(ValueError, match="missing warmup_days"):
        freeze_service.freeze(task_id="task-1", source_scheme_id="scheme-bad")
