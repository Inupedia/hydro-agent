"""Immutable, byte-complete Skill packages for task-scoped replay."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path

_PACKAGE_DIRS = {"references", "assets", "scripts"}
_MAX_TOTAL_BYTES = 10_000_000


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture_package(root: Path) -> dict[str, dict[str, str]]:
    base = root.resolve()
    files: dict[str, dict[str, str]] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative != "SKILL.md" and relative.split("/", 1)[0] not in _PACKAGE_DIRS:
            continue
        if not path.resolve().is_relative_to(base):
            raise ValueError(f"Skill package file escapes root: {relative}")
        data = path.read_bytes()
        total += len(data)
        if total > _MAX_TOTAL_BYTES:
            raise ValueError(f"Skill package exceeds {_MAX_TOTAL_BYTES} bytes: {root.name}")
        files[relative] = {"sha256": _sha256(data), "data_b64": base64.b64encode(data).decode("ascii")}
    if "SKILL.md" not in files:
        raise ValueError(f"Skill package lacks SKILL.md: {root.name}")
    return files


def snapshot_file_bytes(files: dict, relative: str) -> bytes:
    try:
        record = files[relative]
        data = base64.b64decode(record["data_b64"], validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise ValueError(f"missing or invalid frozen Skill file: {relative}") from exc
    if _sha256(data) != record.get("sha256"):
        raise ValueError(f"frozen Skill file hash mismatch: {relative}")
    return data


def build_snapshot(skills: dict[str, dict]) -> dict:
    payload = {"schema_version": 1, "skills": skills}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    payload["sha256"] = _sha256(canonical.encode("utf-8"))
    return payload


def verify_snapshot(snapshot: dict) -> None:
    if snapshot.get("schema_version") != 1 or not isinstance(snapshot.get("skills"), dict):
        raise ValueError("invalid Skill Snapshot schema")
    canonical = json.dumps(
        {"schema_version": 1, "skills": snapshot["skills"]},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if _sha256(canonical.encode("utf-8")) != snapshot.get("sha256"):
        raise ValueError("Skill Snapshot hash mismatch")
