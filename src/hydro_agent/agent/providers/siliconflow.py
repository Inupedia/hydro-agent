from __future__ import annotations

import json
import re
from collections.abc import Callable

from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    ProblemHypothesis,
    WorldStateView,
)
from hydro_agent.llm.client import SiliconFlowClient
from hydro_agent.llm.settings import LLMSettings
from hydro_agent.skills import SkillRegistry

_HYPOTHESES = tuple(h.value for h in ProblemHypothesis)
_ACTIONS = tuple(a.value for a in ActionCode)
_CALIBRATION_OBJECTIVES = {
    "nse",
    "peak",
    "composite",
    "water_balance",
    "recession",
    "routing_event",
    "joint",
}
_XAJ_PARAMETERS = {
    "K",
    "UM",
    "LM",
    "DM",
    "C",
    "B",
    "IM",
    "SM",
    "EX",
    "KI",
    "KG",
    "CS",
    "CI",
    "CG",
    "L",
}
_DIRECTIONS = {"increase", "decrease", "hold"}

SYSTEM_INSTRUCTIONS = f"""You are the Hydro-Agent scientific decision module.
Choose exactly one ActionCode from permissions.safe_actions.
Never invent continuous parameter vectors or call model processes directly.
Use the activated hydrologic Agent Skills as the scientific method. The current
hydro.calibration_phase tells you which hydrologic problem is being solved.
Do not optimize NSE globally when a phase-specific signature is the current target.
Do not choose xaj-hydrologist-manual-v1 in the automatic loop.

The runtime owns protocol mechanics such as optimize -> Gate -> resolve and phase
transitions. You own the scientific choice after diagnosis: hypothesis, smallest
parameter group, numerical strategy, objective, and parameter guidance that match
the current phase. hydro.available_tunable_parameters is a HARD phase whitelist.
Never request or guide a parameter outside that list. If evidence says a parameter
should go down/up/stay fixed, encode that in parameter_guidance instead of only
mentioning it in rationale_summary. Prefer direction/hold constraints; use explicit
numeric bounds only when evidence provides a defensible bound. If evidence points to
DATA/FORCING/STRUCTURAL limitations, do not hide them by parameter compensation.

Return ONLY one JSON object with keys:
- action: ActionCode string
- hypothesis: one of {_HYPOTHESES}
- strategy_id: null, unless action is A07_OPTIMIZE then one of hydro.available_strategies
- param_groups: null, unless A07_OPTIMIZE then a JSON array subset of hydro.available_param_groups
- objective: null, unless A07_OPTIMIZE then one of hydro.available_objectives
- parameter_guidance: null unless A07_OPTIMIZE; otherwise optionally an object with:
  - directions: map of allowed parameter name -> increase | decrease | hold
  - bounds: map of allowed parameter name -> {{"min_value": number|null, "max_value": number|null}}
  - frozen_parameters: array of allowed parameter names
- rationale_summary: short Chinese or English reason (<= 600 chars)

Example:
{{"action":"A07_OPTIMIZE","hypothesis":"MODEL","strategy_id":"xaj-local-refine-v1","param_groups":["evap","runoff"],"objective":"water_balance","parameter_guidance":{{"directions":{{"K":"decrease","B":"increase"}},"bounds":{{}},"frozen_parameters":["DM"]}},"rationale_summary":"P2 总水量已接近阈值，按诊断约束 K 下调并冻结 DM，避免优化器反向补偿。"}}

No markdown fences. No extra keys. No prose outside JSON.
"""
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_HYPOTHESIS_HINTS = (
    (ProblemHypothesis.DATA, ("data", "observation", "资料", "观测")),
    (ProblemHypothesis.TIMING, ("timing", "lag", "时滞", "时间")),
    (ProblemHypothesis.STATE, ("state", "初始", "状态")),
    (ProblemHypothesis.FORCING, ("forcing", "rainfall", "降水", "强迫", "snow", "融雪")),
    (ProblemHypothesis.MODEL, ("model", "parameter", "xaj", "参数", "模型")),
    (ProblemHypothesis.RESOURCE, ("resource", "timeout", "memory", "资源")),
)


