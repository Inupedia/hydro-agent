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
from hydro_agent.agent.permissions import (
    CLOSEOUT_RESERVE_ROUNDS,
    latest_action_index,
    pending_calibration_action,
    rediagnosis_required,
)
from hydro_agent.agent.providers.skill_support import (
    diagnosis_from_view,
    knowledge_context_from_view,
    skill_orchestrator,
)
from hydro_agent.llm.client import SiliconFlowClient
from hydro_agent.llm.settings import LLMSettings
from hydro_agent.skills import SkillRegistry
from hydro_agent.standards import DEFAULT_GRADE_DC_BING

_HYPOTHESES = tuple(h.value for h in ProblemHypothesis)
_ACTIONS = tuple(a.value for a in ActionCode)
_MODEL_DECISION_KEYS = frozenset(
    {
        "action",
        "hypothesis",
        "strategy_id",
        "param_groups",
        "objective",
        "rationale_summary",
        "observation_zh",
        "analysis_zh",
        "decision_zh",
    }
)
_MODEL_DECISION_KEY_ALIASES = {
    "observation_zzh": "observation_zh",
    "analysis_zzh": "analysis_zh",
    "decision_zzh": "decision_zh",
}

SYSTEM_INSTRUCTIONS = f"""You are the Hydro-Agent decision module for a hydrologist-style research loop.
Choose exactly one ActionCode from permissions.safe_actions.
Never invent continuous parameter vectors or call model processes directly.
Follow activated Agent Skills below for diagnosis and experiment design guidance.
Normative thresholds (GB/T DC floors, Gate policy) come from Standards, not Skills.
Do NOT invent continuous parameters for any hydrologic model.
Choose strategy_id and param_groups only from the current model's advertised lists.
Do NOT choose any hydrologist-manual strategy in the automatic loop.

Preferred B-phase path:
A01/A02 -> A03_FORECAST -> A04_DIAGNOSE -> (calibrate if evidence requires it) ->
A05_OPTIMIZE -> A06_GATE -> A07_RESOLVE -> either re-diagnose or A08_FREEZE,
then (F) A09_REPLAY -> (E) A10_EVALUATE_REPORT.
Adoption and qualification are separate: an adopted candidate may still be unqualified.
Only qualification evidence may declare an optimized candidate complete.
A08 is a closeout request: after a Campaign stop, the tool layer freezes the selected research scheme for read-only final evaluation. Only a QUALIFIED release candidate is release-approved; an unqualified research closeout may still replay and report. Final-test evidence is consumed once after freeze, never during experiment planning.

Return ONLY one JSON object with keys:
- action: ActionCode string
- hypothesis: one of {_HYPOTHESES}
- strategy_id: null, unless action is A05_OPTIMIZE then one of hydro.available_strategies
- param_groups: null, unless A05_OPTIMIZE then a JSON array subset of hydro.available_param_groups (e.g. ["runoff","routing"])
- objective: null, unless A05_OPTIMIZE then one of hydro.available_objectives ("nse"|"peak"|"composite")
- rationale_summary: compact technical reason for audit (<= 120 Chinese chars)
- observation_zh: user-facing Chinese summary of the important evidence you noticed (1 sentence, <= 120 chars)
- analysis_zh: user-facing hydrologist-style analysis summary explaining what the evidence means and why it matters (1-3 sentences, <= 260 chars)
- decision_zh: user-facing Chinese explanation of what you decided to do next and why (1 sentence, <= 120 chars)

The three *_zh fields are deliberate, concise audit summaries for people reading the execution journal.
They are NOT hidden chain-of-thought. Do not expose private scratch work, step-by-step internal reasoning,
JSON field names, ActionCode values, raw arrays, or internal strategy IDs in these user-facing fields.
Write them as normal Chinese a hydrologist or project leader can understand.

Example for a non-optimization step:
{{"action":"A04_DIAGNOSE","hypothesis":"MODEL","strategy_id":null,"param_groups":null,"objective":null,"rationale_summary":"已有预报证据，需要先诊断误差形态再设计实验。","observation_zh":"当前过程线与观测存在系统性偏差。","analysis_zh":"现有证据只能支持模型误差假设，尚不足以直接指定连续参数。","decision_zh":"先形成可审计诊断，再决定是否进入有边界的优化。"}}

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
        self.standards = self.skills.standards

    @property
    def model(self) -> str:
        return self.settings.model

    def _bind_typed_skill_contracts(
        self, view: WorldStateView, decision: AgentDecision
    ) -> AgentDecision:
        """When A05 is chosen, bind strategy fields to the Skill CalibrationPlan chain."""

        if decision.action != ActionCode.A05_OPTIMIZE:
            return decision
        diagnosis = diagnosis_from_view(view)
        if not diagnosis:
            return decision
        orchestrator = skill_orchestrator(
            self.skills,
            task_id=view.task.task_id,
            model=self.settings.model,
        )
        plan, invocations = orchestrator.plan_calibration(
            diagnosis,
            view=view,
            campaign_objective=view.hydro.campaign_objective,
            knowledge_context=knowledge_context_from_view(view),
            proposed_strategy_id=decision.strategy_id,
            proposed_param_groups=tuple(decision.param_groups or ()),
            proposed_objective=decision.objective,
        )
        skill_ids, audits = orchestrator.decision_audit(invocations)
        return decision.model_copy(
            update={
                "strategy_id": plan.strategy_id,
                "param_groups": plan.parameter_groups,
                "objective": plan.objective,
                "rationale_summary": plan.rationale[:600],
                "activated_skill_ids": skill_ids,
                "activated_skills_audit": audits,
            }
        )

    def decide(
        self,
        view: WorldStateView,
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> AgentDecision:
        activated_skill_ids, skill_block, skill_audit = self.skills.activated_for_prompt_with_audit(view)
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
                        "Keep all user-facing *_zh fields concise and readable; do not dump internal JSON or codes into them.\n"
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
            available_param_groups=tuple(view.hydro.available_param_groups),
            available_strategies=tuple(view.hydro.available_strategies),
            model_id=str(view.model.model_id or "xaj"),
        )
        original_action = str(payload.get("action") or "")
        payload = _diagnosis_calibration_progress(
            view,
            payload,
            safe_actions=safe,
            dc_bing_floor=self.standards.grade_dc_bing(),
        )
        if str(payload.get("action") or "") != original_action:
            # The deterministic scientific guardrail may override the model's proposed next action.
            # Keep the model's observation/analysis, but make the visible decision match what runs.
            payload["decision_zh"] = str(payload.get("rationale_summary") or "")[:240]
        decision = AgentDecision.model_validate(payload).model_copy(
            update={
                "activated_skill_ids": activated_skill_ids,
                "activated_skills_audit": tuple(
                    {**item, "output_contract": "AgentDecision", "model": self.settings.model}
                    for item in skill_audit
                ),
            }
        )
        return self._bind_typed_skill_contracts(view, decision)


def _optimize_payload(view: WorldStateView, *, rationale: str) -> dict:
    """Legal A05 shell; typed strategy/groups/objective are bound after decide()."""

    model_id = str(view.model.model_id or "xaj")
    diagnosis = dict(view.hydro.diagnosis or {})
    available_strategies = tuple(view.hydro.available_strategies or ())
    available_groups = tuple(view.hydro.available_param_groups or ())
    if not available_strategies or not available_groups:
        from hydro_agent.models.registry import default_model_registry

        try:
            descriptor = default_model_registry().get(model_id).descriptor
        except KeyError:
            descriptor = None
        if descriptor is not None:
            available_strategies = available_strategies or tuple(descriptor.strategy_ids)
            available_groups = available_groups or tuple(descriptor.parameter_groups)
    proposed_strategy = str(diagnosis.get("recommended_strategy_id") or "").strip()
    strategy_id = (
        proposed_strategy
        if proposed_strategy in available_strategies
        else f"{model_id}-bounded-v1"
    )
    raw_groups = diagnosis.get("recommended_param_groups") or ()
    if isinstance(raw_groups, str):
        raw_groups = tuple(item.strip() for item in raw_groups.split(",") if item.strip())
    groups = [str(item) for item in raw_groups if str(item) in available_groups]
    if not groups:
        groups = list(available_groups)
    if not groups:
        from hydro_agent.models.diagnosis_defaults import all_param_groups

        groups = all_param_groups(model_id)
    proposed_objective = str(diagnosis.get("recommended_objective") or "").strip()
    objective = proposed_objective if proposed_objective in {"nse", "peak", "composite"} else "nse"
    return {
        "action": ActionCode.A05_OPTIMIZE.value,
        "hypothesis": ProblemHypothesis.MODEL.value,
        "strategy_id": strategy_id,
        "param_groups": groups,
        "objective": objective,
        "rationale_summary": rationale,
    }


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


def _latest_gates(view: WorldStateView, action: ActionCode) -> dict[str, str]:
    for item in reversed(view.evidence_summary):
        if item.action == action:
            return dict(item.gates or {})
    return {}


def _diagnosis_calibration_progress(
    view: WorldStateView,
    payload: dict,
    *,
    safe_actions: set[str],
    dc_bing_floor: float | None = None,
) -> dict:
    """Deterministic scientific guardrail around the live LLM calibration loop."""
    threshold = float(dc_bing_floor) if dc_bing_floor is not None else DEFAULT_GRADE_DC_BING
    actions = [item.action.value for item in view.evidence_summary]
    nse = _diagnosis_nse(view)
    gate_status = _latest_status(view, ActionCode.A06_GATE.value)
    resolve_status = _latest_status(view, ActionCode.A07_RESOLVE.value)
    resolve_gates = _latest_gates(view, ActionCode.A07_RESOLVE)
    qualification_status = str(resolve_gates.get("qualification_status") or "")
    resolved_outcome = resolve_status
    if not resolve_gates and resolve_status not in {"ACCEPT", "KEEP", "ROLLBACK"}:
        # Compatibility for evidence persisted before dual-gate A07 semantics:
        # older A07 rows used status="succeeded" while A06 carried KEEP/ROLLBACK.
        if gate_status in {"ACCEPT", "KEEP", "ROLLBACK"}:
            resolved_outcome = gate_status
    pending = pending_calibration_action(view)
    if pending is not None and pending.value in safe_actions:
        return {
            **payload,
            "action": pending.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": (
                "最新率定候选尚未完成独立 Gate。"
                if pending == ActionCode.A06_GATE
                else f"落实最新 Gate 结果（{gate_status or 'unknown'}）。"
            ),
        }

    # A qualified Resolve is the only optimized-candidate path that may declare
    # calibration complete. Adoption alone is not qualification.
    if (
        qualification_status == "QUALIFIED"
        and ActionCode.A08_FREEZE.value in safe_actions
        and ActionCode.A08_FREEZE.value not in actions
    ):
        return {
            **payload,
            "action": ActionCode.A08_FREEZE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": "候选已通过独立资格评价，冻结方案进入回放。",
        }

    # KEEP/ROLLBACK is new evidence. Refresh A04 before selecting another
    # experiment; never select from a stale pre-Gate diagnosis.
    if rediagnosis_required(view) and ActionCode.A04_DIAGNOSE.value in safe_actions:
        return {
            **payload,
            "action": ActionCode.A04_DIAGNOSE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": (
                f"Gate={resolved_outcome or gate_status} / Qualification="
                f"{qualification_status or 'UNKNOWN'}，吸收独立验证证据后重新诊断。"
            ),
        }

    # Before any independent Gate exists, a sufficiently good baseline diagnosis
    # may stop calibration. Once a Gate has explicitly said UNQUALIFIED or
    # NOT_EVALUATED, a later diagnostic NSE cannot override that qualification.
    grade_rank = None
    diagnosis = dict(view.hydro.diagnosis or {})
    metrics = diagnosis.get("metrics") if isinstance(diagnosis.get("metrics"), dict) else {}
    if "scheme_grade_rank" in metrics:
        try:
            grade_rank = float(metrics["scheme_grade_rank"])
        except (TypeError, ValueError):
            grade_rank = None
    gbt_ok = grade_rank is not None and grade_rank >= 1.0  # 丙 = 1
    independent_gate_exists = bool(resolve_gates)
    if (
        not independent_gate_exists
        and (gbt_ok or (nse is not None and nse >= threshold))
        and ActionCode.A04_DIAGNOSE.value in actions
        and ActionCode.A08_FREEZE.value in safe_actions
        and latest_action_index(view, ActionCode.A04_DIAGNOSE)
        > latest_action_index(view, ActionCode.A05_OPTIMIZE)
    ):
        return {
            **payload,
            "action": ActionCode.A08_FREEZE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": (
                f"尚无失败的独立资格证据，且 DC/NSE={nse if nse is not None else 'n/a'} "
                f"达到诊断停止阈值 {threshold}，停止不必要搜索。"
            ),
        }

    # Budget exhaustion requests A08 closeout. The Freeze tool is authoritative:
    # QUALIFIED schemes freeze with release approval; unqualified schemes still
    # freeze into read-only research final evaluation (no human pause).
    if (
        resolved_outcome in {"KEEP", "ROLLBACK"}
        and ActionCode.A08_FREEZE.value in safe_actions
        and ActionCode.A08_FREEZE.value not in actions
        and (
            view.budget.optimization_cycles_remaining <= 0
            or view.budget.agent_rounds_remaining <= CLOSEOUT_RESERVE_ROUNDS
            or ActionCode.A05_OPTIMIZE.value not in safe_actions
        )
    ):
        return {
            **payload,
            "action": ActionCode.A08_FREEZE.value,
            "strategy_id": None,
            "param_groups": None,
            "objective": None,
            "rationale_summary": (
                f"Resolve={resolved_outcome} / Qualification={qualification_status or 'UNKNOWN'}，"
                "优化或收尾预算已耗尽；自动进入研究收口。"
                "不合格方案仍可冻结并回放/出报告，但不放行发布。"
            ),
        }

    # After a fresh diagnosis, start another bounded experiment when either the
    # diagnostic skill is poor or the latest independent qualification has not
    # passed. This prevents a high in-sample NSE from bypassing a failed Gate.
    if (
        view.task.allow_optimization
        and ActionCode.A04_DIAGNOSE.value in actions
        and latest_action_index(view, ActionCode.A04_DIAGNOSE)
        > latest_action_index(view, ActionCode.A05_OPTIMIZE)
        and ActionCode.A05_OPTIMIZE.value in safe_actions
        and view.budget.agent_rounds_remaining > CLOSEOUT_RESERVE_ROUNDS
    ):
        qualification_requires_more = qualification_status in {"UNQUALIFIED", "NOT_EVALUATED"}
        if nse is None or nse < threshold or qualification_requires_more:
            if qualification_requires_more:
                rationale = (
                    f"最近独立资格评价为 {qualification_status}；即使诊断 NSE="
                    f"{nse if nse is not None else 'n/a'}，也不能绕过 Gate，继续设计受控率定实验。"
                )
            else:
                rationale = (
                    f"模拟与观测对比 NSE={nse if nse is not None else 'n/a'} "
                    f"< {threshold}（standard grade_dc_bing），启动有界参数率定。"
                )
            return _optimize_payload(view, rationale=rationale)

    # Remap HITL-only manual strategy to a legal automatic proposal. The
    # ExperimentPlan guardrail will still own the execution-semantic strategy.
    if (
        payload.get("action") == ActionCode.A05_OPTIMIZE.value
        and payload.get("strategy_id") == "xaj-hydrologist-manual-v1"
    ):
        fixed = dict(payload)
        fixed["strategy_id"] = "xaj-bounded-v1"
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
    pending = pending_calibration_action(view)
    if pending is not None and pending.value in safe:
        preferred = pending.value
    elif rediagnosis_required(view) and ActionCode.A04_DIAGNOSE.value in safe:
        preferred = ActionCode.A04_DIAGNOSE.value
    elif "A07_RESOLVE" in actions and "A08_FREEZE" not in actions:
        # Request A08 closeout; the Freeze tool decides freeze vs handover from qualification.
        preferred = ActionCode.A08_FREEZE.value
    elif "A08_FREEZE" in actions and "A09_REPLAY" in safe:
        preferred = ActionCode.A09_REPLAY.value
    elif view.task.phase == "E" and "A10_EVALUATE_REPORT" in safe:
        preferred = ActionCode.A10_EVALUATE_REPORT.value
    elif "A03_FORECAST" not in actions and "A03_FORECAST" in safe:
        preferred = ActionCode.A03_FORECAST.value
    elif "A04_DIAGNOSE" not in actions and "A04_DIAGNOSE" in safe and view.latest_forecast_id:
        preferred = ActionCode.A04_DIAGNOSE.value
    elif "A05_OPTIMIZE" in safe:
        preferred = ActionCode.A05_OPTIMIZE.value
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
        "strategy_id": f"{view.model.model_id}-bounded-v1"
        if preferred == ActionCode.A05_OPTIMIZE.value
        else None,
        "param_groups": list(view.hydro.available_param_groups)
        if preferred == ActionCode.A05_OPTIMIZE.value
        else None,
        "objective": "nse" if preferred == ActionCode.A05_OPTIMIZE.value else None,
        "rationale_summary": "模型输出不完整，已按证据状态回退到安全的下一步。",
    }


def normalize_decision_payload(
    payload: dict,
    *,
    safe_actions: set[str] | None = None,
    evidence_actions: tuple[str, ...] = (),
    available_param_groups: tuple[str, ...] | None = None,
    available_strategies: tuple[str, ...] | None = (),
    model_id: str = "xaj",
) -> dict:
    """Coerce common LLM mistakes into a valid AgentDecision dict."""
    # Treat model output as an untrusted wire payload. Preserve strict
    # AgentDecision validation while repairing known misspellings and dropping
    # fields outside the public model-output contract.
    raw_data = dict(payload)
    for alias, canonical in _MODEL_DECISION_KEY_ALIASES.items():
        if canonical not in raw_data and alias in raw_data:
            raw_data[canonical] = raw_data[alias]
    data = {key: value for key, value in raw_data.items() if key in _MODEL_DECISION_KEYS}
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
            ActionCode.A04_DIAGNOSE.value,
            ActionCode.A03_FORECAST.value,
            ActionCode.A02_VALIDATE_SCHEME.value,
            ActionCode.A05_OPTIMIZE.value,
            ActionCode.A06_GATE.value,
            ActionCode.A07_RESOLVE.value,
            ActionCode.A08_FREEZE.value,
            ActionCode.A09_REPLAY.value,
            ActionCode.A10_EVALUATE_REPORT.value,
            ActionCode.A01_CHECK_DATA.value,
        )
        action = next((a for a in preferred if a in safe_actions), sorted(safe_actions)[0])

    # Soft format nudges only — calibration actions repeat, so compare the
    # latest positions instead of letting an old Gate satisfy a new candidate.
    def latest(code: ActionCode) -> int:
        return max(
            (index for index, item in enumerate(evidence_actions) if item == code.value),
            default=-1,
        )

    optimize_index = latest(ActionCode.A05_OPTIMIZE)
    gate_index = latest(ActionCode.A06_GATE)
    resolve_index = latest(ActionCode.A07_RESOLVE)
    if (
        optimize_index > gate_index
        and action == ActionCode.A03_FORECAST.value
        and (not safe_actions or ActionCode.A06_GATE.value in safe_actions)
    ):
        action = ActionCode.A06_GATE.value
    if (
        gate_index > resolve_index
        and action == ActionCode.A03_FORECAST.value
        and (not safe_actions or ActionCode.A07_RESOLVE.value in safe_actions)
    ):
        action = ActionCode.A07_RESOLVE.value
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
            ActionCode.A03_FORECAST.value,
            ActionCode.A05_OPTIMIZE.value,
            ActionCode.A06_GATE.value,
            ActionCode.A02_VALIDATE_SCHEME.value,
        }:
            mapped = ProblemHypothesis.MODEL
        hypothesis = mapped.value

    if not rationale:
        rationale = f"Proceed with {action}."
    if len(rationale) > 600:
        rationale = rationale[:597] + "..."

    default_strategy = f"{model_id}-bounded-v1"
    if available_strategies:
        if default_strategy not in available_strategies:
            default_strategy = next(
                (sid for sid in available_strategies if sid.startswith(f"{model_id}-")),
                available_strategies[0],
            )
    strategy_id = data.get("strategy_id")
    if strategy_id in ("", "null", "None"):
        strategy_id = None
    if action == ActionCode.A05_OPTIMIZE.value and not strategy_id:
        strategy_id = default_strategy
    # Automatic agent loop never uses HITL-only manual strategy.
    if action == ActionCode.A05_OPTIMIZE.value and str(strategy_id or "").endswith(
        "-hydrologist-manual-v1"
    ):
        strategy_id = default_strategy
    if (
        action == ActionCode.A05_OPTIMIZE.value
        and available_strategies
        and strategy_id not in available_strategies
    ):
        strategy_id = default_strategy
    if action != ActionCode.A05_OPTIMIZE.value:
        strategy_id = None

    from hydro_agent.models.diagnosis_defaults import all_param_groups, allowed_param_groups

    default_groups = list(available_param_groups or all_param_groups(model_id))
    allowed_groups = set(available_param_groups or ()) or allowed_param_groups(model_id)

    param_groups = data.get("param_groups")
    objective = data.get("objective")
    if action != ActionCode.A05_OPTIMIZE.value:
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
                if key in allowed_groups and key not in cleaned:
                    cleaned.append(key)
            param_groups = cleaned or None
        if objective in ("", "null", "None", None):
            objective = None
        elif str(objective) not in {"nse", "peak", "composite"}:
            objective = "nse"
        if not param_groups:
            param_groups = default_groups
        if not objective:
            objective = "nse"

    data["hypothesis"] = hypothesis
    data["rationale_summary"] = rationale
    data["strategy_id"] = strategy_id
    data["param_groups"] = param_groups
    data["objective"] = objective
    return data
