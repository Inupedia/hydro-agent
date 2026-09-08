from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from hydro_agent.agent.contracts import ActionCode, EvidencePacket
from hydro_agent.execution.contracts import ExecutionPolicy
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.workbench.real import RealWorkbenchKernel
from hydro_agent.workbench.validation_gate import (
    RealValidationGate,
    ValidationWindow,
    collect_aligned_lead_series,
    resolve_gate_scheme_ids,
)


POLICY = ExecutionPolicy(
    timeout_seconds=1, network_access=False, max_output_bytes=1024, device="cpu"
)


@pytest.fixture
def repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    return HydroRepository(db)


def _seed_task(repo: HydroRepository, task_id: str = "task-1", *, current: str = "scheme-base"):
    repo.create_task(task_id=task_id, basin_id="b1", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id=task_id,
        model_id="xaj",
        status="base",
        config={"parameters": {"K": 0.7}},
        content_hash="h-base",
    )
    if current != "scheme-base":
        repo.create_scheme(
            scheme_id=current,
            task_id=task_id,
            model_id="xaj",
            status="candidate",
            config={
                "parameters": {"K": 0.8},
                "provenance": {"base_scheme_id": "scheme-base"},
            },
            content_hash="h-current",
        )
    repo.ensure_task_state(task_id, current_scheme_id=current)
    return repo


def _add_optimize_evidence(
    repo: HydroRepository,
    *,
    task_id: str,
    evidence_id: str,
    candidate_scheme_id: str,
    base_scheme_id: str,
):
    repo.add_evidence(
        EvidencePacket(
            evidence_id=evidence_id,
            task_id=task_id,
            action=ActionCode.A07_OPTIMIZE,
            status="succeeded",
            observations=(
                f"candidate_scheme_id={candidate_scheme_id}",
                f"base_scheme_id={base_scheme_id}",
            ),
            gates={
                "candidate_scheme_id": candidate_scheme_id,
                "base_scheme_id": base_scheme_id,
                "strategy_id": "xaj-bounded-v1",
            },
            new_information_hash=f"hash-{evidence_id}",
        )
    )


def _forecast_row(
    *,
    forecast_id: str,
    scheme_id: str,
    issue: date,
    leads: dict[int, float],
    task_id: str = "task-1",
):
    return SimpleNamespace(
        forecast_id=forecast_id,
        scheme_id=scheme_id,
        task_id=task_id,
        issue_time=datetime(issue.year, issue.month, issue.day, tzinfo=timezone.utc),
        lead_values_json={str(k): float(v) for k, v in leads.items()},
    )


def test_build_tools_shares_live_task_configs_dict(tmp_path, repository):
    """Creating a task after build_tools must update Gate/diagnose window dates."""
    live: dict = {}
    kernel = RealWorkbenchKernel(
        repository=repository,
        work_root=tmp_path / "work",
        source_dir=_tiny_source(tmp_path),
        scheme_path=_tiny_scheme(tmp_path),
        report_root=tmp_path / "reports",
    )
    kernel.build_tools(task_configs=live)
    live["task-new"] = {
        "start_date": "2021-06-01",
        "end_date": "2021-06-10",
        "model_id": "xaj",
    }
    window = kernel.validation_gate.window_for("task-new")
    assert window.start == date(2021, 6, 1)
    assert window.end == date(2021, 6, 10)
    # Diagnose path also reads the live dict via kernel._task_configs.
    assert kernel._task_configs is live


def test_resolve_gate_uses_current_scheme_not_initial_base(repository):
    _seed_task(repository, current="scheme-accepted")
    repository.create_scheme(
        scheme_id="scheme-cand-r2",
        task_id="task-1",
        model_id="xaj",
        status="candidate",
        config={
            "parameters": {"K": 0.6},
            "provenance": {"base_scheme_id": "scheme-accepted"},
        },
        content_hash="h-cand-r2",
    )
    # Older candidate still present; must not be selected.
    repository.create_scheme(
        scheme_id="zzz-old-cand",
        task_id="task-1",
        model_id="xaj",
        status="candidate",
        config={
            "parameters": {"K": 0.5},
            "provenance": {"base_scheme_id": "scheme-base"},
        },
        content_hash="h-old",
    )
    _add_optimize_evidence(
        repository,
        task_id="task-1",
        evidence_id="ev-opt-old",
        candidate_scheme_id="zzz-old-cand",
        base_scheme_id="scheme-base",
    )
    _add_optimize_evidence(
        repository,
        task_id="task-1",
        evidence_id="ev-opt-new",
        candidate_scheme_id="scheme-cand-r2",
        base_scheme_id="scheme-accepted",
    )
    base_id, cand_id = resolve_gate_scheme_ids(repository, "task-1")
    assert base_id == "scheme-accepted"
    assert cand_id == "scheme-cand-r2"


