from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, ProblemHypothesis
from hydro_agent.agent.tools import (
    CheckDataHandler,
    DiagnoseHandler,
    EvaluateReportToolHandler,
    ForecastHandler,
    FreezeToolHandler,
    OptimizeHandler,
    ReplayToolHandler,
    ToolRouter,
    ValidateSchemeHandler,
    information_hash,
)
from hydro_agent.evaluation.gbt22482 import HydroSeries
from hydro_agent.evaluation.metrics import bias, high_flow_mae, kge, mae, nse
from hydro_agent.graphs.gbt_accuracy import run_gbt_accuracy
from hydro_agent.models.xaj.contracts import XajBasin, XajScheme
from hydro_agent.models.xaj.upstream import simulate
from hydro_agent.optimization.contracts import EvaluationBundle, LeadMetrics
from hydro_agent.skills import SkillRegistry
from hydro_agent.workbench.real import POLICY, RealWorkbenchKernel
from hydro_agent.workbench.validation_gate import ValidationWindow, resolve_gate_scheme_ids


@dataclass(frozen=True)
class CalibrationPlan:
    calibration: ValidationWindow
    gate_validation: ValidationWindow
    final_holdout: ValidationWindow


class LongPeriodValidationGate:
    """Development Gate over continuous multi-year simulations, not 3-lead snapshots.

    The Gate set may guide iterative calibration, therefore it is deliberately separate
    from the final holdout period used only after Freeze/Replay/Evaluate.
    """

    def __init__(self, *, repository, forecast_service, source, policy, task_configs: dict):
        self.repository = repository
        self.forecast = forecast_service
        self.source = source
        self.policy = policy
        self.task_configs = task_configs

    @staticmethod
    def _day(value, fallback: str) -> date:
        raw = value or fallback
        return date.fromisoformat(raw[:10]) if isinstance(raw, str) else raw

    def plan_for(self, task_id: str) -> CalibrationPlan:
        cfg = self.task_configs.get(task_id) or {}
        cal_start = self._day(cfg.get("calibration_start_date"), "2011-01-01")
        cal_end = self._day(cfg.get("calibration_end_date"), "2017-12-31")
        gate_start = self._day(cfg.get("gate_start_date"), "2018-01-01")
        gate_end = self._day(cfg.get("gate_end_date"), "2019-12-31")
        final_start = self._day(cfg.get("start_date"), "2020-04-01")
        final_end = self._day(cfg.get("end_date"), "2020-07-31")
        if not (cal_start <= cal_end < gate_start <= gate_end < final_start <= final_end):
            raise ValueError(
                "calibration, Gate-development and final-holdout windows must be ordered and disjoint"
            )
        return CalibrationPlan(
            calibration=ValidationWindow(cal_start, cal_end),
            gate_validation=ValidationWindow(gate_start, gate_end),
            final_holdout=ValidationWindow(final_start, final_end),
        )

    def window_for(self, task_id: str) -> ValidationWindow:
        # Used by RealWorkbenchKernel._diagnose. The diagnostic window is constructed
        # immediately before this Gate-development period and therefore remains outside it.
        return self.plan_for(task_id).gate_validation

    def calibration_window_for(self, task_id: str) -> ValidationWindow:
        return self.plan_for(task_id).calibration

    def ensure_forecasts(self, task_id: str, scheme_id: str, window: ValidationWindow) -> None:
        # A06 still uses ordinary forecasts for a short pre-Gate diagnosis window.
        for day in window.issue_days:
            issue = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            self.forecast.forecast(
                task_id=task_id,
                scheme_id=scheme_id,
                issue_time=issue.isoformat().replace("+00:00", "Z"),
                policy=self.policy,
            )

    def _continuous_series(self, scheme_id: str, window: ValidationWindow):
        import numpy as np

        row = self.repository.get_scheme(scheme_id)
        cfg = dict(row.config_json or {})
        scheme = XajScheme(
            model_id="xaj",
            warmup_days=int(cfg.get("warmup_days") or 365),
            parameters=dict(cfg.get("parameters") or {}),
            routing=cfg.get("routing") or {},
        )
        basin = XajBasin(**dict(self.source.basin))
        first = window.start - timedelta(days=scheme.warmup_days)
        forcing_by_day = {r.valid_date: r for r in self.source.forcing_rows}
        days = []
        cur = first
        while cur <= window.end:
            days.append(cur)
            cur += timedelta(days=1)
        missing = [d for d in days if d not in forcing_by_day]
        if missing:
            raise RuntimeError(f"continuous Gate forcing incomplete: {missing[0]}..{missing[-1]}")
        inputs = np.asarray(
            [
                [
                    float(forcing_by_day[d].precipitation_mm_day),
                    float(forcing_by_day[d].pet_mm_day),
                ]
                for d in days
            ],
            dtype=float,
        )[:, None, :]
        values = simulate(scheme, basin, inputs)
        sim_days = days[scheme.warmup_days :]
        truth = {r.valid_date: float(r.discharge_m3s) for r in self.source.flow_rows}
        aligned = [
            (d, float(truth[d]), float(q))
            for d, q in zip(sim_days, values)
            if window.start <= d <= window.end and d in truth
        ]
        if len(aligned) < 30:
            raise RuntimeError("long-period Gate requires at least 30 observed daily pairs")
        obs = [x[1] for x in aligned]
        sim = [x[2] for x in aligned]
        score_nse = float(nse(obs, sim))
        lead_metrics = tuple(
            LeadMetrics(
                lead=lead,  # type: ignore[arg-type]
                nse=score_nse,
                mae=float(mae(obs, sim)),
                bias=float(bias(obs, sim)),
                high_flow_mae=float(high_flow_mae(obs, sim, quantile=0.90)),
            )
            for lead in (1, 2, 3)
        )
        bundle = EvaluationBundle(
            scheme_id=scheme_id,
            leads=lead_metrics,  # compatibility: each lead carries the same continuous-period metrics
            primary_score=score_nse,
        )
        times = tuple(datetime(d.year, d.month, d.day, tzinfo=timezone.utc) for d, _, _ in aligned)
        hydro = HydroSeries(
            obs=tuple(obs),
            sim=tuple(sim),
            times=times,
            dt_hours=24.0,
            area_km2=float(basin.area_km2),
        )
        peak_obs_i = max(range(len(obs)), key=lambda i: obs[i])
        peak_sim_i = max(range(len(sim)), key=lambda i: sim[i])
        peak_obs = float(obs[peak_obs_i])
        peak_sim = float(sim[peak_sim_i])
        try:
            kge_value = float(kge(obs, sim))
        except ValueError:
            kge_value = 0.0
        q90 = float(np.quantile(np.asarray(obs, dtype=float), 0.90))
        flood_idx = [i for i, q in enumerate(obs) if q >= q90]
        flood_volume_bias = (
            float((sum(sim[i] for i in flood_idx) - sum(obs[i] for i in flood_idx)) / max(sum(obs[i] for i in flood_idx), 1e-9))
            if flood_idx
            else 0.0
        )
        meta = {
            "sample_count": float(len(aligned)),
            "continuous_nse": score_nse,
            "continuous_kge": kge_value,
            "continuous_bias": float(bias(obs, sim)),
            "continuous_mae": float(mae(obs, sim)),
            "high_flow_mae_q90": float(high_flow_mae(obs, sim, quantile=0.90)),
            "flood_day_count_q90": float(len(flood_idx)),
            "flood_volume_bias_q90": flood_volume_bias,
            "peak_ratio": float(peak_sim / max(peak_obs, 1e-9)),
            "peak_timing_error_days": float(peak_sim_i - peak_obs_i),
        }
        return bundle, hydro, meta

    def bundles(self, task_id: str):
        base_scheme_id, candidate_scheme_id = resolve_gate_scheme_ids(self.repository, task_id)
        window = self.plan_for(task_id).gate_validation
        base, _base_hydro, base_meta = self._continuous_series(base_scheme_id, window)
        candidate, candidate_hydro, candidate_meta = self._continuous_series(candidate_scheme_id, window)
        meta = {f"base_{k}": v for k, v in base_meta.items()}
        meta.update({f"candidate_{k}": v for k, v in candidate_meta.items()})
        meta["gate_days"] = float((window.end - window.start).days + 1)
        return base, candidate, candidate_hydro, meta


