import json
from datetime import date, datetime, timezone

import pytest

from hydro_agent.data.contracts import FlowObservation, ForcingRow, SnapshotContext
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository

ISSUE = datetime(2025, 5, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-f", basin_id="camels_13235000", phase="B", forcing_mode="F")
    return repo


@pytest.fixture
def f_context():
    return SnapshotContext(
        task_id="task-f",
        snapshot_id="snap-f-1",
        basin_id="camels_13235000",
        phase="B",
        forcing_mode="F",
        capability="forecast",
        issue_time=ISSUE,
        history_days=2,
    )


@pytest.fixture
def forcing_rows():
    return [
        ForcingRow(
            valid_date=date(2025, 4, 30),
            precipitation_mm_day=1.0,
            pet_mm_day=1.0,
            source_kind="reanalysis",
            source="era5",
            available_at=datetime(2025, 4, 30, tzinfo=timezone.utc),
        ),
        ForcingRow(
            valid_date=date(2025, 5, 1),
            precipitation_mm_day=1.0,
            pet_mm_day=1.0,
            source_kind="forecast",
            source="hres",
            available_at=ISSUE,
        ),
        ForcingRow(
            valid_date=date(2025, 5, 2),
            precipitation_mm_day=2.0,
            pet_mm_day=1.0,
            source_kind="forecast",
            source="hres",
            available_at=ISSUE,
        ),
        ForcingRow(
            valid_date=date(2025, 5, 3),
            precipitation_mm_day=3.0,
            pet_mm_day=1.0,
            source_kind="forecast",
            source="hres",
            available_at=ISSUE,
        ),
        ForcingRow(
            valid_date=date(2025, 5, 4),
            precipitation_mm_day=4.0,
            pet_mm_day=1.0,
            source_kind="forecast",
            source="hres",
            available_at=ISSUE,
        ),
    ]


@pytest.fixture
def flow_rows():
    return [
        FlowObservation(
            valid_date=date(2025, 4, 30),
            discharge_m3s=10.0,
            source="usgs",
            available_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
        )
    ]


@pytest.fixture
def basin():
    return {"basin_id": "camels_13235000", "area_km2": 1184.0}


@pytest.fixture
def snapshot_builder(tmp_path, repository):
    return SnapshotBuilder(tmp_path / "snapshots", DataAccessPolicy(), repository)


def test_snapshot_contains_only_policy_selected_rows(
    snapshot_builder, f_context, forcing_rows, flow_rows, basin
):
    path = snapshot_builder.build(
        f_context, forcing_rows=forcing_rows, flow_rows=flow_rows, basin=basin
    )
    manifest = json.loads((path / "snapshot-manifest.json").read_text())
    assert manifest["context"]["forcing_mode"] == "F"
    assert {f["relative_path"] for f in manifest["files"]} == {
        "forcing.csv",
        "streamflow.csv",
        "basin.json",
    }
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])


def test_rebuilding_same_snapshot_id_raises(
    snapshot_builder, f_context, forcing_rows, flow_rows, basin
):
    snapshot_builder.build(f_context, forcing_rows=forcing_rows, flow_rows=flow_rows, basin=basin)
    with pytest.raises(FileExistsError):
        snapshot_builder.build(
            f_context, forcing_rows=forcing_rows, flow_rows=flow_rows, basin=basin
        )