class SiliconFlowDecisionProvider:
    """Live SiliconFlow decision provider; scientific control comes from activated skills."""

    def __init__(
        self,
        *,
        client: SiliconFlowClient | None = None,
        settings: LLMSettings | None = None,
        skills: SkillRegistry | None = None,
    ):
        self.settings = settings or LLMSettings.from_env()
        self.client = client or SiliconFlowClient(self.settings)
        self.skills = skills or SkillRegistry()

    @property
    def model(self) -> str:
        return self.settings.model

    def decide(
        self,
        view: WorldStateView,
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> AgentDecision:
        skill_block = self.skills.render_activated(view)
        system = SYSTEM_INSTRUCTIONS + "\n\n# Activated Agent Skills\n\n" + skill_block
        completion = self.client.complete_stream(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        "WorldStateView JSON follows. Pick exactly one legal next action.\n"
                        "hypothesis must be one enum token like MODEL, never a sentence.\n"
                        "action MUST be one of permissions.safe_actions.\n"
                        "Keep rationale_summary concise so JSON stays complete.\n"
                        + view.model_dump_json()
                    ),
                },
            ],
            max_tokens=1200,
            on_delta=on_delta,
        )
        safe = {a.value for a in view.permissions.safe_actions}
        evidence_actions = tuple(item.action.value for item in view.evidence_summary)
        try:
            payload = _extract_json(completion.content)
        except ValueError:
            payload = _fallback_payload(view, raw_text=completion.content)
        payload = normalize_decision_payload(
            payload,
            safe_actions=safe,
            evidence_actions=evidence_actions,
            allowed_parameters=set(view.hydro.available_tunable_parameters),
        )
        return AgentDecision.model_validate(payload)


