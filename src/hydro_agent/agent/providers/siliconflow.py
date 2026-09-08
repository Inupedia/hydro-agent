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

_HYPOTHESES = tuple(h.value for h in ProblemHypothesis)
_ACTIONS = tuple(a.value for a in ActionCode)

SYSTEM_INSTRUCTIONS = f"""You are the Hydro-Agent decision module for a hydrologist-style research loop.
Choose exactly one ActionCode from permissions.safe_actions.
Never invent continuous parameter vectors or call model processes directly.

You MUST use hydro context and skill cards:
- Read hydro.diagnosis / evidence_summary.observations / metrics / gates
- Use available_skills and available_strategies
- Prefer A06_DIAGNOSE after a forecast before blind re-optimization
- After diagnose, follow recommended_action/strategy when still safe
- After A09_RESOLVE with KEEP/ROLLBACK and remaining optimization budget, you MAY A06 or A07 again instead of freezing
- Only A10_FREEZE when evidence supports stopping (small bias / Gate KEEP after enough experiments / budget low)

Preferred B-phase research loop:
A01/A03 -> A05_FORECAST -> A06_DIAGNOSE -> A07_OPTIMIZE(strategy_id) -> A08_GATE -> A09_RESOLVE
then either continue diagnose/optimize OR A10_FREEZE -> (F) A11_REPLAY -> (E) A12_EVALUATE_REPORT

Return ONLY one JSON object with exactly these keys:
- action: one ActionCode string, e.g. "A06_DIAGNOSE"
- hypothesis: MUST be exactly one of {_HYPOTHESES} (a short enum token, NEVER a sentence)
- strategy_id: null, unless action is A07_OPTIMIZE then one of hydro.available_strategies
- rationale_summary: Chinese preferred; state 发现/依据/为何这样调/预期验证 (1-3 short sentences)

Example:
{{"action":"A06_DIAGNOSE","hypothesis":"MODEL","strategy_id":null,"rationale_summary":"已有预报，先诊断洪峰与偏差再决定是否优化。"}}

No markdown fences. No extra keys. No prose outside JSON.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_HYPOTHESIS_HINTS = (
    (ProblemHypothesis.DATA, ("data", "observation", "资料", "观测")),
    (ProblemHypothesis.TIMING, ("timing", "lag", "时滞", "时间")),
    (ProblemHypothesis.STATE, ("state", "初始", "状态")),
    (ProblemHypothesis.FORCING, ("forcing", "rainfall", "降水", "强迫")),
    (ProblemHypothesis.MODEL, ("model", "parameter", "xaj", "参数", "模型")),
    (ProblemHypothesis.RESOURCE, ("resource", "timeout", "memory", "资源")),
)


class SiliconFlowDecisionProvider:
    """Live decision provider over SiliconFlow OpenAI-compatible chat API."""

    def __init__(self, *, client: SiliconFlowClient | None = None, settings: LLMSettings | None = None):
        self.settings = settings or LLMSettings.from_env()
        self.client = client or SiliconFlowClient(self.settings)

    @property
    def model(self) -> str:
        return self.settings.model

    def decide(
        self,
        view: WorldStateView,
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> AgentDecision:
        completion = self.client.complete_stream(
            [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": (
                        "WorldStateView JSON follows. Pick exactly one legal next action.\n"
                        "Remember: hypothesis must be one enum token like MODEL, never a sentence.\n"
                        "action MUST be one of permissions.safe_actions.\n"
                        + view.model_dump_json()
                    ),
                },
            ],
            max_tokens=800,
            on_delta=on_delta,
        )
        safe = {a.value for a in view.permissions.safe_actions}
        payload = normalize_decision_payload(
            _extract_json(completion.content),
            safe_actions=safe,
            evidence_actions=tuple(item.action.value for item in view.evidence_summary),
        )
        return AgentDecision.model_validate(payload)


def _extract_json(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if not match:
            raise ValueError("SiliconFlow response did not contain JSON AgentDecision") from None
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("AgentDecision JSON must be an object")
    return value


def normalize_decision_payload(
    payload: dict,
    *,
    safe_actions: set[str] | None = None,
    evidence_actions: tuple[str, ...] = (),
) -> dict:
    """Coerce common LLM mistakes into a valid AgentDecision dict."""
    data = dict(payload)
    action = str(data.get("action") or "").strip()
    if action not in _ACTIONS:
        # Sometimes models return bare names like FORECAST.
        for code in _ACTIONS:
            if action.endswith(code) or code.endswith(action):
                action = code
                break
    if safe_actions and action not in safe_actions:
        # Prefer forward progress when the model invents a disallowed action.
        preferred = (
            ActionCode.A06_DIAGNOSE.value,
            ActionCode.A05_FORECAST.value,
            ActionCode.A03_VALIDATE_SCHEME.value,
            ActionCode.A07_OPTIMIZE.value,
            ActionCode.A08_GATE.value,
            ActionCode.A09_RESOLVE.value,
            ActionCode.A10_FREEZE.value,
            ActionCode.A11_REPLAY.value,
            ActionCode.A12_EVALUATE_REPORT.value,
            ActionCode.A01_CHECK_DATA.value,
        )
        action = next((a for a in preferred if a in safe_actions), sorted(safe_actions)[0])

    # Soft format nudges only — do NOT force freeze after resolve (multi-round experiments allowed).
    actions = set(evidence_actions)
    if (
        ActionCode.A07_OPTIMIZE.value in actions
        and ActionCode.A08_GATE.value not in actions
        and action == ActionCode.A05_FORECAST.value
        and (not safe_actions or ActionCode.A08_GATE.value in safe_actions)
    ):
        action = ActionCode.A08_GATE.value
    if (
        ActionCode.A08_GATE.value in actions
        and ActionCode.A09_RESOLVE.value not in actions
        and action == ActionCode.A05_FORECAST.value
        and (not safe_actions or ActionCode.A09_RESOLVE.value in safe_actions)
    ):
        action = ActionCode.A09_RESOLVE.value
    data["action"] = action

    hypothesis_raw = data.get("hypothesis")
    hypothesis = str(hypothesis_raw).strip() if hypothesis_raw is not None else ""
    rationale = str(data.get("rationale_summary") or "").strip()

    if hypothesis not in _HYPOTHESES:
        # Model put a sentence into hypothesis — move it to rationale if needed.
        if hypothesis and (not rationale or len(hypothesis) > len(rationale)):
            rationale = hypothesis if not rationale else f"{rationale} ({hypothesis})"
        lowered = hypothesis.lower()
        mapped = ProblemHypothesis.UNKNOWN
        for candidate, hints in _HYPOTHESIS_HINTS:
            if any(h in lowered for h in hints):
                mapped = candidate
                break
        # Prefer MODEL for forecast/optimize/gate style work when unclear.
        if mapped == ProblemHypothesis.UNKNOWN and action in {
            ActionCode.A05_FORECAST.value,
            ActionCode.A07_OPTIMIZE.value,
            ActionCode.A08_GATE.value,
            ActionCode.A03_VALIDATE_SCHEME.value,
        }:
            mapped = ProblemHypothesis.MODEL
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
    if action != ActionCode.A07_OPTIMIZE.value:
        strategy_id = None

    data["hypothesis"] = hypothesis
    data["rationale_summary"] = rationale
    data["strategy_id"] = strategy_id
    return data
