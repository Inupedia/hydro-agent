from fastapi.testclient import TestClient

from hydro_agent.api.app import create_app


def test_health_and_openapi_boot(app_dependencies):
    client = TestClient(create_app(app_dependencies))
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert "mode" in health
    schema = client.get("/openapi.json").json()
    assert "/api/tasks" in schema["paths"]


def test_create_task_returns_persisted_task(client):
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
    assert task["basin_id"] == "yaogu"
    assert task["status"] == "created"
    assert client.get("/api/tasks").json()[0]["task_id"] == task["task_id"]


def test_create_task_persists_formal_rolling_sampling_policy(client, app_dependencies):
    response = client.post(
        "/api/tasks",
        json={
            "basin_id": "yaogu",
            "model_id": "xaj",
            "start_date": "2025-05-01",
            "end_date": "2025-05-20",
            "forcing_mode": "R",
            "base_scheme_id": "scheme-base",
            "allow_optimization": True,
            "development_start_date": "2025-05-05",
            "development_end_date": "2025-05-10",
            "final_test_start_date": "2025-05-11",
            "final_test_end_date": "2025-05-20",
            "development_rolling_issue_limit": 2,
            "final_test_rolling_issue_limit": 3,
            "search_objective_policy": "adaptive",
        },
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]
    config = app_dependencies.task_configs[task_id]
    assert config["development_rolling_issue_limit"] == 2
    assert config["final_test_rolling_issue_limit"] == 3
    assert config["search_objective_policy"] == "adaptive"
    assert config["development_end_date"] == "2025-05-10"
    assert config["end_date"] == "2025-05-07"
    assert config["development_rolling_issue_dates"] == ["2025-05-05", "2025-05-07"]


def test_delete_task_removes_persisted_case(client):
    created = client.post(
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
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
    assert client.get("/api/tasks").json() == []
    assert client.get(f"/api/tasks/{task_id}").status_code == 404


def test_no_browser_endpoint_executes_arbitrary_action(client):
    assert client.post("/api/tasks/task-1/actions/A07_OPTIMIZE").status_code == 404
