from __future__ import annotations

import json
from pathlib import Path

from hydro_agent.execution.hashing import sha256_file
from hydro_agent.execution.workspace import WorkspaceManager


def canonical_json(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


class ExecutionInputMaterializer:
    def __init__(self, repository, *, snapshot_root: Path, workspaces: WorkspaceManager):
        self.repository = repository
        self.snapshot_root = snapshot_root.resolve()
        self.workspaces = workspaces

    def materialize(self, request, workspace: Path) -> None:
        scheme = self.repository.get_scheme(request.scheme_id)
        snapshot = self.repository.get_snapshot(request.data_snapshot_id)
        config = dict(scheme.config_json)
        # Persist provenance/workbench metadata in DB only; runtimes receive model fields.
        for key in ("provenance", "freeze_contract", "workbench"):
            config.pop(key, None)
        config["scheme_id"] = scheme.scheme_id
        scheme_path = workspace / "input/scheme/scheme.json"
        scheme_path.parent.mkdir(parents=True, exist_ok=True)
        scheme_path.write_text(canonical_json(config), encoding="utf-8")
        basin_id = (snapshot.manifest_json.get("context") or {}).get("basin_id")
        if not basin_id:
            raise ValueError("snapshot manifest missing basin_id")
        source_dir = (self.snapshot_root / basin_id / snapshot.snapshot_id).resolve()
        if not source_dir.is_relative_to(self.snapshot_root) or not source_dir.is_dir():
            raise ValueError("snapshot path escapes storage root")
        files = snapshot.manifest_json.get("files") or []
        for item in files:
            relative = item["relative_path"]
            source = source_dir / relative
            destination = workspace / "input/snapshot" / relative
            self.workspaces.materialize_file(source, destination)
            if sha256_file(destination) != item["sha256"]:
                raise ValueError(f"snapshot file hash mismatch: {relative}")
        manifest_name = "snapshot-manifest.json"
        manifest_source = source_dir / manifest_name
        if manifest_source.exists():
            self.workspaces.materialize_file(
                manifest_source, workspace / "input/snapshot" / manifest_name
            )
