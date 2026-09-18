from sqlalchemy import inspect

from hydro_agent.persistence.database import Database


def test_database_creates_experience_tables(tmp_path):
    database = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    database.create_schema()

    names = set(inspect(database.engine).get_table_names())
    assert "experience_revisions" in names
    assert "experience_skill_versions" in names
    assert "experience_evolution_events" in names