class ConvergenceGateHandler:
    def __init__(self, repository, *, gate_evaluator, policy, bundle_provider, gbt_config_provider):
        self.repository = repository
        self.gate_evaluator = gate_evaluator
        self.policy = policy
        self.bundle_provider = bundle_provider
        self.gbt_config_provider = gbt_config_provider

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        base, candidate, hydro_series, period_metrics = self.bundle_provider(task_id)
        gbt_report = run_gbt_accuracy(hydro_series, self.gbt_config_provider(task_id))
        evidence = self.repository.list_evidence(task_id)
        prior_gates = [row for row in evidence if row.action == ActionCode.A08_GATE.value]
        history = []
        statuses = []
        for row in prior_gates:
            metrics = dict(row.metrics_json or {})
            value = metrics.get("best_primary")
            if value is None:
                b = metrics.get("base_primary")
                c = metrics.get("candidate_primary")
                if b is not None and c is not None:
                    value = max(float(b), float(c))
            if value is not None:
                history.append(float(value))
            statuses.append(str((row.gates_json or {}).get("status") or row.status))
        diagnosis_metrics: dict[str, float] = {}
        for row in reversed(evidence):
            if row.action == ActionCode.A06_DIAGNOSE.value:
                diagnosis_metrics = {
                    str(k): float(v) for k, v in dict(row.metrics_json or {}).items()
                }
                break
        result = self.gate_evaluator.evaluate(
            base,
            candidate,
            self.policy,
            gbt_report=gbt_report,
            history_primary=tuple(history),
            prior_statuses=tuple(statuses),
            diagnosis_metrics=diagnosis_metrics,
        )
        metrics = {
            "primary_delta": float(result.primary_delta),
            "base_primary": float(base.primary_score),
            "candidate_primary": float(candidate.primary_score),
            "best_primary": float(result.best_primary if result.best_primary is not None else max(base.primary_score, candidate.primary_score)),
            "history_points": float(result.history_points),
            **{str(k): float(v) for k, v in period_metrics.items()},
            **gbt_report.as_metrics_dict(),
        }
        if result.convergence_slope is not None:
            metrics["convergence_slope"] = float(result.convergence_slope)
        if result.convergence_gain is not None:
            metrics["convergence_gain"] = float(result.convergence_gain)
        if result.convergence_span is not None:
            metrics["convergence_span"] = float(result.convergence_span)
        observations = (
            f"gate_status={result.status}",
            f"base_primary={base.primary_score:.6f}",
            f"candidate_primary={candidate.primary_score:.6f}",
            f"best_primary={metrics['best_primary']:.6f}",
            f"history_points={result.history_points}",
            f"adopt_candidate={result.adopt_candidate}",
            f"should_stop={result.should_stop}",
            f"scheme_grade={gbt_report.scheme_grade}",
            *result.reasons,
        )
        gates = {
            "status": result.status,
            "base_scheme_id": result.base_scheme_id,
            "candidate_scheme_id": result.candidate_scheme_id,
            "adopt_candidate": "true" if result.adopt_candidate else "false",
            "should_stop": "true" if result.should_stop else "false",
            "reasons": ",".join(result.reasons),
            "scheme_grade": result.scheme_grade or "",
            "gbt_summary": result.gbt_summary or "",
            "gbt_report_json": json.dumps(gbt_report.model_dump(), ensure_ascii=False, sort_keys=True),
        }
        return EvidencePacket(
            evidence_id=f"ev-gate-{len(evidence)+1}",
            task_id=task_id,
            action=ActionCode.A08_GATE,
            status=result.status,
            observations=observations,
            metrics=metrics,
            gates=gates,
            new_information_hash=information_hash(
                action=ActionCode.A08_GATE,
                status=result.status,
                observations=observations,
                metrics=metrics,
            ),
        )