def test_aligned_series_ignores_extra_out_of_window_forecast():
    window = ValidationWindow(start=date(2021, 6, 1), end=date(2021, 6, 2))
    truth = {
        date(2021, 6, 2): 10.0,
        date(2021, 6, 3): 11.0,
        date(2021, 6, 4): 12.0,
        date(2021, 6, 5): 13.0,
        # Extra truth that would bias an unfiltered series:
        date(2020, 5, 1): 999.0,
        date(2020, 5, 2): 999.0,
        date(2020, 5, 3): 999.0,
    }
    forecasts = [
        _forecast_row(
            forecast_id="fc-base-1",
            scheme_id="base",
            issue=date(2021, 6, 1),
            leads={1: 9.0, 2: 10.0, 3: 11.0},
        ),
        _forecast_row(
            forecast_id="fc-cand-1",
            scheme_id="cand",
            issue=date(2021, 6, 1),
            leads={1: 10.0, 2: 11.0, 3: 12.0},
        ),
        _forecast_row(
            forecast_id="fc-base-2",
            scheme_id="base",
            issue=date(2021, 6, 2),
            leads={1: 10.5, 2: 11.5, 3: 12.5},
        ),
        _forecast_row(
            forecast_id="fc-cand-2",
            scheme_id="cand",
            issue=date(2021, 6, 2),
            leads={1: 11.0, 2: 12.0, 3: 13.0},
        ),
        # Out-of-window forecast only on base — must not enter either series.
        _forecast_row(
            forecast_id="fc-base-old",
            scheme_id="base",
            issue=date(2020, 4, 29),
            leads={1: 1.0, 2: 1.0, 3: 1.0},
        ),
    ]
    base_series, cand_series = collect_aligned_lead_series(
        forecasts=forecasts,
        base_scheme_id="base",
        candidate_scheme_id="cand",
        truth=truth,
        window=window,
    )
    assert len(base_series[1][0]) == 2
    assert len(cand_series[1][0]) == 2
    assert base_series[1][0] == cand_series[1][0]
    assert 999.0 not in base_series[1][0]
    assert base_series[1][1] == [9.0, 10.5]
    assert cand_series[1][1] == [10.0, 11.0]


def test_aligned_series_drops_issue_missing_on_one_scheme():
    window = ValidationWindow(start=date(2021, 6, 1), end=date(2021, 6, 3))
    truth = {
        date(2021, 6, 2): 10.0,
        date(2021, 6, 3): 11.0,
        date(2021, 6, 4): 12.0,
        date(2021, 6, 5): 13.0,
        date(2021, 6, 6): 14.0,
    }
    forecasts = [
        _forecast_row(
            forecast_id="b1",
            scheme_id="base",
            issue=date(2021, 6, 1),
            leads={1: 9.0, 2: 10.0, 3: 11.0},
        ),
        _forecast_row(
            forecast_id="c1",
            scheme_id="cand",
            issue=date(2021, 6, 1),
            leads={1: 9.5, 2: 10.5, 3: 11.5},
        ),
        # Candidate missing 2021-06-02 — that day must be excluded for both.
        _forecast_row(
            forecast_id="b2",
            scheme_id="base",
            issue=date(2021, 6, 2),
            leads={1: 20.0, 2: 21.0, 3: 22.0},
        ),
        _forecast_row(
            forecast_id="b3",
            scheme_id="base",
            issue=date(2021, 6, 3),
            leads={1: 12.0, 2: 13.0, 3: 14.0},
        ),
        _forecast_row(
            forecast_id="c3",
            scheme_id="cand",
            issue=date(2021, 6, 3),
            leads={1: 12.5, 2: 13.5, 3: 14.5},
        ),
    ]
    base_series, cand_series = collect_aligned_lead_series(
        forecasts=forecasts,
        base_scheme_id="base",
        candidate_scheme_id="cand",
        truth=truth,
        window=window,
    )
    assert len(base_series[1][0]) == 2
    assert 20.0 not in base_series[1][1]


