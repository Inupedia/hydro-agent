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
    "max_agent_decision_rounds": 20,
    "max_optimization_cycles": 4,
}


def test_run_pause_resume_endpoints(client):
    task_id = client.post("/api/tasks", json=CREATE_BODY).json()["task_id"]
    started = client.post(f"/api/tasks/{task_id}/run")
    assert started.status_code == 200
    paused = client.post(f"/api/tasks/{task_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    resumed = client.post(f"/api/tasks/{task_id}/resume")
    assert resumed.status_code == 200
    status = client.get(f"/api/tasks/{task_id}/run")
    assert status.status_code == 200
    assert status.json()["task_id"] == task_id


def test_timeline_uses_business_language_and_keeps_ids_in_details(client, repository):
    task_id = client.post("/api/tasks", json=CREATE_BODY).json()["task_id"]
    repository.create_action_run(
        task_id=task_id,
        action_run_id="run-1",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id=_ensure_snapshot(repository, task_id),
        scheme_id=repository.get_task_state(task_id).current_scheme_id,
        issue_time="2020-05-01T00:00:00Z",
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-forecast",
            task_id=task_id,
            action_run_id="run-1",
            action=ActionCode.A05_FORECAST,
            status="succeeded",
            observations=("forecast_ok",),
            metrics={"lead_1": 1.0},
            new_information_hash="hash-fc",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-gate",
            task_id=task_id,
            action=ActionCode.A08_GATE,
            status="ROLLBACK",
            observations=("gate_status=ROLLBACK", "lead_guardrail"),
            gates={"status": "ROLLBACK"},
            new_information_hash="hash-gate",
        )
    )
    items = client.get(f"/api/tasks/{task_id}/timeline").json()
    labels = [item["label"] for item in items]
    assert "预报完成" in labels
    assert "候选方案因 Gate 未通过而撤销" in labels
    assert all(not item["label"].startswith("A0") for item in items)
    assert items[0]["details"]["action_run_id"] == "run-1"


def _ensure_snapshot(repository, task_id: str) -> str:
    snapshot_id = f"{task_id}-snap"
    repository.create_snapshot(
        snapshot_id=snapshot_id,
        task_id=task_id,
        source="fixture",
        available_at=datetime(2020, 5, 1, tzinfo=timezone.utc),
        manifest={"files": []},
        content_hash="snap-hash",
    )
    return snapshot_id
