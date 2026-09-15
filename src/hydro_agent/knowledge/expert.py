"""Governed executable expert priors for calibration experiment design.

This module is intentionally a small advisory rule engine, not a knowledge
repository. Source claims live in governed knowledge; only the few priors with
explicit machine semantics are evaluated here, after the common governance
filter accepts them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.knowledge.governance import (
    KnowledgeApplicability,
    KnowledgeEntry,
    KnowledgeQueryContext,
    select_knowledge_entries,
)
from hydro_agent.skill_paths import active_skill_root


class _ExpertPriorRule(FrozenModel):
    rule_id: str = Field(min_length=1)
    signal: str = Field(min_length=1)
    threshold: float | int | None = None
    priority: int = 0
    recommendation: dict[str, Any] = Field(default_factory=dict)


class ExpertPriorAdvice(FrozenModel):
    source_id: str
    status: str
    authority: str
    matched_prior_refs: tuple[str, ...] = ()
    recommended_param_groups: tuple[str, ...] | None = None
    recommended_objective: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def is_normative(self) -> bool:
        return False


class BasinHydroProfile(FrozenModel):
    aridity: float | None = None
    runoff_ratio: float | None = None
    baseflow_index: float | None = None
    frac_snow: float | None = None
    climate_zone: str | None = None

    @property
    def available(self) -> bool:
        return any(
            value is not None
            for value in (
                self.aridity,
                self.runoff_ratio,
                self.baseflow_index,
                self.frac_snow,
                self.climate_zone,
            )
        )


class ExpertPriorEngine:
    """Evaluate executable advisory priors behind the governance filter.

    Search-boundary safety, Gate behavior and closeout policy remain deterministic
    protocol concerns and are deliberately absent from this engine. The default
    prior assets travel with the active xaj-calibration Agent Skill so a writable
    user skill override can update advisory knowledge without modifying source.
    """

    def __init__(self, root: Path | None = None):
        self.root = (
            Path(root)
            if root is not None
            else active_skill_root("xaj-calibration") / "assets" / "expert"
        )
        self._sources: dict[str, dict[str, Any]] = {}
        self._rules: dict[str, tuple[str, _ExpertPriorRule]] = {}
        self._entries: dict[str, KnowledgeEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.json")):
            source_bytes = path.read_bytes()
            payload = json.loads(source_bytes.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"expert prior file must contain an object: {path}")
            source_id = str(payload.get("knowledge_id") or "").strip()
            if not source_id:
                raise ValueError(f"expert prior source missing knowledge_id: {path}")
            if source_id in self._sources:
                raise ValueError(f"duplicate expert prior source: {source_id}")
            self._sources[source_id] = payload

            governance = dict(payload.get("governance") or {})
            applicability = KnowledgeApplicability.model_validate(
                governance.get("applicability") or {}
            )
            source_hash = f"sha256:{hashlib.sha256(source_bytes).hexdigest()}"
            for raw in payload.get("rules") or []:
                rule = _ExpertPriorRule.model_validate(raw)
                if rule.rule_id in self._rules:
                    raise ValueError(f"duplicate expert prior rule: {rule.rule_id}")
                recommendation = dict(rule.recommendation)
                claim = str(
                    recommendation.get("message")
                    or f"{rule.signal} -> {json.dumps(recommendation, ensure_ascii=False)}"
                )
                entry = KnowledgeEntry(
                    knowledge_id=rule.rule_id,
                    revision=int(governance.get("revision") or 1),
                    category=governance.get("category") or "expert_diagnostic_prior",
                    authority=payload.get("authority") or "advisory_only",
                    claim=claim,
                    source_id=source_id,
                    source_hash=source_hash,
                    source_locator=f"{path.name}#rule={rule.rule_id}",
                    applicability=applicability,
                    verification_status=governance.get("verification_status") or "unverified",
                    review_status=governance.get("review_status") or "pending",
                    exposure_tags=tuple(governance.get("exposure_tags") or ()),
                    evidence_dataset_ids=tuple(governance.get("evidence_dataset_ids") or ()),
                    evidence_refs=tuple(governance.get("evidence_refs") or ()),
                )
                self._rules[rule.rule_id] = (source_id, rule)
                self._entries[rule.rule_id] = entry

    def source(self, source_id: str = "hydrologist-calibration-priors-v1") -> dict[str, Any]:
        try:
            return dict(self._sources[source_id])
        except KeyError as exc:
            raise KeyError(f"unknown expert prior source: {source_id}") from exc

    def governance_entry(self, rule_id: str) -> KnowledgeEntry:
        try:
            return self._entries[rule_id]
        except KeyError as exc:
            raise KeyError(f"unknown expert prior governance entry: {rule_id}") from exc

    @staticmethod
    def basin_profile(attributes: dict[str, Any] | None) -> BasinHydroProfile:
        raw = dict(attributes or {})

        def maybe_float(name: str) -> float | None:
            value = raw.get(name)
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        zone = raw.get("climate_zone")
        return BasinHydroProfile(
            aridity=maybe_float("aridity"),
            runoff_ratio=maybe_float("runoff_ratio"),
            baseflow_index=maybe_float("baseflow_index"),
            frac_snow=maybe_float("frac_snow"),
            climate_zone=str(zone) if zone not in (None, "") else None,
        )

    @staticmethod
    def _metric(diagnosis: dict[str, Any], *names: str) -> float | None:
        metrics = dict(diagnosis.get("metrics") or {})
        for name in names:
            raw = metrics.get(name)
            if isinstance(raw, (int, float)):
                return float(raw)
        return None

    def advise(
        self,
        diagnosis: dict[str, Any],
        *,
        basin_attributes: dict[str, Any] | None = None,
        source_id: str = "hydrologist-calibration-priors-v1",
        governance_context: KnowledgeQueryContext | None = None,
    ) -> ExpertPriorAdvice:
        source = self.source(source_id)
        source_entries = tuple(
            self._entries[rule_id]
            for rule_id, (candidate_id, _) in self._rules.items()
            if candidate_id == source_id
        )
        eligible_rule_ids: set[str] = set()
        if governance_context is not None:
            bundle = select_knowledge_entries(source_entries, context=governance_context)
            eligible_rule_ids = {entry.knowledge_id for entry in bundle.entries}

        pbias = self._metric(diagnosis, "pbias_percent", "pbias")
        nse = self._metric(diagnosis, "nse")
        profile = self.basin_profile(basin_attributes)
        matches: list[_ExpertPriorRule] = []
        for candidate_id, rule in self._rules.values():
            if candidate_id != source_id or rule.rule_id not in eligible_rule_ids:
                continue
            threshold = float(rule.threshold) if rule.threshold is not None else None
            matched = False
            if rule.signal == "abs_pbias_percent_gte" and pbias is not None and threshold is not None:
                matched = abs(pbias) >= threshold
            elif rule.signal == "nse_lt" and nse is not None and threshold is not None:
                matched = nse < threshold
            elif rule.signal == "basin_attributes_available":
                matched = profile.available
            if matched:
                matches.append(rule)

        matches.sort(key=lambda item: item.priority, reverse=True)
        groups: tuple[str, ...] | None = None
        objective: str | None = None
        notes: list[str] = []
        for rule in matches:
            recommendation = dict(rule.recommendation)
            raw_groups = recommendation.get("parameter_groups")
            if groups is None and isinstance(raw_groups, list):
                groups = tuple(str(item) for item in raw_groups)
            if objective is None and recommendation.get("objective"):
                objective = str(recommendation["objective"])
            message = recommendation.get("message")
            if message:
                notes.append(str(message))

        if profile.available and "expert.basin_attributes_are_priors" in eligible_rule_ids:
            summary = [
                f"{key}={value}"
                for key, value in profile.model_dump().items()
                if value is not None
            ]
            if summary:
                notes.append("流域画像先验: " + ", ".join(summary))

        return ExpertPriorAdvice(
            source_id=source_id,
            status=str(source.get("status") or "seed_prior"),
            authority=str(source.get("authority") or "advisory_only"),
            matched_prior_refs=tuple(
                f"{rule.rule_id}@{self._entries[rule.rule_id].revision}" for rule in matches
            ),
            recommended_param_groups=groups,
            recommended_objective=objective,
            notes=tuple(notes),
        )
