from datetime import datetime, timezone

from hydro_agent.data.contracts import SnapshotContext


def _context(capability: str) -> SnapshotContext:
    return SnapshotContext(
        task_id="task-1",
        snapshot_id=f"snap-{capability}",
        basin_id="leaf-river",
        phase="B",
        forcing_mode="R",
        capability=capability,  # type: ignore[arg-type]
        issue_time=datetime(1990, 2, 25, tzinfo=timezone.utc),
        history_days=10,
        day_timezone="UTC",
    )


def test_forecast_snapshot_keeps_three_day_horizon() -> None:
    context = _context("forecast")
    assert len(context.dates) == 13
    assert context.dates[-1].isoformat() == "1990-02-28"


def test_calibration_snapshot_stops_at_issue_date() -> None:
    context = _context("calibrate")
    assert len(context.dates) == 10
    assert context.dates[-1].isoformat() == "1990-02-25"
