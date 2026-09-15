from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STANDARD_ID = "GB/T 22482-2026"
DEFAULT_POLICY_ID = "hydro-agent-research-v1"
DEFAULT_PROFILE_ID = "flood_forecast_discharge"
DEFAULT_GRADE_DC_BING = 0.5


class StandardRepository:
    """Read-only repository for normative standards and project Gate policy."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else Path(__file__).with_name("data")
        self._standards: dict[str, dict[str, Any]] = {}
        self._policies: dict[str, dict[str, Any]] = {}
        self._rules: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        for path in sorted((self.root / "standards").glob("*.json")):
            payload = self._read_json(path)
            standard_id = str(payload.get("standard_id") or "").strip()
            if not standard_id:
                raise ValueError(f"standard missing standard_id: {path}")
            if standard_id in self._standards:
                raise ValueError(f"duplicate standard: {standard_id}")
            self._standards[standard_id] = payload
            for rule in payload.get("rules") or []:
                rule_id = str(rule.get("rule_id") or "").strip()
                if not rule_id:
                    raise ValueError(f"standard rule missing rule_id: {path}")
                if rule_id in self._rules:
                    raise ValueError(f"duplicate standard rule: {rule_id}")
                self._rules[rule_id] = {**rule, "standard_id": standard_id}

        for path in sorted((self.root / "policies").glob("*.json")):
            payload = self._read_json(path)
            policy_id = str(payload.get("policy_id") or "").strip()
            if not policy_id:
                raise ValueError(f"Gate policy missing policy_id: {path}")
            if policy_id in self._policies:
                raise ValueError(f"duplicate Gate policy: {policy_id}")
            self._policies[policy_id] = payload

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"standard/policy file must contain an object: {path}")
        return payload

    def standard(self, standard_id: str = DEFAULT_STANDARD_ID) -> dict[str, Any]:
        try:
            return dict(self._standards[standard_id])
        except KeyError as exc:
            raise KeyError(f"unknown standard: {standard_id}") from exc

    def policy(self, policy_id: str = DEFAULT_POLICY_ID) -> dict[str, Any]:
        try:
            return dict(self._policies[policy_id])
        except KeyError as exc:
            raise KeyError(f"unknown Gate policy: {policy_id}") from exc

    def rule(self, rule_id: str) -> dict[str, Any]:
        try:
            return dict(self._rules[rule_id])
        except KeyError as exc:
            raise KeyError(f"unknown standard rule: {rule_id}") from exc

    def gbt_accuracy_metadata(
        self,
        *,
        area_km2: float | None = None,
        standard_id: str = DEFAULT_STANDARD_ID,
        policy_id: str = DEFAULT_POLICY_ID,
        profile_id: str = DEFAULT_PROFILE_ID,
    ) -> dict[str, str]:
        standard = self.standard(standard_id)
        profile = (standard.get("profiles") or {}).get(profile_id)
        if not isinstance(profile, dict):
            raise KeyError(f"unknown standard profile: {standard_id}/{profile_id}")
        config = profile.get("config") or {}
        if not isinstance(config, dict):
            raise ValueError(f"invalid standard profile config: {standard_id}/{profile_id}")
        gate = self.gate_defaults(policy_id)
        meta = {key: str(value) for key, value in config.items() if value is not None}
        meta["min_scheme_grade"] = str(gate.get("min_scheme_grade") or "丙")
        if area_km2 is not None:
            meta["area_km2"] = str(area_km2)
        return meta

    def gate_defaults(self, policy_id: str = DEFAULT_POLICY_ID) -> dict[str, Any]:
        gate = self.policy(policy_id).get("gate") or {}
        if not isinstance(gate, dict):
            raise ValueError(f"invalid Gate policy: {policy_id}")
        return dict(gate)

    def grade_dc_bing(self, *, area_km2: float | None = None) -> float:
        """Normative GB/T DC 丙 floor from Standards, never from editable Skills."""

        meta = self.gbt_accuracy_metadata(area_km2=area_km2)
        return float(meta.get("grade_dc_bing", DEFAULT_GRADE_DC_BING))

    def min_scheme_grade(self, policy_id: str = DEFAULT_POLICY_ID) -> str:
        grade = str(self.gate_defaults(policy_id).get("min_scheme_grade") or "丙").strip()
        if grade not in {"甲", "乙", "丙"}:
            raise ValueError(f"invalid standard policy min_scheme_grade: {grade}")
        return grade

    def gbt_accuracy_config(self, *, area_km2: float | None = None):
        from hydro_agent.evaluation.gbt22482 import GbtAccuracyConfig

        meta = self.gbt_accuracy_metadata(area_km2=area_km2)
        return GbtAccuracyConfig.from_metadata(meta, area_km2=area_km2)

    def provenance(
        self,
        *,
        standard_id: str = DEFAULT_STANDARD_ID,
        policy_id: str = DEFAULT_POLICY_ID,
        profile_id: str = DEFAULT_PROFILE_ID,
    ) -> dict[str, Any]:
        standard = self.standard(standard_id)
        policy = self.policy(policy_id)
        profile = (standard.get("profiles") or {}).get(profile_id) or {}
        return {
            "standard_id": standard_id,
            "standard_record_id": standard.get("knowledge_id"),
            "published_on": standard.get("published_on"),
            "effective_from": standard.get("effective_from"),
            "standard_status": standard.get("status"),
            "profile_id": profile_id,
            "clause_refs": list(profile.get("clause_refs") or []),
            "policy_id": policy_id,
            "policy_standard_ref": policy.get("standard_ref"),
        }
