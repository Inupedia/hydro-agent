"""Load governed claim assets owned by Agent Skills."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from hydro_agent.skill_paths import active_skill_root
from hydro_agent.skills.governance import (
    KnowledgeCategory,
    KnowledgeEntry,
    KnowledgeEvidenceBundle,
    KnowledgeQueryContext,
    select_knowledge_entries,
)


class GovernedKnowledgeRepository:
    """Read-only, scope-aware claim repository for one active Skill package.

    The historical class name is intentionally kept inside ``hydro_agent.skills``
    because existing artifacts use ``knowledge_id`` fields. Runtime ownership is
    no longer ambiguous: these claims are Skill assets and only advisory entries
    that pass governance may influence planning.
    """

    def __init__(self, root: Path | None = None):
        self.root = (
            Path(root)
            if root is not None
            else active_skill_root("xaj-calibration") / "assets" / "governed"
        )
        self._entries: dict[tuple[str, int], KnowledgeEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"governed Skill asset must contain an object: {path}")
            raw_entries = payload.get("entries") or []
            if not isinstance(raw_entries, list):
                raise ValueError(f"governed Skill entries must be a list: {path}")
            for raw in raw_entries:
                entry = KnowledgeEntry.model_validate(raw)
                key = (entry.knowledge_id, entry.revision)
                if key in self._entries:
                    raise ValueError(
                        f"duplicate governed Skill claim: {entry.knowledge_id}@{entry.revision}"
                    )
                self._entries[key] = entry

    def entries(self) -> tuple[KnowledgeEntry, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))

    def entry(self, knowledge_id: str, revision: int = 1) -> KnowledgeEntry:
        try:
            return self._entries[(knowledge_id, revision)]
        except KeyError as exc:
            raise KeyError(f"unknown governed Skill claim: {knowledge_id}@{revision}") from exc

    def query(
        self,
        *,
        context: KnowledgeQueryContext,
        categories: Iterable[KnowledgeCategory] | None = None,
    ) -> KnowledgeEvidenceBundle:
        return select_knowledge_entries(self.entries(), context=context, categories=categories)
