from sqlalchemy import inspect, text

from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


def test_database(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    with db.session() as session:
        assert session.execute(text("select 1")).scalar_one() == 1
        assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    db.create_schema()
    assert {"tasks", "schemes", "data_snapshots", "action_runs", "artifacts", "cost_ledger"} <= set(
        inspect(db.engine).get_table_names()
    )


def test_create_schema_adds_workflow_columns_to_existing_tasks(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            """CREATE TABLE tasks (
                task_id VARCHAR NOT NULL PRIMARY KEY,
                basin_id VARCHAR NOT NULL,
                phase VARCHAR NOT NULL,
                forcing_mode VARCHAR NOT NULL,
                terminal_status VARCHAR,
                created_at DATETIME NOT NULL
            )"""
        )
        conn.exec_driver_sql(
            """INSERT INTO tasks (task_id, basin_id, phase, forcing_mode, created_at)
               VALUES ('task-old', 'yaogu', 'B', 'R', '2026-01-01T00:00:00')"""
        )
    db.create_schema()
    columns = {column["name"] for column in inspect(db.engine).get_columns("tasks")}
    assert {"workflow_id", "workflow_version", "workflow_hash"} <= columns

    listed = HydroRepository(db).list_tasks()
    assert listed[0].task_id == "task-old"
    assert listed[0].workflow_id is None

    created = HydroRepository(db).create_task(
        task_id="task-new", basin_id="yaogu", phase="B", forcing_mode="R"
    )
    assert created.workflow_id == "hydro-agent-calibration"
