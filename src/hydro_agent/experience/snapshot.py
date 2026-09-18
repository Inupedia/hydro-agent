from __future__ import annotations

import hashlib
import json

from hydro_agent.skills.loader import parse_skill_md
from hydro_agent.skills.snapshot import snapshot_file_bytes


def build_experience_state_snapshot(repository, version_row) -> dict:
    """Freeze latest state revisions that still belong to one promoted rule structure."""

    manifest = dict(version_row.manifest_json or {})
    source_ids = tuple(
        str(item)
        for item in (
            manifest.get("source_experience_ids")
            or tuple(dict(manifest.get("source_revisions") or {}).keys())
        )
    )
    revisions: dict[str, int] = {}
    hashes: dict[str, str] = {}
    for experience_id in sorted(set(source_ids)):
        active = [
            entry
            for entry in repository.list_experience_revisions(experience_id)
            if entry.status == "active"
        ]
        if not active:
            continue
        latest = max(active, key=lambda entry: entry.revision)
        revisions[experience_id] = latest.revision
        if latest.source_hash:
            hashes[experience_id] = latest.source_hash

    payload = {
        "schema_version": 1,
        "skill_version": int(version_row.version),
        "skill_hash": str(version_row.skill_hash),
        "source_revisions": revisions,
        "source_hashes": hashes,
    }
    payload["sha256"] = _snapshot_hash(payload)
    return payload


def freeze_experience_state_for_task(
    repository,
    task_id: str,
    skill_snapshot: dict,
) -> dict | None:
    package = (skill_snapshot.get("skills") or {}).get("calibration-experience")
    if not isinstance(package, dict) or package.get("source") != "agent":
        return None

    try:
        raw = snapshot_file_bytes(package["files"], "SKILL.md").decode("utf-8")
        loaded = parse_skill_md(raw, directory_name="calibration-experience")
        version = int(loaded.meta("hydro-agent-version"))
        version_row = repository.get_experience_skill_version(version)
    except (KeyError, TypeError, ValueError):
        return None

    snapshot = build_experience_state_snapshot(repository, version_row)
    repository.set_experience_state_snapshot(task_id, snapshot)
    return snapshot


def verify_experience_state_snapshot(snapshot: dict) -> None:
    if snapshot.get("schema_version") != 1:
        raise ValueError("invalid Experience State Snapshot schema")
    version = snapshot.get("skill_version")
    skill_hash = snapshot.get("skill_hash")
    revisions = snapshot.get("source_revisions")
    hashes = snapshot.get("source_hashes")
    if not isinstance(version, int) or version < 1:
        raise ValueError("invalid Experience State Snapshot skill_version")
    if not isinstance(skill_hash, str) or not skill_hash:
        raise ValueError("invalid Experience State Snapshot skill_hash")
    if not isinstance(revisions, dict) or any(
        not isinstance(key, str) or not isinstance(value, int) or value < 1
        for key, value in revisions.items()
    ):
        raise ValueError("invalid Experience State Snapshot source_revisions")
    if not isinstance(hashes, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in hashes.items()
    ):
        raise ValueError("invalid Experience State Snapshot source_hashes")
    expected = _snapshot_hash(
        {
            "schema_version": 1,
            "skill_version": version,
            "skill_hash": skill_hash,
            "source_revisions": revisions,
            "source_hashes": hashes,
        }
    )
    if snapshot.get("sha256") != expected:
        raise ValueError("Experience State Snapshot hash mismatch")


def _snapshot_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
