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
Treat each rejected Gate as new evidence: resolve it, refresh A06 diagnosis, then choose the
next parameter group/objective from the refreshed hydrologic signature. Never repeat a stale
experiment just because NSE is poor. If forcing/model adequacy is doubtful after repeated
rejections, prefer a scientifically explicit stop/escalation over parameter compensation.

Preferred B-phase path:
A01/A03 -> A05_FORECAST -> A06_DIAGNOSE -> (calibrate if evidence supports it) ->
A07_OPTIMIZE -> A08_GATE -> A09_RESOLVE -> A06_DIAGNOSE -> ... -> A10_FREEZE,
then (F) A11_REPLAY -> (E) A12_EVALUATE_REPORT.

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
    (ProblemHypothesis.FORCING, ("forcing", "rainfall", "降水", "强迫", "snow", "融雪")),
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
    if value != value:
        return None
    return value


def _latest_status(view: WorldStateView, action: str) -> str | None:
    for item in reversed(view.evidence_summary):
        if item.action.value == action:
            return item.status
    return None


def _latest_action(view: WorldStateView) -> str | None:
    if not view.evidence_summary:
        return None
    return view.evidence_summary[-1].action.value


def _count_status(view: WorldStateView, action: ActionCode, status: str) -> int:
    return sum(
        1
        for item in view.evidence_summary
        if item.action == action and item.status == status
    )


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


def _action_payload(payload: dict, action: ActionCode, rationale: str, *, hypothesis=None) -> dict:
    return {
        **payload,
        "action": action.value,
        "hypothesis": hypothesis or payload.get("hypothesis") or ProblemHypothesis.MODEL.value,
        "strategy_id": None,
        "param_groups": None,
        "objective": None,
        "rationale_summary": rationale,
    }


def _nse_calibration_progress(
    view: WorldStateView,
    payload: dict,
    *,
    safe_actions: set[str],
    nse_good_enough: float | None = None,
) -> dict:
    """Cycle-aware guardrails around the LLM's hydrologist decision.

    The guardrail owns protocol order (optimize -> gate -> resolve -> re-diagnose),
    while the LLM/skills own the scientific choice of parameter groups and objective.
    """
    threshold = float(nse_good_enough if nse_good_enough is not None else DEFAULT_NSE_GOOD_ENOUGH)
    latest = _latest_action(view)
    nse = _diagnosis_nse(view)
    gate_status = _latest_status(view, ActionCode.A08_GATE.value)
    resolve_status = _latest_status(view, ActionCode.A09_RESOLVE.value)
    diagnosis = dict(view.hydro.diagnosis or {})
    metrics = diagnosis.get("metrics") if isinstance(diagnosis.get("metrics"), dict) else {}
    try:
        forcing_warning = float(metrics.get("forcing_adequacy_warning") or 0.0) >= 0.5
    except (TypeError, ValueError):
        forcing_warning = False
    rollback_count = _count_status(view, ActionCode.A08_GATE, "ROLLBACK")

    # Protocol ordering is determined by the latest evidence, not whether an action ever occurred.
    if latest == ActionCode.A07_OPTIMIZE.value and ActionCode.A08_GATE.value in safe_actions:
        return _action_payload(
            payload,
            ActionCode.A08_GATE,
            "率定候选已生成，用独立 held-out 窗与基线对比后再决定是否采用。",
        )
    if latest == ActionCode.A08_GATE.value and ActionCode.A09_RESOLVE.value in safe_actions:
        return _action_payload(
            payload,
            ActionCode.A09_RESOLVE,
            f"落实本轮 Gate={gate_status or 'unknown'}，不得跳过候选采用/回滚。",
        )

    if latest == ActionCode.A09_RESOLVE.value:
        if resolve_status == "ACCEPT" and ActionCode.A10_FREEZE.value in safe_actions:
            return _action_payload(
                payload,
                ActionCode.A10_FREEZE,
                "本轮候选已 ACCEPT，冻结已采用方案进入回放评估。",
            )
        if resolve_status in {"KEEP", "ROLLBACK"}:
            exhausted = (
                view.budget.optimization_cycles_remaining <= 0
                or view.budget.agent_rounds_remaining <= CLOSEOUT_RESERVE_ROUNDS + 1
                or ActionCode.A07_OPTIMIZE.value not in safe_actions
            )
            if exhausted and ActionCode.A10_FREEZE.value in safe_actions:
                return _action_payload(
                    payload,
                    ActionCode.A10_FREEZE,
                    f"Gate={resolve_status} 且率定预算不足，冻结当前方案并保留失败证据。",
                )
            if ActionCode.A06_DIAGNOSE.value in safe_actions:
                return _action_payload(
                    payload,
                    ActionCode.A06_DIAGNOSE,
                    f"Gate={resolve_status} 后必须刷新诊断；不能继续使用上一轮陈旧误差假说。",
                )

    # Diagnose says the current scheme is already useful enough.
    grade_rank = None
    if "scheme_grade_rank" in metrics:
        try:
            grade_rank = float(metrics["scheme_grade_rank"])
        except (TypeError, ValueError):
            grade_rank = None
    gbt_ok = grade_rank is not None and grade_rank >= 1.0
    if latest == ActionCode.A06_DIAGNOSE.value and (gbt_ok or (nse is not None and nse >= threshold)):
        if ActionCode.A10_FREEZE.value in safe_actions:
            return _action_payload(
                payload,
                ActionCode.A10_FREEZE,
                f"诊断窗已达标（NSE={nse if nse is not None else 'n/a'}，阈值={threshold}），停止搜索。",
            )

    # Two rejected experiments plus a forcing-adequacy warning is evidence of structural mismatch.
    # A hydrologist should stop parameter compensation rather than overfit a held-out event.
    if (
        latest == ActionCode.A06_DIAGNOSE.value
        and forcing_warning
        and rollback_count >= 2
        and ActionCode.A10_FREEZE.value in safe_actions
    ):
        return _action_payload(
            payload,
            ActionCode.A10_FREEZE,
            "连续两轮候选在独立验证中变差，且诊断提示降水+PET难以解释径流上升；停止参数补偿，保留 FORCING/STRUCTURE 升级结论。",
            hypothesis=ProblemHypothesis.FORCING.value,
        )

    # After a fresh diagnosis, preserve a legal LLM calibration experiment. This is where the
    # hydrologist skill can switch from runoff/routing to evap/water-balance, change objective,
    # or select local/global search based on the new evidence.
    if (
        latest == ActionCode.A06_DIAGNOSE.value
        and view.task.allow_optimization
        and view.budget.optimization_cycles_remaining > 0
        and view.budget.agent_rounds_remaining > CLOSEOUT_RESERVE_ROUNDS + 2
        and ActionCode.A07_OPTIMIZE.value in safe_actions
        and (nse is None or nse < threshold)
    ):
        if payload.get("action") == ActionCode.A07_OPTIMIZE.value:
            if payload.get("strategy_id") == "xaj-hydrologist-manual-v1":
                fixed = dict(payload)
                fixed["strategy_id"] = _rotate_strategy(view, "xaj-bounded-v1")
                return fixed
            return payload
        primary = str(diagnosis.get("hypothesis") or "")
        if primary in {"MODEL", "TIMING", "UNKNOWN", ""}:
            return _optimize_payload(
                view,
                rationale=f"新诊断 NSE={nse if nse is not None else 'n/a'} < {threshold}，按本轮误差形态启动新的有界实验。",
            )
        # DATA/FORCING/STATE are allowed to remain non-calibration decisions when the LLM chooses so.
        return payload

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