def test_diagnose_uses_current_scheme_after_rollback(tmp_path, repository):
    _seed_task(repository, current="scheme-base")
    repository.create_scheme(
        scheme_id="scheme-rejected",
        task_id="task-1",
        model_id="xaj",
        status="candidate",
        config={
            "parameters": {"K": 0.2},
            "provenance": {"base_scheme_id": "scheme-base"},
        },
        content_hash="h-rej",
    )
    snap = "snap-1"
    repository.create_snapshot(
        snapshot_id=snap,
        task_id="task-1",
        source="fixture",
        available_at=datetime(2021, 6, 10, tzinfo=timezone.utc),
        manifest={"files": []},
        content_hash="snap-hash",
    )
    for run_id, scheme_id, leads in (
        ("run-good", "scheme-base", {1: 100.0, 2: 110.0, 3: 90.0}),
        ("run-bad", "scheme-rejected", {1: 10.0, 2: 11.0, 3: 9.0}),
    ):
        repository.create_action_run(
            task_id="task-1",
            action_run_id=run_id,
            model_id="xaj",
            capability="forecast",
            data_snapshot_id=snap,
            scheme_id=scheme_id,
            issue_time="2021-06-10T00:00:00Z",
        )
        repository.create_forecast(
            forecast_id=f"fc-{scheme_id}",
            task_id="task-1",
            action_run_id=run_id,
            scheme_id=scheme_id,
            data_snapshot_id=snap,
            issue_time="2021-06-10T00:00:00Z",
            lead_values=leads,
            unit="m3/s",
            artifact_ids=(),
        )

    class FakeSource:
        flow_rows = [
            SimpleNamespace(valid_date=date(2021, 6, 11), discharge_m3s=100.0),
            SimpleNamespace(valid_date=date(2021, 6, 12), discharge_m3s=110.0),
            SimpleNamespace(valid_date=date(2021, 6, 13), discharge_m3s=90.0),
        ]

    live = {
        "task-1": {
            "start_date": "2021-06-01",
            "end_date": "2021-06-10",
            "model_id": "xaj",
        }
    }
    kernel = RealWorkbenchKernel(
        repository=repository,
        work_root=tmp_path / "work",
        source_dir=_tiny_source(tmp_path),
        scheme_path=_tiny_scheme(tmp_path),
        report_root=tmp_path / "reports",
    )
    kernel.source = FakeSource()
    kernel.build_tools(task_configs=live)
    result = kernel._diagnose("task-1")
    assert "scheme_id=scheme-base" in result["notes"]
    # Perfect match on current scheme should not claim peak underestimation.
    assert "洪峰低估" not in result["phenomenon"]
    assert result.get("recommended_strategy_id") != "xaj-peak-bias-v1"


