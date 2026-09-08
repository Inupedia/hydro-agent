from fastapi.testclient import TestClient

from hydro_agent.api.app import create_app


def test_health_and_openapi_boot(app_dependencies):
    client = TestClient(create_app(app_dependencies))
    assert client.get("/api/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert "/api/tasks" in schema["paths"]


def test_create_task_returns_persisted_task(client):
    response = client.post(
        "/api/tasks",
        json={
            "basin_id": "camels_13235000",
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
    assert task["basin_id"] == "camels_13235000"
    assert task["status"] == "created"
    assert client.get("/api/tasks").json()[0]["task_id"] == task["task_id"]


def test_no_browser_endpoint_executes_arbitrary_action(client):
    assert client.post("/api/tasks/task-1/actions/A07_OPTIMIZE").status_code == 404
