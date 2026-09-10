from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from hydro_agent.data.contracts import ForcingRow, SnapshotContext
from hydro_agent.data.policy import DataAccessPolicy

ISSUE = datetime(2025, 5, 1, 0, tzinfo=timezone.utc)


def test_forcing_row_requires_explicit_provenance_and_availability():
    row = ForcingRow(
        valid_date=date(2025, 5, 2),
        precipitation_mm_day=4.0,
        pet_mm_day=2.0,
        source_kind="forecast",
        source="hres",
        available_at=datetime(2025, 5, 1, 0, tzinfo=timezone.utc),
    )
    assert row.source_kind == "forecast"
    with pytest.raises(ValidationError):
        ForcingRow(
            valid_date=date(2025, 5, 2),
            precipitation_mm_day=4.0,
            pet_mm_day=2.0,
            source_kind="forecast",
            source="hres",
            available_at=None,
        )


@pytest.fixture
def f_context():
    return SnapshotContext(
        task_id="task-f",
        snapshot_id="snap-f",
        basin_id="camels_13235000",
        phase="B",
        forcing_mode="F",
        capability="forecast",
        issue_time=ISSUE,
        history_days=2,
    )


@pytest.fixture
def r_context():
    return SnapshotContext(
        task_id="task-r",
        snapshot_id="snap-r",
        basin_id="camels_13235000",
        phase="B",
        forcing_mode="R",
        capability="forecast",
        issue_time=ISSUE,
        history_days=2,
    )


@pytest.fixture
def forcing_rows():
    from hydro_agent.data.contracts import ForcingRow

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
            source_kind="reanalysis",
            source="era5",
            available_at=datetime(2025, 5, 2, tzinfo=timezone.utc),
        ),
        ForcingRow(
            valid_date=date(2025, 5, 2),
            precipitation_mm_day=2.0,
            pet_mm_day=1.0,
            source_kind="reanalysis",
            source="era5",
            available_at=datetime(2025, 5, 3, tzinfo=timezone.utc),
        ),
        ForcingRow(
            valid_date=date(2025, 5, 2),
            precipitation_mm_day=2.0,
            pet_mm_day=1.0,
            source_kind="forecast",
            source="hres",
            available_at=datetime(2025, 5, 1, 0, tzinfo=timezone.utc),
        ),
        ForcingRow(
            valid_date=date(2025, 5, 3),
            precipitation_mm_day=3.0,
            pet_mm_day=1.0,
            source_kind="forecast",
            source="hres",
            available_at=datetime(2025, 5, 1, 0, tzinfo=timezone.utc),
        ),
        ForcingRow(
            valid_date=date(2025, 5, 4),
            precipitation_mm_day=4.0,
            pet_mm_day=1.0,
            source_kind="forecast",
            source="hres",
            available_at=datetime(2025, 5, 1, 0, tzinfo=timezone.utc),
        ),
    ]


@pytest.fixture
def flow_rows():
    from hydro_agent.data.contracts import FlowObservation

    return [
        FlowObservation(
            valid_date=date(2025, 4, 30),
            discharge_m3s=10.0,
            source="usgs",
            available_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
        ),
        FlowObservation(
            valid_date=date(2025, 5, 2),
            discharge_m3s=12.0,
            source="usgs",
            available_at=datetime(2025, 5, 3, tzinfo=timezone.utc),
        ),
        FlowObservation(
            valid_date=date(2025, 5, 3),
            discharge_m3s=11.0,
            source="usgs",
            available_at=datetime(2025, 5, 4, tzinfo=timezone.utc),
        ),
    ]


def test_f_mode_forecast_rejects_future_reanalysis(f_context, forcing_rows):
    selected = DataAccessPolicy().select_forcing(f_context, forcing_rows)
    assert all(
        not (r.valid_date > ISSUE.date() and r.source_kind == "reanalysis") for r in selected
    )


def test_f_mode_accepts_future_forecast_issued_by_issue_time(f_context, forcing_rows):
    selected = DataAccessPolicy().select_forcing(f_context, forcing_rows)
    future = [r for r in selected if r.valid_date > ISSUE.date()]
    assert future
    assert all(r.source_kind == "forecast" and r.available_at <= ISSUE for r in future)


def test_r_mode_may_use_future_reanalysis(r_context, forcing_rows):
    selected = DataAccessPolicy().select_forcing(r_context, forcing_rows)
    assert any(r.valid_date > ISSUE.date() and r.source_kind == "reanalysis" for r in selected)


def test_r_mode_accepts_teacher_observation_forcing(r_context):
    rows = [
        ForcingRow(
            valid_date=day,
            precipitation_mm_day=1.0,
            pet_mm_day=1.0,
            source_kind="observation",
            source="teacher-yaogu-daily",
            available_at=datetime(2025, 5, 2, 8, tzinfo=timezone.utc),
        )
        for day in (date(2025, 4, 30), date(2025, 5, 1), date(2025, 5, 2), date(2025, 5, 3))
    ]
    selected = DataAccessPolicy().select_forcing(r_context, rows)
    assert selected
    assert all(r.source_kind == "observation" for r in selected)


def test_forecast_never_sees_future_observed_discharge(f_context, flow_rows):
    selected = DataAccessPolicy().select_flow(f_context, flow_rows)
    assert all(r.valid_date <= ISSUE.date() for r in selected)


def test_e_phase_evaluate_includes_future_discharge(flow_rows):
    context = SnapshotContext(
        task_id="task-e",
        snapshot_id="snap-e",
        basin_id="camels_13235000",
        phase="E",
        forcing_mode="R",
        capability="evaluate",
        issue_time=ISSUE,
        history_days=2,
    )
    selected = DataAccessPolicy().select_flow(context, flow_rows)
    assert any(r.valid_date > ISSUE.date() for r in selected)
