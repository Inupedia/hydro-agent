from datetime import datetime, timezone
from pathlib import Path

import pytest

from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy, DataAccessViolation
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.services.snapshots import SnapshotResolver

FIXTURE_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "lowman_reanalysis_source"
ISSUE = "2020-05-01T00:00:00Z"


@pytest.fixture
def snapshot_resolver(tmp_path):
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
    builder = SnapshotBuilder(tmp_path / "snapshots", DataAccessPolicy(), repo)
    builder.build(
        SnapshotContext(
            task_id="task-1",
            snapshot_id="snap-legal-0501",
            basin_id=str(source.basin["basin_id"]),
            phase="B",
            forcing_mode="R",
            capability="forecast",
            issue_time=datetime(2020, 5, 1, tzinfo=timezone.utc),
            history_days=2,
        ),
        forcing_rows=list(source.forcing_rows),
        flow_rows=list(source.flow_rows),
        basin=source.basin,
    )
    return SnapshotResolver(repo, builder=builder, source=source, history_days=2)


@pytest.fixture
def f_snapshot_resolver(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    source = load_normalized_source(FIXTURE_SOURCE)
    repo.create_task(
        task_id="task-1",
        basin_id=str(source.basin["basin_id"]),
        phase="B",
        forcing_mode="F",
    )
    builder = SnapshotBuilder(tmp_path / "snapshots", DataAccessPolicy(), repo)
    return SnapshotResolver(repo, builder=builder, source=source, history_days=2)


def test_resolver_reuses_exact_existing_legal_snapshot(snapshot_resolver):
    snapshot_id = snapshot_resolver.resolve("task-1", "forecast", ISSUE)
    assert snapshot_id == "snap-legal-0501"


def test_resolver_never_falls_back_to_later_f_mode_snapshot(f_snapshot_resolver):
    with pytest.raises(DataAccessViolation, match="no legal forcing"):
        f_snapshot_resolver.resolve("task-1", "forecast", ISSUE)