def _fallback_payload(view: WorldStateView, *, raw_text: str) -> dict:
    """Deterministic next step when the LLM returns truncated/non-JSON text."""
    actions = [item.action.value for item in view.evidence_summary]
    latest = actions[-1] if actions else None
    safe = {a.value for a in view.permissions.safe_actions}
    preferred = None
    if latest == ActionCode.A07_OPTIMIZE.value and ActionCode.A08_GATE.value in safe:
        preferred = ActionCode.A08_GATE.value
    elif latest == ActionCode.A08_GATE.value and ActionCode.A09_RESOLVE.value in safe:
        preferred = ActionCode.A09_RESOLVE.value
    elif latest == ActionCode.A09_RESOLVE.value and ActionCode.A06_DIAGNOSE.value in safe:
        preferred = ActionCode.A06_DIAGNOSE.value
    elif latest == ActionCode.A10_FREEZE.value and ActionCode.A11_REPLAY.value in safe:
        preferred = ActionCode.A11_REPLAY.value
    elif view.task.phase == "E" and ActionCode.A12_EVALUATE_REPORT.value in safe:
        preferred = ActionCode.A12_EVALUATE_REPORT.value
    elif ActionCode.A05_FORECAST.value not in actions and ActionCode.A05_FORECAST.value in safe:
        preferred = ActionCode.A05_FORECAST.value
    elif ActionCode.A06_DIAGNOSE.value in safe and view.latest_forecast_id:
        preferred = ActionCode.A06_DIAGNOSE.value
    elif ActionCode.A07_OPTIMIZE.value in safe:
        preferred = ActionCode.A07_OPTIMIZE.value
    else:
        preferred = next(iter(sorted(safe)), ActionCode.A01_CHECK_DATA.value)
    for code in _ACTIONS:
        if code in raw_text and code in safe:
            preferred = code
            break
    return {
        "action": preferred,
        "hypothesis": "MODEL",
        "strategy_id": "xaj-bounded-v1" if preferred == ActionCode.A07_OPTIMIZE.value else None,
        "param_groups": ["evap", "runoff", "routing"] if preferred == ActionCode.A07_OPTIMIZE.value else None,
        "objective": "nse" if preferred == ActionCode.A07_OPTIMIZE.value else None,
        "rationale_summary": "模型输出不完整，已按最新证据回退到安全的下一步。",
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
        for code in _ACTIONS:
            if action.endswith(code) or code.endswith(action):
                action = code
                break
    if safe_actions and action not in safe_actions:
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

    # Soft format nudges only. Hard protocol ordering is handled cycle-wise above.
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
        if hypothesis and (not rationale or len(hypothesis) > len(rationale)):
            rationale = hypothesis if not rationale else f"{rationale} ({hypothesis})"
        lowered = hypothesis.lower()
        mapped = ProblemHypothesis.UNKNOWN
        for candidate, hints in _HYPOTHESIS_HINTS:
            if any(h in lowered for h in hints):
                mapped = candidate
                break
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
