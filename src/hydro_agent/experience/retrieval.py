from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel


class ExperienceMatch(FrozenModel):
    experience_id: str
    revision: int = Field(ge=1)
    category: str
    relevance: float = Field(ge=0.0, le=1.0)
    transfer_weight: float = Field(gt=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    scope_rank: int = Field(ge=1, le=4)
    decision: dict[str, Any]
    pattern: dict[str, Any]
    supporting_count: int = Field(ge=0)
    contradicting_count: int = Field(ge=0)

    @property
    def effective_confidence(self) -> float:
        return self.confidence * self.transfer_weight * max(self.relevance, 0.25)


class ExperienceRetriever:
    """Deterministic scope + pattern retrieval over a frozen Experience revision set."""

    def __init__(self, repository):
        self.repository = repository

    def retrieve(
        self,
        *,
        model_id: str,
        basin_id: str,
        diagnosis: Mapping[str, Any] | None,
        limit: int = 12,
        revision_map: Mapping[str, int] | None = None,
    ) -> tuple[ExperienceMatch, ...]:
        if limit < 1:
            raise ValueError("limit must be >= 1")

        entries = self._entries(model_id=model_id, revision_map=revision_map)
        diagnosis_flat = _flatten(diagnosis or {})
        matches: list[ExperienceMatch] = []
        for entry in entries:
            scope = _scope_score(entry, model_id=model_id, basin_id=basin_id)
            if scope is None:
                continue
            scope_rank, transfer_weight = scope
            relevance = _pattern_relevance(entry.pattern, diagnosis_flat)
            if entry.pattern and relevance <= 0:
                continue
            matches.append(
                ExperienceMatch(
                    experience_id=entry.experience_id,
                    revision=entry.revision,
                    category=entry.category,
                    relevance=relevance,
                    transfer_weight=transfer_weight,
                    confidence=entry.confidence,
                    scope_rank=scope_rank,
                    decision=dict(entry.decision),
                    pattern=dict(entry.pattern),
                    supporting_count=len(entry.supporting_evidence),
                    contradicting_count=len(entry.contradicting_evidence),
                )
            )

        matches.sort(
            key=lambda item: (
                -item.scope_rank,
                -item.relevance,
                -item.confidence,
                item.experience_id,
                -item.revision,
            )
        )
        return tuple(matches[:limit])

    def _entries(self, *, model_id: str, revision_map: Mapping[str, int] | None):
        if revision_map is None:
            return self.repository.list_active_experiences(model_id=model_id)

        entries = []
        for experience_id, revision in sorted(revision_map.items()):
            try:
                entry = self.repository.get_experience(experience_id, int(revision))
            except KeyError:
                continue
            if entry.status == "active":
                entries.append(entry)
        return entries


def _scope_score(entry, *, model_id: str, basin_id: str) -> tuple[int, float] | None:
    models = tuple(entry.scope.model_ids)
    basins = tuple(entry.scope.basin_ids)

    if models and model_id not in models:
        return None

    if models:
        if basin_id in basins:
            return 4, 1.0
        if basins:
            return 3, 0.78
        return 2, 0.68

    return 1, 0.50


def _pattern_relevance(
    pattern: Mapping[str, Any],
    diagnosis_flat: Mapping[str, Any],
) -> float:
    flat_pattern = _flatten(pattern)
    if not flat_pattern:
        return 1.0

    matched = 0
    for key, expected in flat_pattern.items():
        if key not in diagnosis_flat:
            continue
        if _equivalent(diagnosis_flat[key], expected):
            matched += 1
    return matched / len(flat_pattern)


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            output.update(_flatten(item, name))
            # Also expose leaf keys when unambiguous enough for first-version
            # Experience patterns such as {"peak_bias": "negative"}.
            for nested_key, nested_value in _flatten(item).items():
                output.setdefault(nested_key, nested_value)
        else:
            output[name] = item
            output.setdefault(str(key), item)
    return output


def _equivalent(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().casefold() == expected.strip().casefold()
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= 1e-12
    return actual == expected