class ConvergenceResolveHandler:
    """Promote improving candidates; keep best-so-far on rollback/structural stop."""

    def __init__(self, repository):
        self.repository = repository

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        evidence = self.repository.list_evidence(task_id)
        gate = next((row for row in reversed(evidence) if row.action == ActionCode.A08_GATE.value), None)
        if gate is None:
            raise RuntimeError("resolve requires Gate evidence")
        gates = dict(gate.gates_json or {})
        status = str(gates.get("status") or gate.status)
        adopt = str(gates.get("adopt_candidate") or "false").lower() == "true"
        candidate_id = gates.get("candidate_scheme_id")
        if adopt and candidate_id:
            self.repository.update_task_state(task_id, current_scheme_id=candidate_id)
        observations = (
            f"resolve_status={status}",
            f"adopt_candidate={adopt}",
            f"current_scheme_id={self.repository.get_task_state(task_id).current_scheme_id}",
        )
        metrics: dict[str, float] = {}
        return EvidencePacket(
            evidence_id=f"ev-resolve-{len(evidence)+1}",
            task_id=task_id,
            action=ActionCode.A09_RESOLVE,
            status=status,  # type: ignore[arg-type]
            observations=observations,
            metrics=metrics,
            gates={
                "status": status,
                "adopt_candidate": "true" if adopt else "false",
                "should_stop": str(gates.get("should_stop") or "false"),
            },
            new_information_hash=information_hash(
                action=ActionCode.A09_RESOLVE,
                status=status,
                observations=observations,
                metrics=metrics,
            ),
        )


