import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

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


def test_create_schema_adds_skill_audit_to_existing_decision_table(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    with db.engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE agent_decisions DROP COLUMN activated_skills_json")
    db.create_schema()
    columns = {column["name"] for column in inspect(db.engine).get_columns("agent_decisions")}
    assert "activated_skills_json" in columns


def test_create_schema_adds_skill_snapshot_to_existing_task_state(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    with db.engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER task_state_skill_snapshot_no_replace")
        conn.exec_driver_sql("ALTER TABLE task_state DROP COLUMN skill_snapshot_json")
    db.create_schema()
    columns = {column["name"] for column in inspect(db.engine).get_columns("task_state")}
    assert "skill_snapshot_json" in columns


def test_skill_snapshot_cannot_be_replaced_by_direct_sql(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repository = HydroRepository(db)
    repository.create_task(task_id="task-skill", basin_id="yaogu", phase="B", forcing_mode="R")
    repository.create_scheme(
        scheme_id="scheme-skill", task_id="task-skill", model_id="xaj", config={},
        status="base", content_hash="scheme-hash",
    )
    repository.ensure_task_state("task-skill", current_scheme_id="scheme-skill")
    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE task_state SET skill_snapshot_json = '{\"sha256\":\"frozen\"}' "
            "WHERE task_id = 'task-skill'"
        )
        conn.exec_driver_sql(
            "UPDATE task_state SET paused = 1 WHERE task_id = 'task-skill'"
        )
    with pytest.raises(IntegrityError, match="immutable Skill Snapshot"):
        with db.engine.begin() as conn:
            conn.exec_driver_sql(
                "UPDATE task_state SET skill_snapshot_json = '{\"sha256\":\"changed\"}' "
                "WHERE task_id = 'task-skill'"
            )
