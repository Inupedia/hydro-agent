from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url)
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

    @contextmanager
    def session(self):
        with self._sessions() as session:
            with session.begin():
                yield session
