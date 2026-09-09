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
from hydro_agent.agent.permissions import CLOSEOUT_RESERVE_ROUNDS
from hydro_agent.llm.client import SiliconFlowClient
from hydro_agent.llm.settings import LLMSettings
from hydro_agent.skills import DEFAULT_NSE_GOOD_ENOUGH, SkillRegistry

_HYPOTHESES = tuple(h.value for h in ProblemHypothesis)
_ACTIONS = tuple(a.value for a in ActionCode)

SYSTEM_INSTRUCTIONS = f"""You are the Hydro-Agent decision module for a hydrologist-style research loop.
Choose exactly one ActionCode from permissions.safe_actions.
Never invent continuous parameter vectors or call model processes directly.
Follow activated Agent Skills below for calibration/diagnosis methods and thresholds
(especially nse_good_enough from xaj-calibration). Do NOT invent continuous XAJ parameters.
Do NOT choose xaj-hydrologist-manual-v1 in the automatic loop.

Preferred B-phase path:
A01/A03 -> A05_FORECAST -> A06_DIAGNOSE -> (calibrate if NSE below skill threshold) ->
A07_OPTIMIZE -> A08_GATE -> A09_RESOLVE -> A10_FREEZE then (F) A11_REPLAY -> (E) A12_EVALUATE_REPORT

Return ONLY one JSON object with keys:
- action: ActionCode string
- hypothesis: one of {_HYPOTHESES}
- strategy_id: null, unless action is A07_OPTIMIZE then one of hydro.available_strategies
- param_groups: null, unless A07_OPTIMIZE then a JSON array subset of hydro.available_param_groups (e.g. ["runoff","routing"])
- objective: null, unless A07_OPTIMIZE then one of hydro.available_objectives ("nse"|"peak"|"composite")
- rationale_summary: short Chinese or English reason (<= 600 chars)

Example:
{{"action":"A07_OPTIMIZE","hypothesis":"MODEL","strategy_id":"xaj-peak-bias-v1","param_groups":["runoff","routing"],"objective":"composite","rationale_summary":"洪峰低估，先动产汇流参数并用综合目标验证。"}}

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
                        "Remember: hypothesis must be one enum token like MODEL, never a sentence.\n"
                        "action MUST be one of permissions.safe_actions.\n"
                        "Keep rationale_summary under 120 Chinese characters so JSON stays complete.\n"
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
            try_payload = _extract_json(completion.content)
        except ValueError:
            try_payload = _fallback_payload(view, raw_text=completion.content)
        payload = normalize_decision_payload(
            try_payload,
            safe_actions=safe,
            evidence_actions=evidence_actions,
        )
        payload = _nse_calibration_progress(
            view,
            payload,
            safe_actions=safe,
            nse_good_enough=self.skills.nse_good_enough(),
        )
        return AgentDecision.model_validate(payload)


_BOUNDED_STRATEGIES = ("xaj-bounded-v1", "xaj-peak-bias-v1", "xaj-local-refine-v1")

def _diagnosis_nse(view: WorldStateView) -> float | None:
    diagnosis = dict(view.hydro.diagnosis or {})
    metrics = diagnosis.get("metrics") if isinstance(diagnosis.get("metrics"), dict) else {}
    raw = metrics.get("nse")
    if raw is None:
        raw = diagnosis.get("nse")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return value


def _latest_status(view: WorldStateView, action: str) -> str | None:
    for item in reversed(view.evidence_summary):
        if item.action.value == action:
            return item.status
    return None


def _rotate_strategy(view: WorldStateView, preferred: str | None) -> str:
    used = [
        item.gates.get("strategy_id") or ""
        for item in view.evidence_summary
        if item.action == ActionCode.A07_OPTIMIZE
    ]
    preferred = preferred or "xaj-bounded-v1"
    if preferred == "xaj-hydrologist-manual-v1":
        preferred = "xaj-bounded-v1"
    order = [preferred, *[s for s in _BOUNDED_STRATEGIES if s != preferred]]
    for strategy in order:
        if strategy not in used:
            return strategy
    return order[min(len(used), len(order) - 1)]


def _optimize_payload(view: WorldStateView, *, rationale: str) -> dict:
    diagnosis = dict(view.hydro.diagnosis or {})
    strategy = _rotate_strategy(view, str(diagnosis.get("recommended_strategy_id") or "") or None)
    groups = diagnosis.get("recommended_param_groups") or ["runoff", "routing"]
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",") if g.strip()]
    objective = str(diagnosis.get("recommended_objective") or "nse")
    if objective not in {"nse", "peak", "composite"}:
        objective = "nse"
    return {
        "action": ActionCode.A07_OPTIMIZE.value,
        "hypothesis": ProblemHypothesis.MODEL.value,
        "strategy_id": strategy,
        "param_groups": list(groups) if groups else ["runoff", "routing"],
        "objective": objective,
        "rationale_summary": rationale,
    }


def _nse_calibration_progress(
    view: WorldStateView,
    payload: dict,
    *,
    safe_actions: set[str],
    nse_good_enough: float | None = None,
) -> dict:
    """Deterministic NSE loop: calibrate vs observed, stop when NSE is good enough."""
    threshold = (
        float(nse_good_enough)
        if nse_good_enough is not None
        else DEFAULT_NSE_GOOD_ENOUGH
    )
    actions = [item.action.value for item in view.evidence_summary]
    nse = _diagnosis_nse(view)
    gate_status = _latest_status(view, ActionCode.A08_GATE.value)
    resolve_status = _latest_status(view, ActionCode.A09_RESOLVE.value)
    # Adopted candidate → freeze.
    if (
        resolve_status == "ACCEPT"
        and ActionCode.A10_FREEZE.value in safe_actions
        and ActionCode.A10_FREEZE.value not in actions
    ):
        return {
            **payload,
            "action": ActionCode.A10_FREEZE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": "候选已 ACCEPT，NSE 达到可用水平，冻结方案。",
        }

    # After optimize → always gate.
    if (
        ActionCode.A07_OPTIMIZE.value in actions
        and ActionCode.A08_GATE.value not in actions
        and ActionCode.A08_GATE.value in safe_actions
    ):
        return {
            **payload,
            "action": ActionCode.A08_GATE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": "率定候选已生成，用独立验证窗对比观测 NSE 做 Gate。",
        }

    # After gate → resolve.
    if (
        ActionCode.A08_GATE.value in actions
        and ActionCode.A09_RESOLVE.value not in actions
        and ActionCode.A09_RESOLVE.value in safe_actions
    ):
        return {
            **payload,
            "action": ActionCode.A09_RESOLVE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": f"落实 Gate 结果（{gate_status or 'unknown'}）。",
        }

    # Diagnose says NSE / GB/T grade already good enough → freeze (no more calibrate).
    grade_rank = None
    diagnosis = dict(view.hydro.diagnosis or {})
    metrics = diagnosis.get("metrics") if isinstance(diagnosis.get("metrics"), dict) else {}
    if "scheme_grade_rank" in metrics:
        try:
            grade_rank = float(metrics["scheme_grade_rank"])
        except (TypeError, ValueError):
            grade_rank = None
    # 丙 = 1
    gbt_ok = grade_rank is not None and grade_rank >= 1.0
    if (
        (gbt_ok or (nse is not None and nse >= threshold))
        and ActionCode.A06_DIAGNOSE.value in actions
        and ActionCode.A10_FREEZE.value in safe_actions
        and ActionCode.A07_OPTIMIZE.value not in actions
    ):
        return {
            **payload,
            "action": ActionCode.A10_FREEZE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": (
                f"GB/T 方案等级达标或 DC/NSE={nse if nse is not None else 'n/a'} "
                f"≥ {threshold}，视为率定足够，停止搜索。"
            ),
        }
    # After KEEP/ROLLBACK with budget → try another bounded calibrate (rotated strategy).
    if (
        gate_status in {"KEEP", "ROLLBACK"}
        and view.task.allow_optimization
        and ActionCode.A07_OPTIMIZE.value in safe_actions
        and view.budget.optimization_cycles_remaining > 0
        and view.budget.agent_rounds_remaining > CLOSEOUT_RESERVE_ROUNDS
    ):
        a07_count = sum(1 for a in actions if a == ActionCode.A07_OPTIMIZE.value)
        gate_count = sum(1 for a in actions if a == ActionCode.A08_GATE.value)
        if a07_count <= gate_count:  # need a new optimize after latest gate
            return _optimize_payload(
                view,
                rationale=(
                    f"Gate={gate_status} 且 NSE 仍不足，换有界策略再率定 "
                    f"(当前诊断 NSE={nse if nse is not None else 'n/a'})。"
                ),
            )

    # Opt budget or round reserve exhausted after KEEP → freeze base and close out.
    if (
        gate_status in {"KEEP", "ROLLBACK"}
        and ActionCode.A10_FREEZE.value in safe_actions
        and ActionCode.A10_FREEZE.value not in actions
        and (
            view.budget.optimization_cycles_remaining <= 0
            or view.budget.agent_rounds_remaining <= CLOSEOUT_RESERVE_ROUNDS
            or ActionCode.A07_OPTIMIZE.value not in safe_actions
        )
    ):
        return {
            **payload,
            "action": ActionCode.A10_FREEZE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": (
                f"Gate={gate_status} 且优化/收尾预算不足，停止搜索并冻结当前方案以进入回放评估。"
            ),
        }

    # First calibrate after diagnose when NSE is poor / MODEL.
    if (
        view.task.allow_optimization
        and ActionCode.A06_DIAGNOSE.value in actions
        and ActionCode.A07_OPTIMIZE.value not in actions
        and ActionCode.A07_OPTIMIZE.value in safe_actions
        and view.budget.agent_rounds_remaining > CLOSEOUT_RESERVE_ROUNDS
    ):
        if nse is None or nse < threshold:
            return _optimize_payload(
                view,
                rationale=(
                    f"模拟与观测对比 NSE={nse if nse is not None else 'n/a'} "
                    f"< {threshold}（skill nse_good_enough），启动有界参数率定。"
                ),
            )
    # Remap manual strategy if LLM still picks it.
    if (
        payload.get("action") == ActionCode.A07_OPTIMIZE.value
        and payload.get("strategy_id") == "xaj-hydrologist-manual-v1"
    ):
        fixed = dict(payload)
        fixed["strategy_id"] = _rotate_strategy(view, "xaj-bounded-v1")
        return fixed
    return payload


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
        # Common truncation: missing closing braces / quote.
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
    # Close an open string if needed.
    quote_count = fragment.count('"') - fragment.count('\\"')
    if quote_count % 2 == 1:
        fragment += '"'
    opens = fragment.count("{") - fragment.count("}")
    if opens > 0:
        fragment += "}" * opens
    return fragment


def _fallback_payload(view: WorldStateView, *, raw_text: str) -> dict:
    """Deterministic next step when the LLM returns truncated/non-JSON text."""
    actions = [item.action.value for item in view.evidence_summary]
    safe = {a.value for a in view.permissions.safe_actions}
    preferred = None
    if "A07_OPTIMIZE" in actions and "A08_GATE" not in actions:
        preferred = ActionCode.A08_GATE.value
    elif "A08_GATE" in actions and "A09_RESOLVE" not in actions:
        preferred = ActionCode.A09_RESOLVE.value
    elif "A09_RESOLVE" in actions and "A10_FREEZE" not in actions:
        # Allow continue-or-freeze; default freeze to finish the smoke path.
        preferred = ActionCode.A10_FREEZE.value
    elif "A10_FREEZE" in actions and "A11_REPLAY" in safe:
        preferred = ActionCode.A11_REPLAY.value
    elif view.task.phase == "E" and "A12_EVALUATE_REPORT" in safe:
        preferred = ActionCode.A12_EVALUATE_REPORT.value
    elif "A05_FORECAST" not in actions and "A05_FORECAST" in safe:
        preferred = ActionCode.A05_FORECAST.value
    elif "A06_DIAGNOSE" not in actions and "A06_DIAGNOSE" in safe and view.latest_forecast_id:
        preferred = ActionCode.A06_DIAGNOSE.value
    elif "A07_OPTIMIZE" in safe:
        preferred = ActionCode.A07_OPTIMIZE.value
    else:
        preferred = next(iter(sorted(safe)), ActionCode.A01_CHECK_DATA.value)
    # If raw text clearly names an action, prefer that when safe.
    for code in _ACTIONS:
        if code in raw_text and code in safe:
            preferred = code
            break
    return {
        "action": preferred,
        "hypothesis": "MODEL",
        "strategy_id": "xaj-bounded-v1" if preferred == ActionCode.A07_OPTIMIZE.value else None,
        "param_groups": ["evap", "runoff", "routing"]
        if preferred == ActionCode.A07_OPTIMIZE.value
        else None,
        "objective": "nse" if preferred == ActionCode.A07_OPTIMIZE.value else None,
        "rationale_summary": "模型输出不完整，已按证据状态回退到安全的下一步。",
    }


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
    # Automatic agent loop never uses HITL-only manual strategy.
    if action == ActionCode.A07_OPTIMIZE.value and strategy_id == "xaj-hydrologist-manual-v1":
        strategy_id = "xaj-bounded-v1"
    if action != ActionCode.A07_OPTIMIZE.value:
        strategy_id = None

    param_groups = data.get("param_groups")
    objective = data.get("objective")
    if action != ActionCode.A07_OPTIMIZE.value:
        param_groups = None
        objective = None
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
        elif str(objective) not in {"nse", "peak", "composite"}:
            objective = "nse"
        if not param_groups:
            param_groups = ["evap", "runoff", "routing"]
        if not objective:
            objective = "nse"

    data["hypothesis"] = hypothesis
    data["rationale_summary"] = rationale
    data["strategy_id"] = strategy_id
    data["param_groups"] = param_groups
    data["objective"] = objective
    return data