class _LongWindowOptimizeHandler:
    def __init__(self, kernel: "ConvergenceWorkbenchKernel"):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        plan = self.kernel.validation_gate.plan_for(task_id)
        cal = plan.calibration
        gate = plan.gate_validation
        warmup = int(self.kernel.scheme_template["warmup_days"])
        cal_days = (cal.end - cal.start).days + 1
        gate_days = (gate.end - gate.start).days + 1
        cal_issue = datetime.combine(cal.end + timedelta(days=1), datetime.min.time(), timezone.utc)
        gate_issue = datetime.combine(gate.end + timedelta(days=1), datetime.min.time(), timezone.utc)
        cal_id = self.kernel.resolver.resolve(
            task_id,
            "calibrate",
            cal_issue.isoformat().replace("+00:00", "Z"),
            history_days=warmup + cal_days + 1,
        )
        gate_id = self.kernel.resolver.resolve(
            task_id,
            "calibrate",
            gate_issue.isoformat().replace("+00:00", "Z"),
            history_days=warmup + gate_days + 1,
        )
        strategy_id = decision.strategy_id or "xaj-bounded-v1"
        param_groups = decision.param_groups
        objective = decision.objective
        if not param_groups or not objective:
            for row in reversed(self.kernel.repository.list_evidence(task_id)):
                if row.action != ActionCode.A06_DIAGNOSE.value:
                    continue
                gates = row.gates_json or {}
                if not param_groups:
                    raw = str(gates.get("recommended_param_groups") or "")
                    param_groups = tuple(x.strip() for x in raw.split(",") if x.strip()) or None
                objective = objective or gates.get("recommended_objective") or None
                strategy_id = strategy_id or gates.get("recommended_strategy_id") or "xaj-bounded-v1"
                break
        patched = AgentDecision(
            action=ActionCode.A07_OPTIMIZE,
            hypothesis=decision.hypothesis,
            strategy_id=strategy_id,
            param_groups=param_groups,
            objective=objective or "nse",  # type: ignore[arg-type]
            rationale_summary=decision.rationale_summary,
        )
        handler = OptimizeHandler(
            self.kernel.repository,
            calibration_service=self.kernel.calibration,
            candidate_service=self.kernel.candidates,
            calibration_snapshot_id=cal_id,
            validation_snapshot_id=gate_id,
            policy=POLICY,
        )
        packet = handler.execute(task_id, patched)
        extra = (
            f"calibration_window={cal.start.isoformat()}..{cal.end.isoformat()}",
            f"gate_development_window={gate.start.isoformat()}..{gate.end.isoformat()}",
            f"calibration_days={cal_days}",
            f"gate_days={gate_days}",
            "final_holdout_not_visible_to_optimizer=true",
        )
        return packet.model_copy(update={"observations": tuple(packet.observations) + extra})