def _extract_json(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    candidates = [raw]
    match = _JSON_RE.search(text)
    if match:
        candidates.append(match.group(0))
    start = text.find("{")
    if start >= 0:
        fragment = text[start:].strip()
        candidates.append(fragment)
        for suffix in ('"}', '"}}', "}", "}}", '"} }'):
            candidates.append(fragment + suffix)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            repaired = _repair_truncated_json(candidate)
            if repaired is None:
                continue
            try:
                value = json.loads(repaired)
            except json.JSONDecodeError:
                continue
        if isinstance(value, dict):
            return value
    raise ValueError("SiliconFlow response did not contain JSON AgentDecision")


def _repair_truncated_json(text: str) -> str | None:
    if "{" not in text:
        return None
    fragment = text[text.find("{") :]
    quote_count = fragment.count('"') - fragment.count('\\"')
    if quote_count % 2 == 1:
        fragment += '"'
    opens = fragment.count("{") - fragment.count("}")
    if opens > 0:
        fragment += "}" * opens
    return fragment


def _default_objective(view: WorldStateView) -> str:
    available = tuple(view.hydro.available_objectives or ())
    return available[0] if available else "nse"


def _fallback_payload(view: WorldStateView, *, raw_text: str) -> dict:
    """Minimal format recovery; protocol ordering belongs to the workbench controller."""
    safe = {a.value for a in view.permissions.safe_actions}
    preferred = None
    for code in _ACTIONS:
        if code in raw_text and code in safe:
            preferred = code
            break
    if preferred is None:
        preferred_order = (
            ActionCode.A06_DIAGNOSE.value,
            ActionCode.A07_OPTIMIZE.value,
            ActionCode.A05_FORECAST.value,
            ActionCode.A03_VALIDATE_SCHEME.value,
            ActionCode.A08_GATE.value,
            ActionCode.A09_RESOLVE.value,
            ActionCode.A10_FREEZE.value,
            ActionCode.A11_REPLAY.value,
            ActionCode.A12_EVALUATE_REPORT.value,
            ActionCode.A01_CHECK_DATA.value,
        )
        preferred = next((code for code in preferred_order if code in safe), None)
    if preferred is None:
        preferred = next(iter(sorted(safe)), ActionCode.A01_CHECK_DATA.value)
    optimize = preferred == ActionCode.A07_OPTIMIZE.value
    return {
        "action": preferred,
        "hypothesis": ProblemHypothesis.UNKNOWN.value,
        "strategy_id": "xaj-bounded-v1" if optimize else None,
        "param_groups": list(view.hydro.available_param_groups) if optimize else None,
        "objective": _default_objective(view) if optimize else None,
        "parameter_guidance": None,
        "rationale_summary": "模型输出格式不完整，按当前安全动作做最小恢复。",
    }


def _normalize_guidance(raw, *, allowed_parameters: set[str] | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    allowed = set(allowed_parameters or _XAJ_PARAMETERS) & _XAJ_PARAMETERS
    directions: dict[str, str] = {}
    raw_directions = raw.get("directions")
    if isinstance(raw_directions, dict):
        for key, value in raw_directions.items():
            name = str(key).strip().upper()
            direction = str(value).strip().lower()
            if name in allowed and direction in _DIRECTIONS:
                directions[name] = direction

    bounds: dict[str, dict[str, float | None]] = {}
    raw_bounds = raw.get("bounds")
    if isinstance(raw_bounds, dict):
        for key, value in raw_bounds.items():
            name = str(key).strip().upper()
            if name not in allowed or not isinstance(value, dict):
                continue
            normalized: dict[str, float | None] = {"min_value": None, "max_value": None}
            valid = False
            for bound_key in ("min_value", "max_value"):
                bound_value = value.get(bound_key)
                if bound_value is None:
                    continue
                try:
                    normalized[bound_key] = float(bound_value)
                    valid = True
                except (TypeError, ValueError):
                    pass
            if valid:
                lo = normalized["min_value"]
                hi = normalized["max_value"]
                if lo is None or hi is None or lo <= hi:
                    bounds[name] = normalized

    frozen: list[str] = []
    raw_frozen = raw.get("frozen_parameters")
    if isinstance(raw_frozen, (list, tuple)):
        for item in raw_frozen:
            name = str(item).strip().upper()
            if name in allowed and name not in frozen:
                frozen.append(name)

    if not directions and not bounds and not frozen:
        return None
    return {
        "directions": directions,
        "bounds": bounds,
        "frozen_parameters": frozen,
    }


def normalize_decision_payload(
    payload: dict,
    *,
    safe_actions: set[str] | None = None,
    evidence_actions: tuple[str, ...] = (),
    allowed_parameters: set[str] | None = None,
) -> dict:
    """Coerce common LLM formatting mistakes without imposing scientific policy."""
    del evidence_actions
    data = dict(payload)
    action = str(data.get("action") or "").strip()
    if action not in _ACTIONS:
        for code in _ACTIONS:
            if action.endswith(code) or code.endswith(action):
                action = code
                break
    if safe_actions and action not in safe_actions:
        preferred = (
            ActionCode.A06_DIAGNOSE.value,
            ActionCode.A07_OPTIMIZE.value,
            ActionCode.A05_FORECAST.value,
            ActionCode.A03_VALIDATE_SCHEME.value,
            ActionCode.A08_GATE.value,
            ActionCode.A09_RESOLVE.value,
            ActionCode.A10_FREEZE.value,
            ActionCode.A11_REPLAY.value,
            ActionCode.A12_EVALUATE_REPORT.value,
            ActionCode.A01_CHECK_DATA.value,
        )
        action = next((a for a in preferred if a in safe_actions), sorted(safe_actions)[0])
    data["action"] = action

    hypothesis_raw = data.get("hypothesis")
    hypothesis = str(hypothesis_raw).strip() if hypothesis_raw is not None else ""
    rationale = str(data.get("rationale_summary") or "").strip()
    if hypothesis not in _HYPOTHESES:
        if hypothesis and (not rationale or len(hypothesis) > len(rationale)):
            rationale = hypothesis if not rationale else f"{rationale} ({hypothesis})"
        lowered = hypothesis.lower()
        mapped = ProblemHypothesis.UNKNOWN
        for candidate, hints in _HYPOTHESIS_HINTS:
            if any(h in lowered for h in hints):
                mapped = candidate
                break
        hypothesis = mapped.value
    if not rationale:
        rationale = f"Proceed with {action}."
    if len(rationale) > 600:
        rationale = rationale[:597] + "..."

    strategy_id = data.get("strategy_id")
    if strategy_id in ("", "null", "None"):
        strategy_id = None
    if action == ActionCode.A07_OPTIMIZE.value and not strategy_id:
        strategy_id = "xaj-bounded-v1"
    if action == ActionCode.A07_OPTIMIZE.value and strategy_id == "xaj-hydrologist-manual-v1":
        strategy_id = "xaj-bounded-v1"
    if action != ActionCode.A07_OPTIMIZE.value:
        strategy_id = None

    param_groups = data.get("param_groups")
    objective = data.get("objective")
    guidance = data.get("parameter_guidance")
    if action != ActionCode.A07_OPTIMIZE.value:
        param_groups = None
        objective = None
        guidance = None
    else:
        if isinstance(param_groups, str):
            param_groups = [p.strip() for p in param_groups.split(",") if p.strip()]
        if param_groups in ("", "null", "None", None):
            param_groups = None
        if isinstance(param_groups, list):
            cleaned = []
            for item in param_groups:
                key = str(item).strip().lower()
                if key in {"evap", "runoff", "routing"} and key not in cleaned:
                    cleaned.append(key)
            param_groups = cleaned or None
        if objective in ("", "null", "None", None):
            objective = None
        elif str(objective) not in _CALIBRATION_OBJECTIVES:
            objective = "nse"
        if not param_groups:
            param_groups = ["evap", "runoff", "routing"]
        if not objective:
            objective = "nse"
        guidance = _normalize_guidance(guidance, allowed_parameters=allowed_parameters)

    data["hypothesis"] = hypothesis
    data["rationale_summary"] = rationale
    data["strategy_id"] = strategy_id
    data["param_groups"] = param_groups
    data["objective"] = objective
    data["parameter_guidance"] = guidance
    return data
