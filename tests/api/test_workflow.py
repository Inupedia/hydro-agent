def test_workflow_definition_endpoint(client):
    response = client.get("/api/workflow-definition")
    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_id"] == "hydro-agent-calibration"
    assert payload["version"] == "2.0.0"
    assert payload["actions"]["A04_DIAGNOSE"]["display_node"] == "diagnose"
    assert payload["actions"]["A07_RESOLVE"]["display_node_by_status"]["ACCEPT"] == "accept"
    assert {"1.0.0", "2.0.0"} <= set(payload["available_versions"])
    assert payload["transitions"]
    named = client.get("/api/workflow-definition/2.0.0")
    assert named.status_code == 200
    assert named.json()["workflow_hash"] == payload["workflow_hash"]
    legacy = client.get("/api/workflow-definition/1.0.0")
    assert legacy.status_code == 200
    assert "A02_REPAIR_DATA" in legacy.json()["actions"]
    assert "A02_REPAIR_DATA" not in payload["actions"]
    assert legacy.json()["workflow_hash"] != payload["workflow_hash"]
    missing = client.get("/api/workflow-definition/9.9.9")
    assert missing.status_code == 404


def test_create_task_binds_workflow_version(client):
    response = client.post(
        "/api/tasks",
        json={
            "basin_id": "yaogu",
            "model_id": "xaj",
            "start_date": "2025-05-01",
            "end_date": "2025-05-10",
            "forcing_mode": "R",
            "base_scheme_id": "scheme-base",
            "allow_optimization": True,
            "max_agent_decision_rounds": 20,
            "max_optimization_cycles": 4,
        },
    )
    assert response.status_code == 201
    task = response.json()
    assert task["workflow_id"] == "hydro-agent-calibration"
    assert task["workflow_version"] == "2.0.0"
    assert task["workflow_hash"].startswith("sha256:")
    health = client.get("/api/health").json()
    assert health["workflow_version"] == "2.0.0"
    assert health["workflow_hash"] == task["workflow_hash"]
