"""Load governed claim assets owned by focused Agent Skills."""

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

_GOVERNED_SKILL_IDS = (
    "hydro-data-readiness",
    "hydro-error-diagnosis",
    "xaj-water-balance",
    "xaj-runoff-generation",
    "xaj-routing-diagnosis",
    "hydro-experiment-design",
    "xaj-calibration",
)


class GovernedKnowledgeRepository:
    """Read-only, scope-aware claim repository aggregated from active Skills."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        roots: Iterable[Path] | None = None,
    ):
        if root is not None and roots is not None:
            raise ValueError("provide root or roots, not both")
        if root is not None:
            self.roots = (Path(root),)
        elif roots is not None:
            self.roots = tuple(Path(item) for item in roots)
        else:
            self.roots = tuple(
                active_skill_root(skill_id) / "assets" / "governed"
                for skill_id in _GOVERNED_SKILL_IDS
            )
        self._entries: dict[tuple[str, int], KnowledgeEntry] = {}
        self._load()

    def _load(self) -> None:
        for root in self.roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("*.json")):
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
