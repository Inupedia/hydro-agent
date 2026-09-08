import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy, DataAccessViolation
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository

FIXTURE_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "lowman_reanalysis_source"
REAL_SOURCE = os.getenv("HYDRO_AGENT_LOWMAN_SOURCE")
SOURCE = Path(REAL_SOURCE) if REAL_SOURCE else FIXTURE_SOURCE
ISSUE = datetime(2020, 5, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def lowman_source():
    if not (SOURCE / "forcing.jsonl").exists():
        pytest.skip(f"Lowman source missing at {SOURCE}")
    loaded = load_normalized_source(SOURCE)
    return {
        "forcing_rows": list(loaded.forcing_rows),
        "flow_rows": list(loaded.flow_rows),
        "basin": loaded.basin,
    }


@pytest.fixture
def repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    return HydroRepository(db)


@pytest.fixture
def snapshot_builder(tmp_path, repository):
    return SnapshotBuilder(tmp_path / "snapshots", DataAccessPolicy(), repository)


@pytest.fixture
def f_context(repository, lowman_source):
    basin_id = str(lowman_source["basin"]["basin_id"])
    repository.create_task(task_id="lowman-f-001", basin_id=basin_id, phase="B", forcing_mode="F")
    return SnapshotContext(
        task_id="lowman-f-001",
        snapshot_id="lowman-f-2020-05-01",
        basin_id=basin_id,
        phase="B",
        forcing_mode="F",
        capability="forecast",
        issue_time=ISSUE,
        history_days=2,
        day_timezone=str(lowman_source["basin"].get("day_timezone", "UTC")),
    )


def test_f_mode_cannot_build_three_future_leads_from_reanalysis_only(
    lowman_source, snapshot_builder, f_context
):
    with pytest.raises(DataAccessViolation, match="no legal forcing"):
        snapshot_builder.build(f_context, **lowman_source)
