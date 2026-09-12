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
from hydro_agent.optimization.calibration_scientist import plan_from_diagnosis


class CalibrationScientistDecisionProvider:
    """Evidence-conditioned Observe→Diagnose→Plan→Gate→Reflect policy."""

    def __init__(self, *, max_experiments: int = 2):
        self.max_experiments = max(1, int(max_experiments))
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
            recommended_action = str(diagnosis.get("recommended_action") or "")
            hypothesis = self._hypothesis(diagnosis.get("hypothesis"))
            if recommended_action == ActionCode.A10_FREEZE.value:
                action = self._fallback(view, ActionCode.A10_FREEZE)
                return AgentDecision(
                    action=action,
                    hypothesis=hypothesis,
                    rationale_summary="率定期证据已足够，不为追求指标继续无意义搜索。",
                )

            plan = plan_from_diagnosis(diagnosis)
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
            completed = view.budget.max_optimization_cycles - view.budget.optimization_cycles_remaining
            gate_status = str(latest.gates.get("status") or latest.status)
            if gate_status == "ACCEPT":
                action = self._fallback(view, ActionCode.A10_FREEZE)
                return AgentDecision(
                    action=action,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary="候选通过独立验证，冻结已解析方案。",
                )
            if completed < self.max_experiments and view.budget.optimization_cycles_remaining > 0:
                action = self._fallback(view, ActionCode.A06_DIAGNOSE)
                return AgentDecision(
                    action=action,
                    hypothesis=ProblemHypothesis.UNKNOWN,
                    rationale_summary=(
                        f"Gate={gate_status}；失败本身作为新 Evidence，重新诊断后再设计一次率定实验，"
                        "而不是重复同一参数搜索。"
                    ),
                )
            action = self._fallback(view, ActionCode.A10_FREEZE)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary=(
                    f"已完成 {completed} 次受控率定实验且未通过 Gate；停止继续试探，冻结解析后的基线方案。"
                ),
            )

        # A10 changes phase synchronously, A11 changes phase synchronously; these are
        # defensive fallbacks for unusual persistence/retry situations.
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
