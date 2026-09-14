"""Load claim-level governed knowledge without granting it execution authority."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from hydro_agent.knowledge.governance import (
    KnowledgeCategory,
    KnowledgeEntry,
    KnowledgeEvidenceBundle,
    KnowledgeQueryContext,
    select_knowledge_entries,
)


class GovernedKnowledgeRepository:
    """Read-only repository for atomized, scope-aware knowledge claims.

    Source review manifests live separately under ``data/review``. Only claims
    intentionally copied into ``data/governed`` are visible here, and visibility
    still does not imply Agent usability: every query passes through the strict
    governance filter before returning an evidence bundle.
    """

    def __init__(self, root: Path | None = None):
        self.root = (
            Path(root)
            if root is not None
            else Path(__file__).with_name("data") / "governed"
        )
        self._entries: dict[tuple[str, int], KnowledgeEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"governed knowledge file must contain an object: {path}")
            raw_entries = payload.get("entries") or []
            if not isinstance(raw_entries, list):
                raise ValueError(f"governed knowledge entries must be a list: {path}")
            for raw in raw_entries:
                entry = KnowledgeEntry.model_validate(raw)
                key = (entry.knowledge_id, entry.revision)
                if key in self._entries:
                    raise ValueError(
                        f"duplicate governed knowledge revision: "
                        f"{entry.knowledge_id}@{entry.revision}"
                    )
                self._entries[key] = entry

    def entries(self) -> tuple[KnowledgeEntry, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))

    def entry(self, knowledge_id: str, revision: int = 1) -> KnowledgeEntry:
        try:
            return self._entries[(knowledge_id, revision)]
        except KeyError as exc:
            raise KeyError(f"unknown governed knowledge: {knowledge_id}@{revision}") from exc

    def query(
        self,
        *,
        context: KnowledgeQueryContext,
        categories: Iterable[KnowledgeCategory] | None = None,
    ) -> KnowledgeEvidenceBundle:
        return select_knowledge_entries(
            self.entries(),
            context=context,
            categories=categories,
        )
