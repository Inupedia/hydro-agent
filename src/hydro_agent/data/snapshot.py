import csv
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from hydro_agent.execution.hashing import sha256_file
from hydro_agent.models.xaj.contracts import XajBasin

from .contracts import SnapshotFile, SnapshotManifest
from .policy import DataAccessViolation


def canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


class SnapshotBuilder:
    def __init__(self, root: Path, policy, repository):
        self.root = root.resolve()
        self.policy = policy
        self.repository = repository

    def build(self, context, *, forcing_rows, flow_rows, basin, source_metadata=None):
        task = self.repository.get_task(context.task_id)
        if (task.basin_id, task.phase, task.forcing_mode) != (
            context.basin_id,
            context.phase,
            context.forcing_mode,
        ):
            raise DataAccessViolation("snapshot context does not match task")
        basin = XajBasin(**basin)
        if basin.basin_id != context.basin_id or basin.day_timezone != context.day_timezone:
            raise DataAccessViolation("basin or daily timezone mismatch")
        forcing = self.policy.select_forcing(context, forcing_rows)
        if tuple(r.valid_date for r in forcing) != context.dates:
            selected_dates = {row.valid_date for row in forcing}
            missing = [day for day in context.dates if day not in selected_dates]
            preview = ",".join(day.isoformat() for day in missing[:3])
            raise DataAccessViolation(
                "no legal forcing for complete warmup and three leads: "
                f"issue_date={context.issue_date}, history_days={context.history_days}, "
                f"required={context.dates[0]}..{context.dates[-1]}, "
                f"missing_count={len(missing)}, missing_first={preview or '-'}"
            )
        flows = self.policy.select_flow(context, flow_rows)
        parent = self.root / context.basin_id
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or not parent.resolve().is_relative_to(self.root):
            raise ValueError("snapshot path escapes root")
        path = parent / context.snapshot_id
        path.mkdir(exist_ok=False)
        try:
            with (path / "forcing.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "precipitation_mm_day", "pet_mm_day"])
                writer.writerows(
                    (r.valid_date.isoformat(), r.precipitation_mm_day, r.pet_mm_day)
                    for r in forcing
                )
            with (path / "streamflow.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "discharge_m3s"])
                writer.writerows((r.valid_date.isoformat(), r.discharge_m3s) for r in flows)
            (path / "basin.json").write_text(canonical_json(basin.model_dump()), encoding="utf-8")
            files = []
            for name, role, rows in [
                ("forcing.csv", "forcing", forcing),
                ("streamflow.csv", "observations", flows),
                ("basin.json", "basin", []),
            ]:
                files.append(
                    SnapshotFile(
                        role=role,
                        relative_path=name,
                        sha256=sha256_file(path / name),
                        bytes=(path / name).stat().st_size,
                        row_count=len(rows),
                        min_valid_date=rows[0].valid_date if rows else None,
                        max_valid_date=rows[-1].valid_date if rows else None,
                        sources=tuple(sorted({r.source for r in rows})),
                    )
                )
            manifest = SnapshotManifest(
                snapshot_id=context.snapshot_id,
                context=context,
                files=tuple(files),
                created_at=datetime.now(timezone.utc),
                forcing_rows=tuple(forcing),
                flow_rows=tuple(flows),
                source_metadata=source_metadata or {},
            )
            (path / "snapshot-manifest.json").write_text(
                canonical_json(manifest.model_dump(mode="json")), encoding="utf-8"
            )
            for file in path.iterdir():
                os.chmod(file, 0o444)
            os.chmod(path, 0o555)
            self.repository.create_snapshot(
                snapshot_id=context.snapshot_id,
                task_id=context.task_id,
                source=";".join(sorted({r.source for r in forcing})),
                available_at=max(r.available_at for r in forcing).isoformat(),
                manifest=manifest.model_dump(mode="json"),
                content_hash=sha256_file(path / "snapshot-manifest.json"),
            )
        except Exception:
            os.chmod(path, 0o755)
            shutil.rmtree(path)
            raise
        return path
