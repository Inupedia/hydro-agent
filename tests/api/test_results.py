from datetime import datetime, timezone

from hydro_agent.agent.contracts import ActionCode, EvidencePacket

CREATE_BODY = {
    "basin_id": "camels_13235000",
    "model_id": "xaj",
    "start_date": "2025-05-01",
    "end_date": "2025-05-10",
    "forcing_mode": "R",
    "base_scheme_id": "scheme-base",
    "allow_optimization": True,
}


def test_results_are_read_from_persisted_scheme_forecast_gate_report(
    client, repository, app_dependencies
):
    task_id = client.post("/api/tasks", json=CREATE_BODY).json()["task_id"]
    state = repository.get_task_state(task_id)
    # Promote current scheme to frozen for result assembly.
    frozen_id = f"{state.current_scheme_id}--frozen"
    repository.create_scheme(
        scheme_id=frozen_id,
        task_id=task_id,
        model_id="xaj",
        status="frozen",
        config={
            "model_id": "xaj",
            "warmup_days": 2,
            "parameters": {"K": 0.7},
            "provenance": {"source_scheme_id": state.current_scheme_id},
        },
        content_hash="frozen-hash",
    )
    repository.update_task_state(task_id, current_scheme_id=frozen_id)
    repository.set_task_phase(task_id, "F")
    repository.set_task_phase(task_id, "E")
    snap = f"{task_id}-snap"
    repository.create_snapshot(
        snapshot_id=snap,
        task_id=task_id,
        source="fixture",
        available_at=datetime(2020, 5, 1, tzinfo=timezone.utc),
        manifest={"files": []},
        content_hash="snap-hash",
    )
    repository.create_action_run(
        task_id=task_id,
        action_run_id="run-fc-1",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id=snap,
        scheme_id=frozen_id,
        issue_time="2020-05-01T00:00:00Z",
    )
    repository.create_forecast(
        forecast_id="fc-1",
        task_id=task_id,
        action_run_id="run-fc-1",
        scheme_id=frozen_id,
        data_snapshot_id=snap,
        issue_time="2020-05-01T00:00:00Z",
        lead_values={1: 10.0, 2: 11.0, 3: 12.0},
        unit="m3/s",
        artifact_ids=(),
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-gate",
            task_id=task_id,
            action=ActionCode.A08_GATE,
            status="KEEP",
            observations=("insufficient_primary_delta",),
            gates={"status": "KEEP"},
            new_information_hash="hash-gate",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-report",
            task_id=task_id,
            action=ActionCode.A12_EVALUATE_REPORT,
            status="succeeded",
            metrics={"NSE": 0.55, "KGE": 0.44, "MAE": 1.1, "Bias": -0.05},
            artifact_ids=("report.json", "report.md"),
            new_information_hash="hash-report",
        )
    )
    app_dependencies.report_artifacts[task_id] = ("report.json", "report.md")
    payload = client.get(f"/api/tasks/{task_id}/results").json()
    assert payload["scheme"]["status"] == "frozen"
    assert payload["forecasts"]
    assert payload["metrics"]["NSE"] is not None
    assert payload["report_artifacts"]
