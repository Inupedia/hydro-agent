"""Campaign Skill Usage: frozen Snapshot × recorded Skill invocations."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def build_skill_usage(*, task_id: str, snapshot: dict | None, decisions: list) -> dict[str, Any]:
    """Summarize which Skills a Campaign froze and which ones were actually invoked."""

    frozen_skills: list[dict[str, Any]] = []
    snapshot_sha256 = None
    snapshot_ids: set[str] = set()
    if snapshot is not None:
        snapshot_sha256 = snapshot.get("sha256")
        for skill_id, package in sorted((snapshot.get("skills") or {}).items()):
            snapshot_ids.add(skill_id)
            files = package.get("files") or {}
            skill_md = files.get("SKILL.md") or {}
            frozen_skills.append(
                {
                    "skill_id": skill_id,
                    "source": package.get("source"),
                    "skill_sha256": skill_md.get("sha256"),
                    "file_count": len(files),
                    "binding": package.get("binding") or {},
                    "in_snapshot": True,
                }
            )

    invocations: list[dict[str, Any]] = []
    by_skill: dict[str, dict[str, Any]] = {}
    contract_counter: dict[str, Counter[str]] = defaultdict(Counter)

    for decision in decisions:
        audits = list(getattr(decision, "activated_skills_json", None) or [])
        for audit in audits:
            if not isinstance(audit, dict):
                continue
            skill_id = str(audit.get("skill_id") or "").strip()
            if not skill_id:
                continue
            contract = str(audit.get("output_contract") or "AgentDecision")
            refs = audit.get("loaded_references") or []
            if not isinstance(refs, list):
                refs = []
            row = {
                "decision_id": getattr(decision, "decision_id", None),
                "round_number": getattr(decision, "round_number", None),
                "action": getattr(decision, "action", None),
                "skill_id": skill_id,
                "skill_sha256": audit.get("skill_sha256"),
                "snapshot_sha256": audit.get("snapshot_sha256") or snapshot_sha256,
                "output_contract": contract,
                "model": audit.get("model") or getattr(decision, "model", None),
                "loaded_reference_count": len(refs),
                "loaded_references": [
                    {"path": item.get("path"), "sha256": item.get("sha256")}
                    for item in refs
                    if isinstance(item, dict)
                ],
            }
            invocations.append(row)
            bucket = by_skill.setdefault(
                skill_id,
                {
                    "skill_id": skill_id,
                    "invocation_count": 0,
                    "in_snapshot": skill_id in snapshot_ids,
                    "snapshot_skill_sha256": next(
                        (
                            item["skill_sha256"]
                            for item in frozen_skills
                            if item["skill_id"] == skill_id
                        ),
                        None,
                    ),
                    "output_contracts": [],
                    "last_round_number": None,
                },
            )
            bucket["invocation_count"] += 1
            bucket["last_round_number"] = row["round_number"]
            contract_counter[skill_id][contract] += 1

    usage_by_skill = []
    for skill_id in sorted(by_skill):
        bucket = by_skill[skill_id]
        bucket["output_contracts"] = [
            {"contract": name, "count": count}
            for name, count in sorted(contract_counter[skill_id].items())
        ]
        usage_by_skill.append(bucket)

    # Include frozen skills that were never invoked so the Campaign inventory is complete.
    for item in frozen_skills:
        if item["skill_id"] not in by_skill:
            usage_by_skill.append(
                {
                    "skill_id": item["skill_id"],
                    "invocation_count": 0,
                    "in_snapshot": True,
                    "snapshot_skill_sha256": item["skill_sha256"],
                    "output_contracts": [],
                    "last_round_number": None,
                }
            )
    usage_by_skill.sort(key=lambda row: (-int(row["invocation_count"]), str(row["skill_id"])))

    return {
        "task_id": task_id,
        "snapshot_sha256": snapshot_sha256,
        "frozen_skills": frozen_skills,
        "invocations": invocations,
        "usage_by_skill": usage_by_skill,
        "invocation_count": len(invocations),
        "frozen_skill_count": len(frozen_skills),
    }
