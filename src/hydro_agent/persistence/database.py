from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url, connect_args={"check_same_thread": False})
        if self.engine.dialect.name != "sqlite":
            raise ValueError("only SQLite is supported")

        @event.listens_for(self.engine, "connect")
        def configure(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")

        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        from . import models  # noqa: F401

        Base.metadata.create_all(self.engine)
        self._add_missing_columns()
        # Immutability must survive direct SQL writes, not just repository conventions.
        with self.engine.begin() as conn:
            for table in ("schemes", "data_snapshots", "forecasts"):
                for operation in ("UPDATE", "DELETE"):
                    conn.exec_driver_sql(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{operation}
                        BEFORE {operation} ON {table} BEGIN
                        SELECT RAISE(ABORT, 'immutable record'); END""")
            conn.exec_driver_sql(
                """CREATE UNIQUE INDEX IF NOT EXISTS forecasts_task_scheme_issue
                   ON forecasts(task_id, scheme_id, issue_time)"""
            )

    def _add_missing_columns(self) -> None:
        """SQLite create_all never ALTERs existing tables; add new nullable columns in place."""
        inspector = inspect(self.engine)
        existing_tables = set(inspector.get_table_names())
        with self.engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name not in existing_tables:
                    continue
                existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in existing_columns:
                        continue
                    if not column.nullable and column.server_default is None:
                        raise RuntimeError(
                            f"cannot add non-nullable column {table.name}.{column.name} without a default"
                        )
                    sql_type = column.type.compile(dialect=self.engine.dialect)
                    conn.exec_driver_sql(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {sql_type}'
                    )

    @contextmanager
    def session(self):
        with self._sessions() as session:
            with session.begin():
                yield session
