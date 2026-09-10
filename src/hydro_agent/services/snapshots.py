from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import NormalizedSource, load_normalized_source
from hydro_agent.data.policy import DataAccessViolation
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.execution.hashing import sha256_file


def _parse_issue(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SnapshotResolver:
    def __init__(
        self,
        repository,
        *,
        builder: SnapshotBuilder | None = None,
        source: Path | NormalizedSource | None = None,
        history_days: int = 365,
    ):
        self.repository = repository
        self.builder = builder
        self.source = source
        self.history_days = history_days

    def resolve(
        self,
        task_id: str,
        capability: str,
        issue_time: str,
        *,
        history_days: int | None = None,
    ) -> str:
        task = self.repository.get_task(task_id)
        issue = _parse_issue(issue_time)
        effective_history = int(history_days or self.history_days)
        if effective_history < 1 or effective_history > 36500:
            raise ValueError("history_days must be within 1..36500")
        matches = []
        for snapshot in self.repository.list_snapshots(task_id):
            context = (snapshot.manifest_json or {}).get("context") or {}
            ctx_issue = context.get("issue_time")
            if ctx_issue is None:
                continue
            if (
                context.get("task_id") == task_id
                and context.get("basin_id") == task.basin_id
                and context.get("phase") == task.phase
                and context.get("forcing_mode") == task.forcing_mode
                and context.get("capability") == capability
                and int(context.get("history_days") or self.history_days) == effective_history
                and _parse_issue(str(ctx_issue)) == issue
            ):
                matches.append(snapshot)
        if len(matches) > 1:
            raise DataAccessViolation("ambiguous legal snapshots")
        if len(matches) == 1:
            return matches[0].snapshot_id
        if self.builder is None or self.source is None:
            raise DataAccessViolation("no legal forcing")
        loaded = (
            self.source
            if isinstance(self.source, NormalizedSource)
            else load_normalized_source(Path(self.source))
        )
        snapshot_id = (
            f"{task_id}--{task.phase}--{capability}--h{effective_history}--"
            f"{issue.strftime('%Y%m%dT%H%M%SZ')}"
        )
        context = SnapshotContext(
            task_id=task_id,
            snapshot_id=snapshot_id,
            basin_id=task.basin_id,
            phase=task.phase,
            forcing_mode=task.forcing_mode,
            capability=capability,  # type: ignore[arg-type]
            issue_time=issue,
            history_days=effective_history,
            day_timezone=str(loaded.basin.get("day_timezone", "UTC")),
        )
        path = self.builder.build(
            context,
            forcing_rows=list(loaded.forcing_rows),
            flow_rows=list(loaded.flow_rows),
            basin=loaded.basin,
        )
        stored = self.repository.get_snapshot(snapshot_id)
        if stored.content_hash != sha256_file(path / "snapshot-manifest.json"):
            raise DataAccessViolation("snapshot content hash mismatch")
        return snapshot_id


def new_action_run_id() -> str:
    return f"run-{uuid4().hex}"
