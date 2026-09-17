from __future__ import annotations

from datetime import date, datetime
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

    def _history_days_for(self, task_id: str, capability: str) -> int:
        if capability != "calibrate":
            return self.history_days
        try:
            state = self.repository.ensure_task_state(task_id)
            if not state.current_scheme_id:
                return self.history_days
            scheme = self.repository.get_scheme(state.current_scheme_id)
            workbench = dict((scheme.config_json or {}).get("workbench") or {})
            raw = workbench.get("calibration_history_days")
            if raw is None:
                return self.history_days
            value = int(raw)
            if value < 1 or value > 36500:
                raise DataAccessViolation("invalid calibration_history_days")
            return value
        except KeyError:
            return self.history_days

    def resolve(
        self,
        task_id: str,
        capability: str,
        issue_time: str,
        *,
        history_end_date: date | None = None,
    ) -> str:
        task = self.repository.get_task(task_id)
        issue = _parse_issue(issue_time)
        history_days = self._history_days_for(task_id, capability)
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
                and int(context.get("history_days") or self.history_days) == history_days
                and _parse_issue(str(ctx_issue)) == issue
                and context.get("history_end_date")
                == (history_end_date.isoformat() if history_end_date is not None else None)
            ):
                matches.append(snapshot)
        ready = [row for row in matches if self._snapshot_has_required_forcings(task_id, row)]
        if len(ready) > 1:
            raise DataAccessViolation("ambiguous legal snapshots")
        if len(ready) == 1:
            return ready[0].snapshot_id
        if self.builder is None or self.source is None:
            raise DataAccessViolation("no legal forcing")
        loaded = (
            self.source
            if isinstance(self.source, NormalizedSource)
            else load_normalized_source(Path(self.source))
        )
        history_suffix = "" if history_days == self.history_days else f"--h{history_days}"
        if history_end_date is not None:
            history_suffix += f"--end{history_end_date.strftime('%Y%m%d')}"
        forcing_suffix = self._forcing_suffix(task_id)
        snapshot_id = (
            f"{task_id}--{task.phase}--{capability}{history_suffix}{forcing_suffix}--"
            f"{issue.strftime('%Y%m%dT%H%M%SZ')}"
        )
        existing = next((row for row in matches if row.snapshot_id == snapshot_id), None)
        if existing is not None and self._snapshot_has_required_forcings(task_id, existing):
            return existing.snapshot_id
        context = SnapshotContext(
            task_id=task_id,
            snapshot_id=snapshot_id,
            basin_id=task.basin_id,
            phase=task.phase,
            forcing_mode=task.forcing_mode,
            capability=capability,  # type: ignore[arg-type]
            issue_time=issue,
            history_days=history_days,
            history_end_date=history_end_date,
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

    def _required_forcings(self, task_id: str) -> tuple[str, ...]:
        try:
            state = self.repository.ensure_task_state(task_id)
            if not getattr(state, "current_scheme_id", None):
                return ()
            scheme = self.repository.get_scheme(state.current_scheme_id)
            from hydro_agent.models.registry import default_model_registry

            return tuple(default_model_registry().get(scheme.model_id).descriptor.required_forcings)
        except Exception:  # noqa: BLE001
            return ()

    def _forcing_suffix(self, task_id: str) -> str:
        required = self._required_forcings(task_id)
        if "temperature" not in required:
            return ""
        return "--T"

    def _snapshot_has_required_forcings(self, task_id: str, snapshot) -> bool:
        required = self._required_forcings(task_id)
        if "temperature" not in required:
            return True
        rows = (snapshot.manifest_json or {}).get("forcing_rows") or []
        if not rows:
            return False
        return all(row.get("temperature_c") not in (None, "") for row in rows)


def new_action_run_id() -> str:
    return f"run-{uuid4().hex}"
