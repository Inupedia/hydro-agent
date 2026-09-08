from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hydro_agent.api.app import create_app
from hydro_agent.api.deps import AppDependencies
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


@pytest.fixture
def database(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    return db


@pytest.fixture
def repository(database):
    return HydroRepository(database)


@pytest.fixture
def app_dependencies(repository, tmp_path):
    class InstantRuntime:
        def run_until_terminal(self, task_id: str):
            return []

    deps = AppDependencies(
        repository=repository,
        runtime_factory=lambda: InstantRuntime(),
        report_root=str(tmp_path / "reports"),
    )
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "report.json").write_text('{"ok": true}\n', encoding="utf-8")
    (tmp_path / "reports" / "report.md").write_text("# ok\n", encoding="utf-8")
    return deps


@pytest.fixture
def client(app_dependencies):
    app = create_app(app_dependencies)
    with TestClient(app) as test_client:
        yield test_client
    app.state.executor.shutdown()
