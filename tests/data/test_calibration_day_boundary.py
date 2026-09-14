from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from hydro_agent.data.contracts import FlowObservation, SnapshotContext
from hydro_agent.data.policy import DataAccessPolicy


@pytest.mark.parametrize("zone", ["UTC", "Asia/Shanghai", "America/Chicago"])
def test_calibration_includes_last_day_without_reading_development(zone):
    end = date(2000, 5, 4)
    context = SnapshotContext(
        task_id="task-1",
        snapshot_id="snapshot-1",
        basin_id="basin-1",
        phase="B",
        forcing_mode="R",
        capability="calibrate",
        issue_time=datetime.combine(end + timedelta(days=1), time.min, ZoneInfo(zone)),
        history_end_date=end,
        history_days=369,
        day_timezone=zone,
    )
    rows = [
        FlowObservation(
            valid_date=end + timedelta(days=offset),
            discharge_m3s=10,
            source="test",
            available_at=datetime(1999, 1, 1, tzinfo=timezone.utc),
        )
        for offset in range(-3, 2)
    ]
    selected = DataAccessPolicy().select_flow(context, rows)
    assert len(selected) == 4
    assert selected[-1].valid_date == end
    assert context.dates[365:] == tuple(row.valid_date for row in selected)
    assert context.dates[-1] == end
    assert context.flow_dates[-1] == end
