from sqlalchemy import inspect, text

from hydro_agent.persistence.database import Database


def test_database(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    with db.session() as session:
        assert session.execute(text("select 1")).scalar_one() == 1
        assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    db.create_schema()
    assert {"tasks", "schemes", "data_snapshots", "action_runs", "artifacts", "cost_ledger"} <= set(
        inspect(db.engine).get_table_names()
    )