class _TaskForecastHandler:
    def __init__(self, kernel: "ConvergenceWorkbenchKernel"):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        plan = self.kernel.validation_gate.plan_for(task_id)
        # Initial operational forecast is anchored at the end of calibration, before Gate truth.
        issue_day = plan.calibration.end
        issue = datetime(issue_day.year, issue_day.month, issue_day.day, tzinfo=timezone.utc)
        return ForecastHandler(
            self.kernel.repository,
            forecast_service=self.kernel.forecast,
            issue_time=issue.isoformat().replace("+00:00", "Z"),
            policy=POLICY,
        ).execute(task_id, decision)


class _TaskReplayHandler:
    def __init__(self, kernel: "ConvergenceWorkbenchKernel"):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        window = self.kernel.validation_gate.plan_for(task_id).final_holdout
        return ReplayToolHandler(
            self.kernel.repository,
            planner=self.kernel.planner,
            replay_service=self.kernel.replay_service,
            start_date=window.start,
            end_date=window.end,
        ).execute(task_id, decision)


class _TaskEvaluateHandler:
    def __init__(self, kernel: "ConvergenceWorkbenchKernel"):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        window = self.kernel.validation_gate.plan_for(task_id).final_holdout
        issue = datetime(window.end.year, window.end.month, window.end.day, tzinfo=timezone.utc)
        truth_id = self.kernel.ensure_eval_truth_snapshot(task_id, issue)
        out_dir = self.kernel.report_root / task_id
        out_dir.mkdir(parents=True, exist_ok=True)
        return EvaluateReportToolHandler(
            self.kernel.repository,
            evaluation_service=self.kernel.evaluation,
            report_builder=self.kernel.report_builder,
            observation_snapshot_id=truth_id,
            output_dir=out_dir,
        ).execute(task_id, decision)


