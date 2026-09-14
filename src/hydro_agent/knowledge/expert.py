"""Provenance-aware expert priors for calibration-scientist decisions.

External skills and published heuristics are treated as *seed priors*, not as
normative rules and not as validated local experience. Legacy executable priors
are converted into the same claim-level governance contract used by newly
atomized expert material before they can influence a CalibrationPlan.
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


class ExpertRule(FrozenModel):
    rule_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    signal: str = Field(min_length=1)
    threshold: float | int | None = None
    priority: int = 0
    recommendation: dict[str, Any] = Field(default_factory=dict)


class ExpertAdvice(FrozenModel):
    knowledge_id: str
    status: str
    authority: str
    matched_rule_ids: tuple[str, ...] = ()
    recommended_param_groups: tuple[str, ...] | None = None
    recommended_objective: str | None = None
    search_adjustment: str | None = None
    prefer_recheck: bool = False
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


class ExpertKnowledgeRepository:
    """Read-only advisory knowledge store behind the common governance filter.

    A legacy rule is an executable advisory payload, not an authority shortcut.
    Each rule is wrapped as an atomic ``KnowledgeEntry`` and must pass the same
    review, verification, applicability, exposure and dataset-provenance checks
    as any newer governed claim before its threshold is even evaluated.
    """

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else Path(__file__).with_name("data") / "expert"
        self._sources: dict[str, dict[str, Any]] = {}
        self._rules: dict[str, tuple[str, ExpertRule]] = {}
        self._entries: dict[str, KnowledgeEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.json")):
            source_bytes = path.read_bytes()
            payload = json.loads(source_bytes.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"expert knowledge file must contain an object: {path}")
            knowledge_id = str(payload.get("knowledge_id") or "").strip()
            if not knowledge_id:
                raise ValueError(f"expert knowledge missing knowledge_id: {path}")
            if knowledge_id in self._sources:
                raise ValueError(f"duplicate expert knowledge source: {knowledge_id}")
            self._sources[knowledge_id] = payload

            governance = dict(payload.get("governance") or {})
            applicability = KnowledgeApplicability.model_validate(
                governance.get("applicability") or {}
            )
            source_hash = f"sha256:{hashlib.sha256(source_bytes).hexdigest()}"
            for raw in payload.get("rules") or []:
                rule = ExpertRule.model_validate(raw)
                if rule.rule_id in self._rules:
                    raise ValueError(f"duplicate expert rule: {rule.rule_id}")
                recommendation = dict(rule.recommendation)
                claim = str(
                    recommendation.get("message")
                    or f"{rule.signal} -> {json.dumps(recommendation, ensure_ascii=False)}"
                )
                entry = KnowledgeEntry.model_validate(
                    {
                        "knowledge_id": rule.rule_id,
                        "revision": int(governance.get("revision") or 1),
                        "category": governance.get("category")
                        or "expert_diagnostic_prior",
                        "authority": payload.get("authority") or "advisory_only",
                        "claim": claim,
                        "source_id": knowledge_id,
                        "source_hash": source_hash,
                        "source_locator": f"{path.name}#rule={rule.rule_id}",
                        "applicability": applicability.model_dump(),
                        "verification_status": governance.get("verification_status")
                        or "unverified",
                        "review_status": governance.get("review_status") or "pending",
                        "exposure_tags": governance.get("exposure_tags") or (),
                        "evidence_dataset_ids": governance.get("evidence_dataset_ids") or (),
                        "evidence_refs": governance.get("evidence_refs") or (),
                    }
                )
                self._rules[rule.rule_id] = (knowledge_id, rule)
                self._entries[rule.rule_id] = entry

    def source(self, knowledge_id: str = "hydrologist-calibration-priors-v1") -> dict[str, Any]:
        try:
            return dict(self._sources[knowledge_id])
        except KeyError as exc:
            raise KeyError(f"unknown expert knowledge source: {knowledge_id}") from exc

    def rule(self, rule_id: str) -> ExpertRule:
        try:
            return self._rules[rule_id][1]
        except KeyError as exc:
            raise KeyError(f"unknown expert rule: {rule_id}") from exc

    def governance_entry(self, rule_id: str) -> KnowledgeEntry:
        try:
            return self._entries[rule_id]
        except KeyError as exc:
            raise KeyError(f"unknown expert rule governance entry: {rule_id}") from exc

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

    @staticmethod
    def _name_list(diagnosis: dict[str, Any], key: str) -> tuple[str, ...]:
        raw = diagnosis.get(key)
        if isinstance(raw, str):
            return tuple(item.strip() for item in raw.split(",") if item.strip())
        if isinstance(raw, (list, tuple)):
            return tuple(str(item).strip() for item in raw if str(item).strip())
        return ()

    def advise(
        self,
        diagnosis: dict[str, Any],
        *,
        basin_attributes: dict[str, Any] | None = None,
        validation_degraded: bool = False,
        no_improvement_rounds: int = 0,
        knowledge_id: str = "hydrologist-calibration-priors-v1",
        governance_context: KnowledgeQueryContext | None = None,
    ) -> ExpertAdvice:
        source = self.source(knowledge_id)
        source_entries = tuple(
            self._entries[rule_id]
            for rule_id, (candidate_id, _) in self._rules.items()
            if candidate_id == knowledge_id
        )
        eligible_rule_ids: set[str] = set()
        if governance_context is not None:
            bundle = select_knowledge_entries(source_entries, context=governance_context)
            eligible_rule_ids = {entry.knowledge_id for entry in bundle.entries}

        matches: list[ExpertRule] = []
        pbias = self._metric(diagnosis, "pbias_percent", "pbias")
        nse = self._metric(diagnosis, "nse")
        profile = self.basin_profile(basin_attributes)
        local_boundary_hits = self._name_list(diagnosis, "local_boundary_hits")
        absolute_boundary_hits = self._name_list(diagnosis, "absolute_boundary_hits")
        any_boundary_hits = bool(local_boundary_hits or absolute_boundary_hits)

        for candidate_id, rule in self._rules.values():
            if candidate_id != knowledge_id or rule.rule_id not in eligible_rule_ids:
                continue
            matched = False
            threshold = float(rule.threshold) if rule.threshold is not None else None
            if rule.signal == "abs_pbias_percent_gte" and pbias is not None and threshold is not None:
                matched = abs(pbias) >= threshold
            elif rule.signal == "nse_lt" and nse is not None and threshold is not None:
                matched = nse < threshold
            elif rule.signal == "boundary_hit":
                matched = any_boundary_hits
            elif rule.signal == "local_boundary_hit":
                matched = bool(local_boundary_hits) and not absolute_boundary_hits
            elif rule.signal == "absolute_boundary_hit":
                matched = bool(absolute_boundary_hits)
            elif rule.signal == "validation_degraded":
                matched = validation_degraded
            elif rule.signal == "no_improvement_rounds_gte" and threshold is not None:
                matched = no_improvement_rounds >= int(threshold)
            elif rule.signal == "basin_attributes_available":
                matched = profile.available
            if matched:
                matches.append(rule)

        matches.sort(key=lambda item: item.priority, reverse=True)
        groups: tuple[str, ...] | None = None
        objective: str | None = None
        search_adjustment: str | None = None
        prefer_recheck = False
        notes: list[str] = []
        for rule in matches:
            recommendation = dict(rule.recommendation)
            raw_groups = recommendation.get("parameter_groups")
            if groups is None and isinstance(raw_groups, list):
                groups = tuple(str(item) for item in raw_groups)
            if objective is None and recommendation.get("objective"):
                objective = str(recommendation["objective"])
            if search_adjustment is None and recommendation.get("search_adjustment"):
                search_adjustment = str(recommendation["search_adjustment"])
            prefer_recheck = prefer_recheck or bool(recommendation.get("prefer_recheck"))
            message = recommendation.get("message")
            if message:
                notes.append(str(message))

        if profile.available and "expert.basin_attributes_are_priors" in eligible_rule_ids:
            summary = []
            for key, value in profile.model_dump().items():
                if value is not None:
                    summary.append(f"{key}={value}")
            if summary:
                notes.append("流域画像先验: " + ", ".join(summary))
        if local_boundary_hits and matches:
            notes.append("局部搜索边界触碰: " + ", ".join(local_boundary_hits))
        if absolute_boundary_hits and matches:
            notes.append("绝对参数边界触碰: " + ", ".join(absolute_boundary_hits))

        return ExpertAdvice(
            knowledge_id=knowledge_id,
            status=str(source.get("status") or "seed_prior"),
            authority=str(source.get("authority") or "advisory_only"),
            matched_rule_ids=tuple(rule.rule_id for rule in matches),
            recommended_param_groups=groups,
            recommended_objective=objective,
            search_adjustment=search_adjustment,
            prefer_recheck=prefer_recheck,
            notes=tuple(notes),
        )
