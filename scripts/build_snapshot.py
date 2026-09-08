"""Build an immutable DataSnapshot from a normalized Lowman source directory."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


def build_snapshot(
    *,
    source: Path,
    task_id: str,
    snapshot_id: str,
    phase: str,
    forcing_mode: str,
    capability: str,
    issue_time: str,
    db_url: str,
    output_root: Path,
    history_days: int = 365,
) -> Path:
    db = Database(db_url)
    db.create_schema()
    repository = HydroRepository(db)
    loaded = load_normalized_source(source)
    basin_id = str(loaded.basin["basin_id"])
    try:
        repository.get_task(task_id)
    except KeyError:
        repository.create_task(
            task_id=task_id,
            basin_id=basin_id,
            phase=phase,
            forcing_mode=forcing_mode,
        )
    context = SnapshotContext(
        task_id=task_id,
        snapshot_id=snapshot_id,
        basin_id=basin_id,
        phase=phase,  # type: ignore[arg-type]
        forcing_mode=forcing_mode,  # type: ignore[arg-type]
        capability=capability,  # type: ignore[arg-type]
        issue_time=datetime.fromisoformat(issue_time.replace("Z", "+00:00")),
        history_days=history_days,
        day_timezone=str(loaded.basin.get("day_timezone", "UTC")),
    )
    builder = SnapshotBuilder(output_root, DataAccessPolicy(), repository)
    path = builder.build(
        context,
        forcing_rows=list(loaded.forcing_rows),
        flow_rows=list(loaded.flow_rows),
        basin=loaded.basin,
        source_metadata={"source_dir": str(source.resolve())},
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--phase", choices=("B", "F", "E"), required=True)
    parser.add_argument("--forcing-mode", choices=("R", "F"), required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--issue-time", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--history-days", type=int, default=365)
    args = parser.parse_args()
    path = build_snapshot(
        source=args.source,
        task_id=args.task_id,
        snapshot_id=args.snapshot_id,
        phase=args.phase,
        forcing_mode=args.forcing_mode,
        capability=args.capability,
        issue_time=args.issue_time,
        db_url=args.db,
        output_root=args.output_root,
        history_days=args.history_days,
    )
    print(json.dumps({"snapshot": str(path.resolve())}))
    print(path.resolve())


if __name__ == "__main__":
    main()
