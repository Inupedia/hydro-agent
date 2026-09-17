from fastapi.testclient import TestClient

from hydro_agent.api.app import create_app


def test_spa_index_disables_browser_cache(app_dependencies, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<main>current frontend</main>", encoding="utf-8")
    app = create_app(app_dependencies, static_dir=static)

    with TestClient(app) as client:
        response = client.get("/nested/route")

    assert response.status_code == 200
    assert response.text == "<main>current frontend</main>"
    assert response.headers["cache-control"] == "no-store, max-age=0"
    app.state.executor.shutdown()
