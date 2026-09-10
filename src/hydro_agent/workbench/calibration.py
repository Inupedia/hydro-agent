from __future__ import annotations

from datetime import datetime, timezone

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, ProblemHypothesis
from hydro_agent.agent.tools import (
    CheckDataHandler,
    DiagnoseHandler,
    EvaluateReportToolHandler,
    ForecastHandler,
    FreezeToolHandler,
    ReplayToolHandler,
    ToolRouter,
    ValidateSchemeHandler,
)
from hydro_agent.calibration.contracts import CalibrationPhase
from hydro_agent.calibration.convergence import SearchConvergenceController
from hydro_agent.calibration.phase_gate import HydrologicPhaseGate
from hydro_agent.calibration.protocol import CalibrationProtocol
from hydro_agent.graphs.gbt_accuracy import run_gbt_accuracy
from hydro_agent.optimization.contracts import ParameterGuidance
from hydro_agent.workbench.calibration_evaluation import CalibrationEvaluationService
from hydro_agent.workbench.calibration_handlers import (
    HydrologicGateHandler,
    PhaseOptimizeHandler,
    ProtocolResolveHandler,
)
from hydro_agent.workbench.real import POLICY, RealWorkbenchKernel


class CalibrationWorkbenchKernel(RealWorkbenchKernel):
    """Hydrologist-style XAJ calibration workbench.

    The kernel wires domain services together. Hydrologic metrics, phase gates,
    convergence control and numerical optimization live in dedicated modules so the
    orchestration layer stays small and auditable.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.protocol = CalibrationProtocol()
        self.evaluator = CalibrationEvaluationService(
            repository=self.repository,
            source=self.source,
            task_configs=self._task_configs,
        )
        self.validation_gate = self.evaluator
        self.phase_gate = HydrologicPhaseGate()
        self.convergence = SearchConvergenceController()

    def build_tools(self, *, task_configs: dict) -> ToolRouter:
        self._task_configs = task_configs
        self.evaluator.task_configs = task_configs
        tools = ToolRouter()
        tools.register(ActionCode.A01_CHECK_DATA, CheckDataHandler(self.repository))
        tools.register(ActionCode.A03_VALIDATE_SCHEME, ValidateSchemeHandler(self.repository))
        tools.register(ActionCode.A05_FORECAST, _CalibrationForecastHandler(self))
        tools.register(
            ActionCode.A06_DIAGNOSE,
            DiagnoseHandler(self.repository, diagnose_fn=self._diagnose_phase),
        )
        tools.register(ActionCode.A07_OPTIMIZE, PhaseOptimizeHandler(self))
        tools.register(ActionCode.A08_GATE, HydrologicGateHandler(self))
        tools.register(ActionCode.A09_RESOLVE, ProtocolResolveHandler(self.repository))
        tools.register(
            ActionCode.A10_FREEZE,
            FreezeToolHandler(self.repository, freeze_service=self.freeze_service),
        )
        tools.register(ActionCode.A11_REPLAY, _CalibrationReplayHandler(self))
        tools.register(ActionCode.A12_EVALUATE_REPORT, _CalibrationEvaluateHandler(self))
        return tools

    def _diagnose_phase(self, task_id: str) -> dict:
        evidence = self.repository.list_evidence(task_id)
        phase = self.protocol.phase_from_evidence(evidence)
        state = self.repository.get_task_state(task_id)
        plan = self.evaluator.plan_for(task_id)
        window = (
            plan.development
            if phase == CalibrationPhase.DEVELOPMENT_VALIDATION
            else plan.calibration
        )
        _hydro, signatures = self.evaluator.evaluate_scheme(state.current_scheme_id, window)
        metrics = dict(signatures.metrics)

        # A rain+PET XAJ should not compensate parameters when runoff depth is
        # physically inconsistent with forcing; the flag is evidence for a structural
        # escalation, not an automatic proof of missing snowmelt.
        runoff_ratio = metrics.get("observed_runoff_ratio")
        metrics["forcing_adequacy_warning"] = float(
            runoff_ratio is not None and runoff_ratio > 1.20
        )

        if phase == CalibrationPhase.WATER_BALANCE:
            phenomenon = (
                f"多年水量相对误差={metrics['volume_rel_error']:.3f}; "
                f"年际MAE={metrics['annual_volume_bias_mae']:.3f}; "
                f"季节MAE={metrics['seasonal_volume_bias_mae']:.3f}"
            )
            groups = ("evap", "runoff")
            objective = "water_balance"
        elif phase == CalibrationPhase.SOURCE_RECESSION:
            phenomenon = (
                f"退水误差 fast={metrics['recession_fast_rel_error']:.3f}, "
                f"mid={metrics['recession_mid_rel_error']:.3f}, "
                f"tail={metrics['recession_tail_rel_error']:.3f}"
            )
            groups = ("runoff",)
            objective = "recession"
        elif phase == CalibrationPhase.ROUTING_EVENT:
            phenomenon = (
                f"事件洪峰中位误差={metrics['event_peak_rel_error_median']:.3f}; "
                f"峰现={metrics['event_peak_timing_steps_median']:.2f}步; "
                f"洪量={metrics['event_volume_rel_error_median']:.3f}"
            )
            groups = ("routing",)
            objective = "routing_event"
        elif phase == CalibrationPhase.JOINT_REFINE:
            phenomenon = (
                f"整体NSE={metrics['nse']:.3f}; KGE={metrics['kge']:.3f}，"
                "在已通过的水文约束内收口"
            )
            groups = ("evap", "runoff", "routing")
            objective = "joint"
        elif phase == CalibrationPhase.DEVELOPMENT_VALIDATION:
            phenomenon = (
                f"开发验证 NSE={metrics['nse']:.3f}; KGE={metrics['kge']:.3f}; "
                f"水量误差={metrics['volume_rel_error']:.3f}; "
                f"洪水事件={int(metrics['flood_event_count'])}场"
            )
            groups = ()
            objective = "joint"
        else:
            phenomenon = "最终holdout阶段禁止继续诊断和调参"
            groups = ()
            objective = "joint"

        forcing_warning = metrics["forcing_adequacy_warning"] >= 0.5
        hypothesis = "FORCING" if forcing_warning else "MODEL"
        next_action = (
            "A08_GATE"
            if phase == CalibrationPhase.DEVELOPMENT_VALIDATION
            else "A07_OPTIMIZE"
        )
        return {
            "hypothesis": hypothesis,
            "phenomenon": phenomenon,
            "recommended_action": next_action,
            "recommended_strategy_id": "xaj-local-refine-v1",
            "recommended_param_groups": groups,
            "recommended_objective": objective,
            "metrics": metrics,
            "hypotheses": [
                {
                    "id": hypothesis,
                    "strength": 0.75 if forcing_warning else 0.70,
                    "suggested_action": next_action,
                    "suggested_strategy_id": "xaj-local-refine-v1",
                }
            ],
            "notes": [
                f"calibration_phase={phase.value}",
                f"signature_window={window.start}..{window.end}",
                f"flood_event_count={len(signatures.events)}",
                "diagnosis_uses_continuous_hydrologic_signatures=true",
                (
                    "forcing_warning_blocks_parameter_compensation=true"
                    if forcing_warning
                    else "forcing_warning_blocks_parameter_compensation=false"
                ),
            ],
        }


class HydrologistProtocolDecisionProvider:
    """Own protocol mechanics while the LLM owns scientific experiment choices.

    Lifetime mechanics use ``HydroContext.action_counts/latest_gate`` derived from the
    full evidence ledger. The rolling evidence summary is used only for the immediate
    previous action and scientific context.
    """

    _TERMINAL_LIMITS = {
        "DATA_LIMIT",
        "FORCING_LIMIT",
        "STRUCTURAL_LIMIT",
        "HARD_BUDGET",
        "PLATEAU_FAIL",
    }
    _PHASE_DEFAULTS = {
        CalibrationPhase.WATER_BALANCE.value: (("evap", "runoff"), "water_balance"),
        CalibrationPhase.SOURCE_RECESSION.value: (("runoff",), "recession"),
        CalibrationPhase.ROUTING_EVENT.value: (("routing",), "routing_event"),
        CalibrationPhase.JOINT_REFINE.value: (("evap", "runoff", "routing"), "joint"),
    }

    def __init__(self, delegate):
        self.delegate = delegate

    @staticmethod
    def _decision(
        action: ActionCode,
        rationale: str,
        hypothesis: ProblemHypothesis = ProblemHypothesis.MODEL,
    ) -> AgentDecision:
        return AgentDecision(
            action=action,
            hypothesis=hypothesis,
            rationale_summary=rationale,
        )

    def decide(self, view):
        evidence = list(view.evidence_summary)
        safe = {a.value for a in view.permissions.safe_actions}
        latest = evidence[-1] if evidence else None
        phase = str(view.hydro.calibration_phase)
        counts = dict(view.hydro.action_counts or {})
        latest_gate = dict(view.hydro.latest_gate or {})

        def count(action: ActionCode) -> int:
            return int(counts.get(action.value, 0))

        if view.task.phase == "F" and ActionCode.A11_REPLAY.value in safe:
            return self._decision(
                ActionCode.A11_REPLAY,
                "方案已冻结，只在最终独立holdout回放。",
            )
        if view.task.phase == "E" and ActionCode.A12_EVALUATE_REPORT.value in safe:
            return self._decision(
                ActionCode.A12_EVALUATE_REPORT,
                "读取最终holdout并形成一次性终评。",
            )

        # One-time initialization is durable; never infer it from the rolling prompt window.
        if count(ActionCode.A01_CHECK_DATA) == 0 and ActionCode.A01_CHECK_DATA.value in safe:
            return self._decision(
                ActionCode.A01_CHECK_DATA,
                "先验证资料与任务可用性。",
                ProblemHypothesis.DATA,
            )
        if count(ActionCode.A03_VALIDATE_SCHEME) == 0 and ActionCode.A03_VALIDATE_SCHEME.value in safe:
            return self._decision(ActionCode.A03_VALIDATE_SCHEME, "确认XAJ参数初值和方案合法。")
        if count(ActionCode.A05_FORECAST) == 0 and ActionCode.A05_FORECAST.value in safe:
            return self._decision(ActionCode.A05_FORECAST, "建立初始过程证据。")
        if count(ActionCode.A06_DIAGNOSE) == 0 and ActionCode.A06_DIAGNOSE.value in safe:
            return self._decision(ActionCode.A06_DIAGNOSE, "按当前水文阶段提取连续signature并诊断。")

        # Recover protocol order from lifetime counts even if a transient fallback action
        # was inserted or the originating evidence fell out of the prompt window.
        if count(ActionCode.A07_OPTIMIZE) > count(ActionCode.A08_GATE):
            if ActionCode.A08_GATE.value in safe:
                return self._decision(
                    ActionCode.A08_GATE,
                    "存在未Gate的新unique experiment，运行当前HydrologicPhaseGate。",
                )
        if count(ActionCode.A08_GATE) > count(ActionCode.A09_RESOLVE):
            if ActionCode.A09_RESOLVE.value in safe:
                return self._decision(
                    ActionCode.A09_RESOLVE,
                    f"落实阶段Gate={latest_gate.get('status', 'unknown')}的采用、回滚或返工路由。",
                )

        if latest is not None and latest.action == ActionCode.A09_RESOLVE:
            status = str(latest.gates.get("status") or latest_gate.get("status") or latest.status)
            return_phase = str(
                latest.gates.get("return_phase") or latest_gate.get("return_phase") or ""
            )
            if phase == CalibrationPhase.FINAL_HOLDOUT.value and ActionCode.A10_FREEZE.value in safe:
                return self._decision(
                    ActionCode.A10_FREEZE,
                    "P6独立开发验证通过，冻结方案后才能读取最终holdout。",
                )
            if return_phase and ActionCode.A06_DIAGNOSE.value in safe:
                return self._decision(
                    ActionCode.A06_DIAGNOSE,
                    f"P6失败已归因并返回{return_phase}，重新提取该阶段signature。",
                )
            if status in self._TERMINAL_LIMITS and ActionCode.A10_FREEZE.value in safe:
                hypothesis = (
                    ProblemHypothesis.FORCING
                    if status == "FORCING_LIMIT"
                    else ProblemHypothesis.MODEL
                )
                return self._decision(
                    ActionCode.A10_FREEZE,
                    f"率定以{status}终止，冻结当前best并保留失败证据。",
                    hypothesis,
                )
            if ActionCode.A06_DIAGNOSE.value in safe:
                return self._decision(
                    ActionCode.A06_DIAGNOSE,
                    f"上一实验={status}，按新的{phase}重新提取signature。",
                )

        # Defensive terminal recovery: if the resolve happened but its row is no longer
        # the latest prompt item, a terminal latest Gate still owns the next transition.
        if (
            count(ActionCode.A08_GATE) == count(ActionCode.A09_RESOLVE)
            and count(ActionCode.A08_GATE) > 0
            and str(latest_gate.get("status") or "") in self._TERMINAL_LIMITS
            and not str(latest_gate.get("return_phase") or "")
            and ActionCode.A10_FREEZE.value in safe
        ):
            status = str(latest_gate.get("status"))
            hypothesis = (
                ProblemHypothesis.FORCING
                if status == "FORCING_LIMIT"
                else ProblemHypothesis.MODEL
            )
            return self._decision(
                ActionCode.A10_FREEZE,
                f"最新已解析Gate={status}为终止状态，不再生成新的率定实验。",
                hypothesis,
            )

        if phase == CalibrationPhase.FINAL_HOLDOUT.value and ActionCode.A10_FREEZE.value in safe:
            return self._decision(
                ActionCode.A10_FREEZE,
                "开发验证已完成，禁止再调参；冻结后进入最终holdout。",
            )

        if latest is not None and latest.action == ActionCode.A06_DIAGNOSE:
            if phase == CalibrationPhase.DEVELOPMENT_VALIDATION.value:
                if ActionCode.A08_GATE.value in safe:
                    return self._decision(
                        ActionCode.A08_GATE,
                        "P6只做独立开发验证，不生成新的参数候选。",
                    )
            if view.budget.optimization_cycles_remaining <= 0 and ActionCode.A10_FREEZE.value in safe:
                return self._decision(
                    ActionCode.A10_FREEZE,
                    "优化hard ceiling已到，冻结当前best并保留预算终止证据。",
                    ProblemHypothesis.RESOURCE,
                )

            forcing_warning = float(latest.metrics.get("forcing_adequacy_warning", 0.0)) >= 0.5
            if forcing_warning and ActionCode.A07_OPTIMIZE.value in safe:
                groups, objective = self._PHASE_DEFAULTS.get(
                    phase,
                    (("evap", "runoff", "routing"), "joint"),
                )
                return AgentDecision(
                    action=ActionCode.A07_OPTIMIZE,
                    hypothesis=ProblemHypothesis.FORCING,
                    strategy_id="xaj-local-refine-v1",
                    param_groups=groups,  # type: ignore[arg-type]
                    objective=objective,  # type: ignore[arg-type]
                    parameter_guidance=ParameterGuidance(
                        frozen_parameters=tuple(view.hydro.available_tunable_parameters)  # type: ignore[arg-type]
                    ),
                    rationale_summary=(
                        "forcing adequacy warning 已成立；禁止用 XAJ 参数补偿潜在缺失过程。"
                        "本轮只执行 frozen no-change probe，让 Gate 形成可审计的 FORCING_LIMIT 证据。"
                    ),
                )

            delegated = self.delegate.decide(view)
            if delegated.action != ActionCode.A07_OPTIMIZE:
                if (
                    delegated.action == ActionCode.A10_FREEZE
                    and delegated.hypothesis in {ProblemHypothesis.DATA, ProblemHypothesis.FORCING}
                ):
                    return delegated
                delegated = AgentDecision(
                    action=ActionCode.A07_OPTIMIZE,
                    hypothesis=delegated.hypothesis,
                    strategy_id=delegated.strategy_id or "xaj-local-refine-v1",
                    param_groups=None,
                    objective=None,
                    parameter_guidance=delegated.parameter_guidance,
                    rationale_summary=(
                        f"{delegated.rationale_summary}；按当前phase执行最小范围率定实验。"
                    ),
                )
            groups, objective = self._PHASE_DEFAULTS.get(
                phase,
                (("evap", "runoff", "routing"), "joint"),
            )
            selected = tuple(
                g for g in (delegated.param_groups or groups) if g in set(groups)
            ) or groups
            return delegated.model_copy(
                update={
                    "param_groups": selected,
                    "objective": objective,
                    "strategy_id": delegated.strategy_id or "xaj-local-refine-v1",
                }
            )

        if phase == CalibrationPhase.DEVELOPMENT_VALIDATION.value and ActionCode.A08_GATE.value in safe:
            return self._decision(
                ActionCode.A08_GATE,
                "运行独立development Gate并决定通过、返工或结构性终止。",
            )
        return self.delegate.decide(view)


class _CalibrationForecastHandler:
    def __init__(self, kernel: CalibrationWorkbenchKernel):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        issue_day = self.kernel.evaluator.plan_for(task_id).calibration.end
        issue = datetime(issue_day.year, issue_day.month, issue_day.day, tzinfo=timezone.utc)
        return ForecastHandler(
            self.kernel.repository,
            forecast_service=self.kernel.forecast,
            issue_time=issue.isoformat().replace("+00:00", "Z"),
            policy=POLICY,
        ).execute(task_id, decision)


class _CalibrationReplayHandler:
    def __init__(self, kernel: CalibrationWorkbenchKernel):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        window = self.kernel.evaluator.plan_for(task_id).final_holdout
        return ReplayToolHandler(
            self.kernel.repository,
            planner=self.kernel.planner,
            replay_service=self.kernel.replay_service,
            start_date=window.start,
            end_date=window.end,
        ).execute(task_id, decision)


class _CalibrationEvaluateHandler:
    def __init__(self, kernel: CalibrationWorkbenchKernel):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        window = self.kernel.evaluator.plan_for(task_id).final_holdout
        issue = datetime(window.end.year, window.end.month, window.end.day, tzinfo=timezone.utc)
        truth_id = self.kernel.ensure_eval_truth_snapshot(task_id, issue)
        out_dir = self.kernel.report_root / task_id
        out_dir.mkdir(parents=True, exist_ok=True)
        packet = EvaluateReportToolHandler(
            self.kernel.repository,
            evaluation_service=self.kernel.evaluation,
            report_builder=self.kernel.report_builder,
            observation_snapshot_id=truth_id,
            output_dir=out_dir,
        ).execute(task_id, decision)

        state = self.kernel.repository.get_task_state(task_id)
        hydro, signatures = self.kernel.evaluator.evaluate_scheme(state.current_scheme_id, window)
        gbt = run_gbt_accuracy(
            hydro,
            self.kernel.skills.gbt_accuracy_config(
                area_km2=float(self.kernel.source.basin.get("area_km2") or 0.0)
            ),
        )
        metrics = {
            **dict(packet.metrics),
            **{f"holdout_{k}": float(v) for k, v in signatures.metrics.items()},
            **{f"holdout_gbt_{k}": float(v) for k, v in gbt.as_metrics_dict().items()},
        }
        observations = tuple(packet.observations) + (
            f"calibration_phase={CalibrationPhase.FINAL_HOLDOUT.value}",
            f"holdout_window={window.start}..{window.end}",
            f"holdout_scheme_grade={gbt.scheme_grade}",
            "final_holdout_read_once=true",
        )
        return packet.model_copy(update={"metrics": metrics, "observations": observations})