def test_gate_bundles_compare_accepted_baseline_not_initial_base(tmp_path, repository):
    _seed_task(repository, current="scheme-accepted")
    repository.create_scheme(
        scheme_id="scheme-cand-r2",
        task_id="task-1",
        model_id="xaj",
        status="candidate",
        config={
            "parameters": {"K": 0.55},
            "provenance": {"base_scheme_id": "scheme-accepted"},
        },
        content_hash="h-cand",
    )
    _add_optimize_evidence(
        repository,
        task_id="task-1",
        evidence_id="ev-opt",
        candidate_scheme_id="scheme-cand-r2",
        base_scheme_id="scheme-accepted",
    )

    class SpyForecast:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def forecast(self, **kwargs):
            self.calls.append((kwargs["scheme_id"], kwargs["issue_time"][:10]))
            return SimpleNamespace(
                forecast_id=f"fc-{len(self.calls)}",
                action_run_id=f"run-{len(self.calls)}",
                lead_values={1: 1.0, 2: 1.0, 3: 1.0},
                artifact_ids=(),
            )

    # Seed aligned forecasts so bundles can score without calling real XAJ.
    snap = "snap-gate"
    repository.create_snapshot(
        snapshot_id=snap,
        task_id="task-1",
        source="fixture",
        available_at=datetime(2021, 6, 1, tzinfo=timezone.utc),
        manifest={"files": []},
        content_hash="snap-hash",
    )
    truth_days = [
        date(2021, 6, 2),
        date(2021, 6, 3),
        date(2021, 6, 4),
        date(2021, 6, 5),
    ]
    window_days = [date(2021, 6, 1), date(2021, 6, 2)]
    # Accepted baseline is better than the new candidate (0.8 vs 0.6 story).
    for day in window_days:
        for scheme_id, scale in (("scheme-accepted", 1.0), ("scheme-cand-r2", 0.6)):
            run_id = f"run-{scheme_id}-{day.isoformat()}"
            repository.create_action_run(
                task_id="task-1",
                action_run_id=run_id,
                model_id="xaj",
                capability="forecast",
                data_snapshot_id=snap,
                scheme_id=scheme_id,
                issue_time=f"{day.isoformat()}T00:00:00Z",
            )
            repository.create_forecast(
                forecast_id=f"fc-{scheme_id}-{day.isoformat()}",
                task_id="task-1",
                action_run_id=run_id,
                scheme_id=scheme_id,
                data_snapshot_id=snap,
                issue_time=f"{day.isoformat()}T00:00:00Z",
                lead_values={
                    1: 100.0 * scale,
                    2: 110.0 * scale,
                    3: 90.0 * scale,
                },
                unit="m3/s",
                artifact_ids=(),
            )

    class FakeSource:
        flow_rows = [
            SimpleNamespace(valid_date=d, discharge_m3s=v)
            for d, v in zip(
                truth_days + [date(2021, 6, 6)],
                [100.0, 110.0, 90.0, 100.0, 110.0],
            )
        ]

    spy = SpyForecast()
    gate = RealValidationGate(
        repository=repository,
        forecast_service=spy,
        source=FakeSource(),
        policy=POLICY,
        task_configs={
            "task-1": {"start_date": "2021-06-01", "end_date": "2021-06-02"},
        },
    )
    base_bundle, cand_bundle = gate.bundles("task-1")
    assert base_bundle.scheme_id == "scheme-accepted"
    assert cand_bundle.scheme_id == "scheme-cand-r2"
    assert base_bundle.primary_score > cand_bundle.primary_score
    # ensure_forecasts still targets accepted + latest candidate, never initial base alone.
    schemes_called = {scheme for scheme, _ in spy.calls}
    assert "scheme-accepted" in schemes_called
    assert "scheme-cand-r2" in schemes_called
    assert "scheme-base" not in schemes_called


def _tiny_scheme(tmp_path):
    path = tmp_path / "scheme.json"
    path.write_text(
        '{"model_id":"xaj","warmup_days":2,"parameters":{"K":0.7,"B":0.3,"IM":0.01,'
        '"UM":20,"LM":60,"DM":40,"C":0.15,"SM":20,"EX":1.2,"KI":0.3,"KG":0.4,'
        '"CS":0.8,"L":1,"CI":0.7,"CG":0.95}}',
        encoding="utf-8",
    )
    return path


def _tiny_source(tmp_path):
    root = tmp_path / "source"
    root.mkdir(parents=True, exist_ok=True)
    (root / "basin.json").write_text(
        '{"basin_id":"b1","area_km2":100.0,"day_timezone":"UTC"}',
        encoding="utf-8",
    )
    (root / "forcing.jsonl").write_text(
        '{"valid_date":"2021-05-01","precipitation_mm_day":0.0,"pet_mm_day":1.0,'
        '"source_kind":"reanalysis","source":"fixture","available_at":"2021-05-02T00:00:00Z"}\n'
        '{"valid_date":"2021-06-15","precipitation_mm_day":0.0,"pet_mm_day":1.0,'
        '"source_kind":"reanalysis","source":"fixture","available_at":"2021-06-16T00:00:00Z"}\n',
        encoding="utf-8",
    )
    (root / "flow.jsonl").write_text(
        '{"valid_date":"2021-05-01","discharge_m3s":1.0,"source":"fixture",'
        '"available_at":"2021-05-02T00:00:00Z"}\n'
        '{"valid_date":"2021-06-15","discharge_m3s":1.0,"source":"fixture",'
        '"available_at":"2021-06-16T00:00:00Z"}\n',
        encoding="utf-8",
    )
    return root