class ConvergenceWorkbenchKernel(RealWorkbenchKernel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.validation_gate = LongPeriodValidationGate(
            repository=self.repository,
            forecast_service=self.forecast,
            source=self.source,
            policy=POLICY,
            task_configs=self._task_configs,
        )

    def build_tools(self, *, task_configs: dict) -> ToolRouter:
        self._task_configs = task_configs
        self.validation_gate.task_configs = task_configs
        tools = ToolRouter()
        tools.register(ActionCode.A01_CHECK_DATA, CheckDataHandler(self.repository))
        tools.register(ActionCode.A03_VALIDATE_SCHEME, ValidateSchemeHandler(self.repository))
        tools.register(ActionCode.A05_FORECAST, _TaskForecastHandler(self))
        tools.register(ActionCode.A06_DIAGNOSE, DiagnoseHandler(self.repository, diagnose_fn=self._diagnose))
        tools.register(ActionCode.A07_OPTIMIZE, _LongWindowOptimizeHandler(self))
        tools.register(
            ActionCode.A08_GATE,
            ConvergenceGateHandler(
                self.repository,
                gate_evaluator=self.gate,
                policy=self.gate_policy,
                bundle_provider=self.validation_gate.bundles,
                gbt_config_provider=lambda _task_id: self.skills.gbt_accuracy_config(
                    area_km2=float(self.source.basin.get("area_km2") or 0.0)
                ),
            ),
        )
        tools.register(ActionCode.A09_RESOLVE, ConvergenceResolveHandler(self.repository))
        tools.register(ActionCode.A10_FREEZE, FreezeToolHandler(self.repository, freeze_service=self.freeze_service))
        tools.register(ActionCode.A11_REPLAY, _TaskReplayHandler(self))
        tools.register(ActionCode.A12_EVALUATE_REPORT, _TaskEvaluateHandler(self))
        return tools


class ConvergenceDecisionProvider:
    """Use deterministic control for mechanics and LLM+Skills only for hydrologic choices."""

    STOP_STATUSES = {"ACCEPT", "CONVERGED", "STRUCTURAL_LIMIT"}

    def __init__(self, delegate):
        self.delegate = delegate

    @staticmethod
    def _decision(action: ActionCode, rationale: str, hypothesis=ProblemHypothesis.MODEL):
        return AgentDecision(action=action, hypothesis=hypothesis, rationale_summary=rationale)

    def decide(self, view):
        evidence = list(view.evidence_summary)
        actions = [item.action.value for item in evidence]
        safe = {a.value for a in view.permissions.safe_actions}
        if view.task.phase == "F" and ActionCode.A11_REPLAY.value in safe:
            return self._decision(ActionCode.A11_REPLAY, "方案已冻结，仅在最终独立留出期回放一次。")
        if view.task.phase == "E" and ActionCode.A12_EVALUATE_REPORT.value in safe:
            return self._decision(ActionCode.A12_EVALUATE_REPORT, "读取最终留出期结果并形成报告。")

        opt_count = actions.count(ActionCode.A07_OPTIMIZE.value)
        gate_count = actions.count(ActionCode.A08_GATE.value)
        resolve_count = actions.count(ActionCode.A09_RESOLVE.value)
        if opt_count > gate_count and ActionCode.A08_GATE.value in safe:
            return self._decision(ActionCode.A08_GATE, "候选已生成，运行多年开发验证 Gate 并更新收敛曲线。")
        if gate_count > resolve_count and ActionCode.A09_RESOLVE.value in safe:
            return self._decision(ActionCode.A09_RESOLVE, "落实 Gate 的晋升/回滚/停止判定。")

        latest_gate = next(
            (item for item in reversed(evidence) if item.action == ActionCode.A08_GATE),
            None,
        )
        latest_resolve = next(
            (item for item in reversed(evidence) if item.action == ActionCode.A09_RESOLVE),
            None,
        )
        if latest_gate is not None and latest_resolve is not None:
            status = str(latest_gate.gates.get("status") or latest_gate.status)
            if status in self.STOP_STATUSES and ActionCode.A10_FREEZE.value in safe:
                hypothesis = (
                    ProblemHypothesis.FORCING
                    if status == "STRUCTURAL_LIMIT"
                    else ProblemHypothesis.MODEL
                )
                return self._decision(
                    ActionCode.A10_FREEZE,
                    f"Gate={status}，收敛控制器判定无需继续搜索；冻结当前 best-so-far。",
                    hypothesis,
                )
            if status in {"CONTINUE", "ROLLBACK"} and ActionCode.A06_DIAGNOSE.value in safe:
                # Require a fresh diagnosis after every numerical experiment. The next A07
                # remains an LLM+Skill hydrologic choice, not a fixed strategy rotation.
                if not evidence or evidence[-1].action != ActionCode.A06_DIAGNOSE:
                    return self._decision(
                        ActionCode.A06_DIAGNOSE,
                        f"Gate={status} 后重新诊断当前 best-so-far，再决定是否/如何继续率定。",
                    )
        return self.delegate.decide(view)
