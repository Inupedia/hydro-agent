"""Deterministic calibration-scientist policy for reproducible research runs.

Owns orchestration only: which stage runs next, and how typed Skill/Core
contracts are sequenced via ``SkillOrchestrator``. Hydrologic knowledge lives
in Agent Skills; continuous parameter search lives in optimizers.
"""

from __future__ import annotations

from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    ProblemHypothesis,
    WorldStateView,
)
from hydro_agent.agent.providers.skill_support import (
    diagnosis_from_view,
    knowledge_context_from_view,
    skill_orchestrator,
)
from hydro_agent.skills import SkillRegistry


class CalibrationScientistDecisionProvider:
    """Evidence-conditioned Observe→Diagnose→Plan→Gate→Reflect policy."""

    def __init__(
        self,
        *,
        max_experiments: int | None = None,
        repository=None,
        skills: SkillRegistry | None = None,
    ) -> None:
        _ = max_experiments
        self.repository = repository
        self.skills = skills
        self.seen_views: list[WorldStateView] = []

    @staticmethod
    def _hypothesis(raw: object) -> ProblemHypothesis:
        try:
            return ProblemHypothesis(str(raw or "UNKNOWN"))
        except ValueError:
            return ProblemHypothesis.UNKNOWN

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

    def _orchestrator(self, view: WorldStateView):
        registry = self.skills
        if registry is None and self.repository is not None:
            registry = SkillRegistry(repository=self.repository)
        return skill_orchestrator(
            registry,
            task_id=view.task.task_id,
            model="calibration-scientist",
        )

    def decide(self, view: WorldStateView) -> AgentDecision:
        self.seen_views.append(view)
        latest = self._latest(view)

        if view.task.phase == "F":
            action = self._fallback(view, ActionCode.A09_REPLAY)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="冻结方案进入历史起报回放，率定参数不再变化。",
            )
        if view.task.phase == "E":
            action = self._fallback(view, ActionCode.A10_EVALUATE_REPORT)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="E 阶段只读评价并生成最终报告。",
            )

        if latest is None:
            action = self._fallback(view, ActionCode.A02_VALIDATE_SCHEME)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary=(
                    f"先验证 {view.model.model_id} 方案、强迫资料与参数契约，"
                    "再进行任何预报或率定。"
                ),
            )

        if latest.action == ActionCode.A02_VALIDATE_SCHEME:
            action = self._fallback(view, ActionCode.A03_FORECAST)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="运行当前基线方案，形成可诊断的真实模型输出。",
            )

        if latest.action == ActionCode.A03_FORECAST:
            action = self._fallback(view, ActionCode.A04_DIAGNOSE)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.UNKNOWN,
                rationale_summary="先基于验证期之前的多日历史误差形成水文诊断，不直接调参。",
            )

        if latest.action == ActionCode.A04_DIAGNOSE:
            diagnosis = diagnosis_from_view(view)
            hypothesis = self._hypothesis(diagnosis.get("hypothesis"))
            if view.hydro.campaign.stop_reason is not None:
                action = self._fallback(view, ActionCode.A08_FREEZE)
                return AgentDecision(
                    action=action,
                    hypothesis=hypothesis,
                    rationale_summary=(
                        f"Campaign stop={view.hydro.campaign.stop_reason}; "
                        "按预注册停止证据请求研究收尾。"
                    ),
                )
            if (
                view.hydro.campaign.mode == "smoke"
                and view.budget.optimization_cycles_remaining <= 0
            ):
                action = self._fallback(view, ActionCode.A08_FREEZE)
                return AgentDecision(
                    action=action,
                    hypothesis=ProblemHypothesis.RESOURCE,
                    rationale_summary=(
                        "Campaign 尚未满足科学停止条件，但运行时优化循环安全预算已耗尽；"
                        "转人工接管，不得宣称收敛。"
                    ),
                )

            orchestrator = self._orchestrator(view)
            plan, invocations = orchestrator.plan_calibration(
                diagnosis,
                view=view,
                campaign_objective=view.hydro.campaign_objective,
                knowledge_context=knowledge_context_from_view(view),
            )
            skill_ids, audit = orchestrator.decision_audit(invocations)
            interpretation = plan.evidence_interpretation
            diagnosis_hypothesis = plan.diagnosis_hypothesis
            action = self._fallback(view, ActionCode.A05_OPTIMIZE)
            patterns = (
                "；".join(interpretation.dominant_patterns[:2])
                if interpretation is not None
                else plan.hypothesis.phenomenon
            )
            analysis = (
                f"{diagnosis_hypothesis.process_layer}："
                f"{' / '.join(diagnosis_hypothesis.falsification_conditions[:2])}"
                if diagnosis_hypothesis is not None
                else plan.rationale
            )
            return AgentDecision(
                action=action,
                hypothesis=hypothesis,
                strategy_id=plan.strategy_id if action == ActionCode.A05_OPTIMIZE else None,
                param_groups=(plan.parameter_groups if action == ActionCode.A05_OPTIMIZE else None),
                objective=plan.objective if action == ActionCode.A05_OPTIMIZE else None,
                rationale_summary=plan.rationale[:600],
                observation_zh=patterns[:240],
                analysis_zh=analysis[:600],
                decision_zh=(
                    f"开放 {','.join(plan.parameter_groups)} · {plan.optimizer} · {plan.objective}"
                )[:240],
                activated_skill_ids=skill_ids,
                activated_skills_audit=audit,
            )

        if latest.action == ActionCode.A05_OPTIMIZE:
            if latest.status != "succeeded":
                action = self._fallback(view, ActionCode.A04_DIAGNOSE)
                return AgentDecision(
                    action=action,
                    hypothesis=ProblemHypothesis.RESOURCE,
                    rationale_summary="率定执行失败且没有可评估候选；重新诊断执行证据，不进入 Gate。",
                )
            action = self._fallback(view, ActionCode.A06_GATE)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="数值优化只产生候选；必须进入独立验证 Gate，不能由率定期指标宣布成功。",
            )

        if latest.action == ActionCode.A06_GATE:
            action = self._fallback(view, ActionCode.A07_RESOLVE)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="按 Gate 结果执行接受、保持或回滚，禁止绕过独立验证。",
            )

        if latest.action == ActionCode.A07_RESOLVE:
            campaign = view.hydro.campaign
            gate_status = str(latest.gates.get("gate_status") or latest.status)
            qualification_status = str(latest.gates.get("qualification_status") or "")
            candidate_adopted = str(latest.gates.get("candidate_adopted") or "").lower() == "true"

            if campaign.stop_reason is not None:
                action = self._fallback(view, ActionCode.A08_FREEZE)
                return AgentDecision(
                    action=action,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary=(
                        f"Campaign stop={campaign.stop_reason}; trials={campaign.resolved_trial_count}, "
                        f"model_evaluations={campaign.total_model_evaluations}, "
                        f"converged={'true' if campaign.converged else 'false'}。"
                    ),
                )
            if (
                view.hydro.campaign.mode == "smoke"
                and view.budget.optimization_cycles_remaining <= 0
            ):
                action = self._fallback(view, ActionCode.A08_FREEZE)
                return AgentDecision(
                    action=action,
                    hypothesis=ProblemHypothesis.RESOURCE,
                    rationale_summary=(
                        f"Gate={gate_status} / Qualification={qualification_status or 'UNKNOWN'}；"
                        "Campaign 尚无科学停止证据，但运行时优化循环安全预算已耗尽，"
                        "转人工接管且不得宣称收敛。"
                    ),
                )

            action = self._fallback(view, ActionCode.A04_DIAGNOSE)
            adopted_note = "已采用改进候选" if candidate_adopted else "候选未采用"
            plateau_note = (
                " 当前为 plateau candidate，但尚未满足预注册重启检查，继续搜索。"
                if campaign.plateau_candidate and not campaign.restart_check_satisfied
                else ""
            )
            orchestrator = self._orchestrator(view)
            review, review_inv = orchestrator.review_calibration(
                diagnosis=diagnosis_from_view(view),
                view=view,
                gate_status=gate_status,
                qualification_status=qualification_status or "NOT_EVALUATED",
                reasons=(adopted_note,),
                campaign_objective=view.hydro.campaign_objective,
                knowledge_context=knowledge_context_from_view(view),
            )
            skill_ids, audit = orchestrator.decision_audit((review_inv,))
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.UNKNOWN,
                rationale_summary=(
                    f"Gate={gate_status} / Qualification={qualification_status or 'UNKNOWN'}；"
                    f"{adopted_note}。Campaign 尚无停止证据，吸收本轮 Evidence 后继续诊断。"
                    f"{plateau_note} review={review.hypothesis_status}"
                )[:600],
                activated_skill_ids=skill_ids,
                activated_skills_audit=audit,
            )

        if latest.action == ActionCode.A08_FREEZE:
            action = self._fallback(view, ActionCode.A09_REPLAY)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="冻结后执行历史起报回放。",
            )
        if latest.action == ActionCode.A09_REPLAY:
            action = self._fallback(view, ActionCode.A10_EVALUATE_REPORT)
            return AgentDecision(
                action=action,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="回放完成后进入只读最终评价。",
            )

        action = self._fallback(view, ActionCode.A04_DIAGNOSE)
        return AgentDecision(
            action=action,
            hypothesis=ProblemHypothesis.UNKNOWN,
            rationale_summary="出现未预期状态，回到证据诊断而不是直接修改参数。",
        )
