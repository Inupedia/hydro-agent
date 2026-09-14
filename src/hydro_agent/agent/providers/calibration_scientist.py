"""Deterministic calibration-scientist policy for reproducible research runs.

This is deliberately not presented as an LLM. It implements the same scientific
contract an LLM provider must satisfy so CI and O/P/A experiments can separate
Agent architecture value from model-provider variance.
"""

from __future__ import annotations

import json

from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    ProblemHypothesis,
    WorldStateView,
)
from hydro_agent.knowledge.governance import KnowledgeQueryContext
from hydro_agent.optimization.calibration_scientist import plan_from_diagnosis


class CalibrationScientistDecisionProvider:
    """Evidence-conditioned Observe→Diagnose→Plan→Gate→Reflect policy."""

    def __init__(self) -> None:
        self.seen_views: list[WorldStateView] = []

    @staticmethod
    def _hypothesis(raw: object) -> ProblemHypothesis:
        try:
            return ProblemHypothesis(str(raw or "UNKNOWN"))
        except ValueError:
            return ProblemHypothesis.UNKNOWN

    @staticmethod
    def _diagnosis(view: WorldStateView) -> dict:
        diagnosis = dict(view.hydro.diagnosis or {})
        raw_hypotheses = diagnosis.get("hypotheses_json")
        if isinstance(raw_hypotheses, str) and raw_hypotheses:
            try:
                diagnosis["hypotheses"] = json.loads(raw_hypotheses)
            except json.JSONDecodeError:
                diagnosis["hypotheses"] = []
        return diagnosis

    @staticmethod
    def _knowledge_context(view: WorldStateView) -> KnowledgeQueryContext:
        return KnowledgeQueryContext(
            model_id=str(view.model.model_id),
            basin_id=view.task.basin_id,
            allow_unverified_expert_priors=view.hydro.allow_unverified_expert_priors,
            forbidden_evidence_dataset_ids=view.hydro.forbidden_evidence_dataset_ids,
        )

    @staticmethod
    def _latest(view: WorldStateView):
        return view.evidence_summary[-1] if view.evidence_summary else None

    def _fallback(self, view: WorldStateView, preferred: ActionCode) -> ActionCode:
        safe = tuple(view.permissions.safe_actions)
        if preferred in safe:
            return preferred
        if not safe:
            raise RuntimeError("calibration scientist has no safe action")
        return safe[0]

    def decide(self, view: WorldStateView) -> AgentDecision:
        self.seen_views.append(view)
        latest = self._latest(view)

        if view.task.phase == "F":
            action = self._fallback(view, ActionCode.A11_REPLAY)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="冻结方案进入历史起报回放，率定参数不再变化。",
            )
        if view.task.phase == "E":
            action = self._fallback(view, ActionCode.A12_EVALUATE_REPORT)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="E 阶段只读评价并生成最终报告。",
            )

        if latest is None:
            action = self._fallback(view, ActionCode.A03_VALIDATE_SCHEME)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="先验证 XAJ 方案与参数契约，再进行任何预报或率定。",
            )

        if latest.action == ActionCode.A03_VALIDATE_SCHEME:
            action = self._fallback(view, ActionCode.A05_FORECAST)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="运行当前基线方案，形成可诊断的真实模型输出。",
            )

        if latest.action == ActionCode.A05_FORECAST:
            action = self._fallback(view, ActionCode.A06_DIAGNOSE)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.UNKNOWN,
                rationale_summary="先基于验证期之前的多日历史误差形成水文诊断，不直接调参。",
            )

        if latest.action == ActionCode.A06_DIAGNOSE:
            diagnosis = self._diagnosis(view)
            hypothesis = self._hypothesis(diagnosis.get("hypothesis"))
            # A diagnostic stop suggestion is evidence, not a Campaign stop.
            # Only a preregistered Campaign condition may end automatic search.
            if view.hydro.campaign.stop_reason is not None:
                action = self._fallback(view, ActionCode.A10_FREEZE)
                return AgentDecision(
                    action=action,
                    hypothesis=hypothesis,
                    rationale_summary=(
                        f"Campaign stop={view.hydro.campaign.stop_reason}; "
                        "按预注册停止证据请求研究收尾。"
                    ),
                )

            plan = plan_from_diagnosis(
                diagnosis,
                campaign_objective=view.hydro.campaign_objective,
                knowledge_context=self._knowledge_context(view),
            )
            action = self._fallback(view, ActionCode.A07_OPTIMIZE)
            return AgentDecision(
                action=action,
                hypothesis=hypothesis,
                strategy_id=plan.strategy_id if action == ActionCode.A07_OPTIMIZE else None,
                param_groups=(
                    plan.parameter_groups if action == ActionCode.A07_OPTIMIZE else None
                ),
                objective=plan.objective if action == ActionCode.A07_OPTIMIZE else None,
                rationale_summary=plan.rationale[:600],
            )

        if latest.action == ActionCode.A07_OPTIMIZE:
            action = self._fallback(view, ActionCode.A08_GATE)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="数值优化只产生候选；必须进入独立验证 Gate，不能由率定期指标宣布成功。",
            )

        if latest.action == ActionCode.A08_GATE:
            action = self._fallback(view, ActionCode.A09_RESOLVE)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="按 Gate 结果执行接受、保持或回滚，禁止绕过独立验证。",
            )

        if latest.action == ActionCode.A09_RESOLVE:
            campaign = view.hydro.campaign
            gate_status = str(latest.gates.get("gate_status") or latest.status)
            qualification_status = str(latest.gates.get("qualification_status") or "")
            candidate_adopted = str(latest.gates.get("candidate_adopted") or "").lower() == "true"

            if campaign.stop_reason is not None:
                action = self._fallback(view, ActionCode.A10_FREEZE)
                return AgentDecision(
                    action=action,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary=(
                        f"Campaign stop={campaign.stop_reason}; trials={campaign.resolved_trial_count}, "
                        f"model_evaluations={campaign.total_model_evaluations}, "
                        f"converged={'true' if campaign.converged else 'false'}。"
                    ),
                )

            action = self._fallback(view, ActionCode.A06_DIAGNOSE)
            adopted_note = "已采用改进候选" if candidate_adopted else "候选未采用"
            plateau_note = (
                " 当前为 plateau candidate，但尚未满足预注册重启检查，继续搜索。"
                if campaign.plateau_candidate and not campaign.restart_check_satisfied
                else ""
            )
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.UNKNOWN,
                rationale_summary=(
                    f"Gate={gate_status} / Qualification={qualification_status or 'UNKNOWN'}；"
                    f"{adopted_note}。Campaign 尚无停止证据，吸收本轮 Evidence 后继续诊断。"
                    f"{plateau_note}"
                )[:600],
            )

        # A10 changes phase synchronously only after the closeout tool accepts it;
        # a blocked handover pauses before this provider is called again.
        if latest.action == ActionCode.A10_FREEZE:
            action = self._fallback(view, ActionCode.A11_REPLAY)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="冻结后执行历史起报回放。",
            )
        if latest.action == ActionCode.A11_REPLAY:
            action = self._fallback(view, ActionCode.A12_EVALUATE_REPORT)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="回放完成后进入只读最终评价。",
            )

        action = self._fallback(view, ActionCode.A06_DIAGNOSE)
        return AgentDecision(
            action=action,
            hypothesis=ProblemHypothesis.UNKNOWN,
            rationale_summary="出现未预期状态，回到证据诊断而不是直接修改参数。",
        )
