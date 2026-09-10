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
from hydro_agent.calibration.contracts import (
    CalibrationPhase,
    PhaseGateStatus,
    SearchProgressPoint,
)
from hydro_agent.calibration.convergence import SearchConvergenceController
from hydro_agent.calibration.phase_gate import HydrologicPhaseGate
from hydro_agent.calibration.protocol import CalibrationProtocol
from hydro_agent.calibration.signatures import HydrologicSignatures, compute_hydrologic_signatures
from hydro_agent.evaluation.gbt22482 import HydroSeries
from hydro_agent.graphs.gbt_accuracy import run_gbt_accuracy
from hydro_agent.models.xaj.contracts import XajBasin, XajScheme
from hydro_agent.models.xaj.upstream import simulate
from hydro_agent.workbench.real import POLICY, RealWorkbenchKernel
from hydro_agent.workbench.validation_gate import ValidationWindow


@dataclass(frozen=True)
class CalibrationPlan:
    calibration: ValidationWindow
    development: ValidationWindow
    final_holdout: ValidationWindow


class CalibrationEvaluationService:
    """Continuous multi-year evaluation + hydrologic signatures for one XAJ scheme."""

    def __init__(self, *, repository, source, task_configs: dict):
        self.repository = repository
        self.source = source
        self.task_configs = task_configs

    @staticmethod
    def _day(value, fallback: str) -> date:
        raw = value or fallback
        return date.fromisoformat(raw[:10]) if isinstance(raw, str) else raw

    def plan_for(self, task_id: str) -> CalibrationPlan:
        cfg = self.task_configs.get(task_id) or {}
        cal_start = self._day(cfg.get("calibration_start_date"), "2011-01-01")
        cal_end = self._day(cfg.get("calibration_end_date"), "2017-12-31")
        dev_start = self._day(cfg.get("gate_start_date"), "2018-01-01")
        dev_end = self._day(cfg.get("gate_end_date"), "2019-12-31")
        final_start = self._day(cfg.get("start_date"), "2020-04-01")
        final_end = self._day(cfg.get("end_date"), "2020-07-31")
        if not (cal_start <= cal_end < dev_start <= dev_end < final_start <= final_end):
            raise ValueError("calibration, development and final holdout windows must be ordered and disjoint")
        return CalibrationPlan(
            calibration=ValidationWindow(cal_start, cal_end),
            development=ValidationWindow(dev_start, dev_end),
            final_holdout=ValidationWindow(final_start, final_end),
        )

    # Compatibility for RealWorkbench diagnostics that need a reference window.
    def window_for(self, task_id: str) -> ValidationWindow:
        return self.plan_for(task_id).development

    def calibration_window_for(self, task_id: str) -> ValidationWindow:
        return self.plan_for(task_id).calibration

    def evaluate_scheme(
        self,
        scheme_id: str,
        window: ValidationWindow,
    ) -> tuple[HydroSeries, HydrologicSignatures]:
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
        truth = {r.valid_date: float(r.discharge_m3s) for r in self.source.flow_rows}

        days: list[date] = []
        cur = first
        while cur <= window.end:
            days.append(cur)
            cur += timedelta(days=1)
        missing = [d for d in days if d not in forcing_by_day]
        if missing:
            raise RuntimeError(f"forcing incomplete: {missing[0]}..{missing[-1]}")
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
        aligned = [
            (d, float(truth[d]), float(q), float(forcing_by_day[d].precipitation_mm_day))
            for d, q in zip(sim_days, values)
            if window.start <= d <= window.end and d in truth
        ]
        if len(aligned) < 30:
            raise RuntimeError("calibration evaluation requires at least 30 observed daily pairs")
        obs = tuple(row[1] for row in aligned)
        sim = tuple(row[2] for row in aligned)
        precip = tuple(row[3] for row in aligned)
        times = tuple(datetime(d.year, d.month, d.day, tzinfo=timezone.utc) for d, *_ in aligned)
        hydro = HydroSeries(
            obs=obs,
            sim=sim,
            times=times,
            dt_hours=24.0,
            area_km2=float(basin.area_km2),
        )
        signatures = compute_hydrologic_signatures(
            obs,
            sim,
            times=times,
            precipitation_mm=precip,
            area_km2=float(basin.area_km2),
            dt_hours=24.0,
        )
        return hydro, signatures


class PhaseOptimizeHandler:
    _DEFAULTS = {
        CalibrationPhase.WATER_BALANCE: (("evap", "runoff"), "water_balance"),
        CalibrationPhase.SOURCE_RECESSION: (("runoff", "routing"), "recession"),
        CalibrationPhase.ROUTING_EVENT: (("runoff", "routing"), "routing_event"),
        CalibrationPhase.JOINT_REFINE: (("evap", "runoff", "routing"), "joint"),
    }

    def __init__(self, kernel: "CalibrationWorkbenchKernel"):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        evidence = self.kernel.repository.list_evidence(task_id)
        phase = self.kernel.protocol.phase_from_evidence(evidence)
        if phase not in self._DEFAULTS:
            raise RuntimeError(f"optimization forbidden in calibration phase {phase.value}")
        default_groups, objective = self._DEFAULTS[phase]
        allowed_groups = set(default_groups)
        selected_groups = tuple(g for g in (decision.param_groups or default_groups) if g in allowed_groups)
        if not selected_groups:
            selected_groups = default_groups

        plan = self.kernel.evaluator.plan_for(task_id)
        cal = plan.calibration
        dev = plan.development
        warmup = int(self.kernel.scheme_template["warmup_days"])
        cal_days = (cal.end - cal.start).days + 1
        dev_days = (dev.end - dev.start).days + 1
        cal_issue = datetime.combine(cal.end + timedelta(days=1), datetime.min.time(), timezone.utc)
        dev_issue = datetime.combine(dev.end + timedelta(days=1), datetime.min.time(), timezone.utc)
        cal_id = self.kernel.resolver.resolve(
            task_id,
            "calibrate",
            cal_issue.isoformat().replace("+00:00", "Z"),
            history_days=warmup + cal_days + 1,
        )
        dev_id = self.kernel.resolver.resolve(
            task_id,
            "calibrate",
            dev_issue.isoformat().replace("+00:00", "Z"),
            history_days=warmup + dev_days + 1,
        )
        patched = AgentDecision(
            action=ActionCode.A07_OPTIMIZE,
            hypothesis=decision.hypothesis,
            strategy_id=decision.strategy_id or "xaj-bounded-v1",
            param_groups=selected_groups,  # type: ignore[arg-type]
            objective=objective,  # type: ignore[arg-type]
            rationale_summary=decision.rationale_summary,
        )
        packet = OptimizeHandler(
            self.kernel.repository,
            calibration_service=self.kernel.calibration,
            candidate_service=self.kernel.candidates,
            calibration_snapshot_id=cal_id,
            validation_snapshot_id=dev_id,
            policy=POLICY,
        ).execute(task_id, patched)
        candidate_id = str(packet.gates.get("candidate_scheme_id") or "")
        experiment_id = f"{packet.action_run_id}:{candidate_id}:{dev.start}:{dev.end}"
        gates = {
            **dict(packet.gates),
            "calibration_phase": phase.value,
            "experiment_id": experiment_id,
            "objective": objective,
        }
        observations = tuple(packet.observations) + (
            f"calibration_phase={phase.value}",
            f"phase_objective={objective}",
            f"experiment_id={experiment_id}",
            f"calibration_window={cal.start}..{cal.end}",
            f"development_window={dev.start}..{dev.end}",
            "final_holdout_visible=false",
        )
        return packet.model_copy(update={"gates": gates, "observations": observations})


class HydrologicGateHandler:
    def __init__(self, kernel: "CalibrationWorkbenchKernel"):
        self.kernel = kernel

    @staticmethod
    def _forcing_warning(evidence) -> bool:
        for row in reversed(evidence):
            if row.action != ActionCode.A06_DIAGNOSE.value:
                continue
            try:
                return float((row.metrics_json or {}).get("forcing_adequacy_warning", 0.0)) >= 0.5
            except (TypeError, ValueError):
                return False
        return False

    @staticmethod
    def _history(evidence, phase: CalibrationPhase) -> tuple[SearchProgressPoint, ...]:
        points: list[SearchProgressPoint] = []
        seen: set[str] = set()
        for row in evidence:
            if row.action != ActionCode.A08_GATE.value:
                continue
            gates = dict(row.gates_json or {})
            if gates.get("calibration_phase") != phase.value:
                continue
            experiment_id = str(gates.get("experiment_id") or "")
            if not experiment_id or experiment_id in seen:
                continue
            seen.add(experiment_id)
            metrics = dict(row.metrics_json or {})
            if "phase_progress_value" not in metrics:
                continue
            points.append(
                SearchProgressPoint(
                    experiment_id=experiment_id,
                    phase=phase,
                    value=float(metrics["phase_progress_value"]),
                    higher_is_better=str(gates.get("higher_is_better") or "true").lower() == "true",
                )
            )
        return tuple(points)

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        del decision
        repo = self.kernel.repository
        evidence = repo.list_evidence(task_id)
        phase = self.kernel.protocol.phase_from_evidence(evidence)
        plan = self.kernel.evaluator.plan_for(task_id)
        dev = plan.development
        state = repo.get_task_state(task_id)

        if phase == CalibrationPhase.DEVELOPMENT_VALIDATION:
            scheme_id = state.current_scheme_id
            hydro, signatures = self.kernel.evaluator.evaluate_scheme(scheme_id, dev)
            gbt = run_gbt_accuracy(
                hydro,
                self.kernel.skills.gbt_accuracy_config(
                    area_km2=float(self.kernel.source.basin.get("area_km2") or 0.0)
                ),
            )
            experiment_id = f"development-validation:{scheme_id}:{dev.start}:{dev.end}"
            assessment = self.kernel.phase_gate.evaluate(
                phase=phase,
                base_scheme_id=scheme_id,
                candidate_scheme_id=scheme_id,
                experiment_id=experiment_id,
                base_metrics=signatures.metrics,
                candidate_metrics=signatures.metrics,
                development_grade_ok=gbt.meets_min_grade,
            )
            status = assessment.status
            base_id = candidate_id = scheme_id
            convergence = None
        else:
            optimize = next(
                (row for row in reversed(evidence) if row.action == ActionCode.A07_OPTIMIZE.value),
                None,
            )
            if optimize is None:
                raise RuntimeError("phase Gate requires a fresh optimization experiment")
            optimize_gates = dict(optimize.gates_json or {})
            experiment_id = str(optimize_gates.get("experiment_id") or "")
            if not experiment_id:
                action_run = getattr(optimize, "action_run_id", None) or optimize.evidence_id
                candidate_hint = str(optimize_gates.get("candidate_scheme_id") or "")
                experiment_id = f"{action_run}:{candidate_hint}:{dev.start}:{dev.end}"
            if experiment_id in {
                str((row.gates_json or {}).get("experiment_id") or "")
                for row in evidence
                if row.action == ActionCode.A08_GATE.value
            }:
                raise RuntimeError(f"duplicate Gate for calibration experiment {experiment_id}")
            base_id = str(optimize_gates.get("base_scheme_id") or state.current_scheme_id)
            candidate_id = str(optimize_gates.get("candidate_scheme_id") or "")
            if not candidate_id:
                raise RuntimeError("optimization evidence missing candidate_scheme_id")
            base_hydro, base_signatures = self.kernel.evaluator.evaluate_scheme(base_id, dev)
            candidate_hydro, candidate_signatures = self.kernel.evaluator.evaluate_scheme(candidate_id, dev)
            gbt = run_gbt_accuracy(
                candidate_hydro,
                self.kernel.skills.gbt_accuracy_config(
                    area_km2=float(self.kernel.source.basin.get("area_km2") or 0.0)
                ),
            )
            assessment = self.kernel.phase_gate.evaluate(
                phase=phase,
                base_scheme_id=base_id,
                candidate_scheme_id=candidate_id,
                experiment_id=experiment_id,
                base_metrics=base_signatures.metrics,
                candidate_metrics=candidate_signatures.metrics,
                development_grade_ok=gbt.meets_min_grade,
            )
            point = SearchProgressPoint(
                experiment_id=experiment_id,
                phase=phase,
                value=assessment.progress_value,
                higher_is_better=assessment.higher_is_better,
            )
            convergence = self.kernel.convergence.evaluate(self._history(evidence, phase), point)
            status = assessment.status
            if convergence.duplicate:
                raise RuntimeError(f"duplicate convergence point {experiment_id}")
            if convergence.plateau and status != PhaseGateStatus.PHASE_PASS:
                status = (
                    PhaseGateStatus.FORCING_LIMIT
                    if self._forcing_warning(evidence)
                    else PhaseGateStatus.PLATEAU_FAIL
                )
            signatures = candidate_signatures

        metrics = {
            **{f"candidate_{k}": float(v) for k, v in signatures.metrics.items()},
            **{str(k): float(v) for k, v in assessment.metrics.items()},
            "phase_progress_value": float(assessment.progress_value),
            **gbt.as_metrics_dict(),
        }
        if phase != CalibrationPhase.DEVELOPMENT_VALIDATION:
            metrics.update({f"base_{k}": float(v) for k, v in base_signatures.metrics.items()})
        if convergence is not None:
            metrics["convergence_unique_points"] = float(convergence.unique_points)
            if convergence.gain is not None:
                metrics["convergence_gain"] = float(convergence.gain)
            if convergence.slope is not None:
                metrics["convergence_slope"] = float(convergence.slope)
            if convergence.span is not None:
                metrics["convergence_span"] = float(convergence.span)

        advance = status in {PhaseGateStatus.PHASE_PASS, PhaseGateStatus.PLATEAU_PASS}
        terminal_limit = status in {
            PhaseGateStatus.PLATEAU_FAIL,
            PhaseGateStatus.DATA_LIMIT,
            PhaseGateStatus.FORCING_LIMIT,
            PhaseGateStatus.STRUCTURAL_LIMIT,
            PhaseGateStatus.HARD_BUDGET,
        }
        adopt = assessment.adopt_candidate and phase != CalibrationPhase.DEVELOPMENT_VALIDATION
        reasons = list(assessment.reasons)
        if convergence is not None:
            reasons.append(convergence.reason)
        observations = (
            f"calibration_phase={phase.value}",
            f"gate_status={status.value}",
            f"experiment_id={experiment_id}",
            f"progress_metric={assessment.progress_metric}",
            f"progress_value={assessment.progress_value:.6f}",
            f"adopt_candidate={adopt}",
            f"advance_phase={advance}",
            f"scheme_grade={gbt.scheme_grade}",
            *tuple(dict.fromkeys(reasons)),
        )
        gates = {
            "status": status.value,
            "calibration_phase": phase.value,
            "experiment_id": experiment_id,
            "base_scheme_id": base_id,
            "candidate_scheme_id": candidate_id,
            "adopt_candidate": "true" if adopt else "false",
            "advance_phase": "true" if advance else "false",
            "stop_search": "true" if terminal_limit or advance else "false",
            "higher_is_better": "true" if assessment.higher_is_better else "false",
            "progress_metric": assessment.progress_metric,
            "reasons": ",".join(dict.fromkeys(reasons)),
            "scheme_grade": gbt.scheme_grade,
            "gbt_report_json": json.dumps(gbt.model_dump(), ensure_ascii=False, sort_keys=True),
        }
        return EvidencePacket(
            evidence_id=f"ev-gate-{len(evidence)+1}",
            task_id=task_id,
            action=ActionCode.A08_GATE,
            status=status.value,  # type: ignore[arg-type]
            observations=observations,
            metrics=metrics,
            gates=gates,
            new_information_hash=information_hash(
                action=ActionCode.A08_GATE,
                status=status.value,
                observations=observations,
                metrics=metrics,
            ),
        )


class ProtocolResolveHandler:
    def __init__(self, repository):
        self.repository = repository

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        del decision
        evidence = self.repository.list_evidence(task_id)
        gate = next((row for row in reversed(evidence) if row.action == ActionCode.A08_GATE.value), None)
        if gate is None:
            raise RuntimeError("resolve requires phase Gate evidence")
        gates = dict(gate.gates_json or {})
        status = str(gates.get("status") or gate.status)
        adopt = str(gates.get("adopt_candidate") or "false").lower() == "true"
        candidate_id = str(gates.get("candidate_scheme_id") or "")
        if adopt and candidate_id:
            self.repository.update_task_state(task_id, current_scheme_id=candidate_id)
        observations = (
            f"resolve_status={status}",
            f"calibration_phase={gates.get('calibration_phase')}",
            f"adopt_candidate={adopt}",
            f"current_scheme_id={self.repository.get_task_state(task_id).current_scheme_id}",
        )
        return EvidencePacket(
            evidence_id=f"ev-resolve-{len(evidence)+1}",
            task_id=task_id,
            action=ActionCode.A09_RESOLVE,
            status=status,  # type: ignore[arg-type]
            observations=observations,
            metrics={},
            gates={
                "status": status,
                "calibration_phase": str(gates.get("calibration_phase") or ""),
                "experiment_id": str(gates.get("experiment_id") or ""),
                "adopt_candidate": "true" if adopt else "false",
                "advance_phase": str(gates.get("advance_phase") or "false"),
            },
            new_information_hash=information_hash(
                action=ActionCode.A09_RESOLVE,
                status=status,
                observations=observations,
                metrics={},
            ),
        )


class CalibrationWorkbenchKernel(RealWorkbenchKernel):
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
        tools.register(ActionCode.A06_DIAGNOSE, DiagnoseHandler(self.repository, diagnose_fn=self._diagnose_phase))
        tools.register(ActionCode.A07_OPTIMIZE, PhaseOptimizeHandler(self))
        tools.register(ActionCode.A08_GATE, HydrologicGateHandler(self))
        tools.register(ActionCode.A09_RESOLVE, ProtocolResolveHandler(self.repository))
        tools.register(ActionCode.A10_FREEZE, FreezeToolHandler(self.repository, freeze_service=self.freeze_service))
        tools.register(ActionCode.A11_REPLAY, _CalibrationReplayHandler(self))
        tools.register(ActionCode.A12_EVALUATE_REPORT, _CalibrationEvaluateHandler(self))
        return tools

    def _diagnose_phase(self, task_id: str) -> dict:
        evidence = self.repository.list_evidence(task_id)
        phase = self.protocol.phase_from_evidence(evidence)
        state = self.repository.get_task_state(task_id)
        plan = self.evaluator.plan_for(task_id)
        window = plan.development if phase == CalibrationPhase.DEVELOPMENT_VALIDATION else plan.calibration
        hydro, signatures = self.evaluator.evaluate_scheme(state.current_scheme_id, window)
        metrics = dict(signatures.metrics)

        forcing_warning = 0.0
        runoff_ratio = metrics.get("observed_runoff_ratio")
        if runoff_ratio is not None and runoff_ratio > 1.20:
            forcing_warning = 1.0
        metrics["forcing_adequacy_warning"] = forcing_warning

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
            groups = ("runoff", "routing")
            objective = "recession"
        elif phase == CalibrationPhase.ROUTING_EVENT:
            phenomenon = (
                f"事件洪峰中位误差={metrics['event_peak_rel_error_median']:.3f}; "
                f"峰现={metrics['event_peak_timing_steps_median']:.2f}步; "
                f"洪量={metrics['event_volume_rel_error_median']:.3f}"
            )
            groups = ("runoff", "routing")
            objective = "routing_event"
        elif phase == CalibrationPhase.JOINT_REFINE:
            phenomenon = f"整体NSE={metrics['nse']:.3f}; KGE={metrics['kge']:.3f}，在既有水文约束内收口"
            groups = ("evap", "runoff", "routing")
            objective = "joint"
        else:
            phenomenon = f"开发验证 NSE={metrics['nse']:.3f}; KGE={metrics['kge']:.3f}"
            groups = ()
            objective = "joint"

        hypothesis = "FORCING" if forcing_warning else "MODEL"
        return {
            "hypothesis": hypothesis,
            "phenomenon": phenomenon,
            "recommended_action": "A08_GATE" if phase == CalibrationPhase.DEVELOPMENT_VALIDATION else "A07_OPTIMIZE",
            "recommended_strategy_id": "xaj-local-refine-v1",
            "recommended_param_groups": groups,
            "recommended_objective": objective,
            "metrics": metrics,
            "hypotheses": [
                {
                    "id": hypothesis,
                    "strength": 0.75 if forcing_warning else 0.70,
                    "suggested_action": "A08_GATE" if phase == CalibrationPhase.DEVELOPMENT_VALIDATION else "A07_OPTIMIZE",
                    "suggested_strategy_id": "xaj-local-refine-v1",
                }
            ],
            "notes": [
                f"calibration_phase={phase.value}",
                f"signature_window={window.start}..{window.end}",
                f"flood_event_count={len(signatures.events)}",
                "diagnosis_uses_continuous_hydrologic_signatures=true",
            ],
        }


class HydrologistProtocolDecisionProvider:
    """Own protocol mechanics while delegating scientific experiment choice to the LLM."""

    _TERMINAL_LIMITS = {
        "PLATEAU_FAIL",
        "DATA_LIMIT",
        "FORCING_LIMIT",
        "STRUCTURAL_LIMIT",
        "HARD_BUDGET",
    }

    _PHASE_DEFAULTS = {
        "P2_WATER_BALANCE": (("evap", "runoff"), "water_balance"),
        "P3_SOURCE_RECESSION": (("runoff", "routing"), "recession"),
        "P4_ROUTING_EVENT": (("runoff", "routing"), "routing_event"),
        "P5_JOINT_REFINE": (("evap", "runoff", "routing"), "joint"),
    }

    def __init__(self, delegate):
        self.delegate = delegate

    @staticmethod
    def _decision(action: ActionCode, rationale: str, hypothesis=ProblemHypothesis.MODEL):
        return AgentDecision(action=action, hypothesis=hypothesis, rationale_summary=rationale)

    def decide(self, view):
        evidence = list(view.evidence_summary)
        actions = [item.action.value for item in evidence]
        safe = {a.value for a in view.permissions.safe_actions}
        latest = evidence[-1] if evidence else None

        if view.task.phase == "F" and ActionCode.A11_REPLAY.value in safe:
            return self._decision(ActionCode.A11_REPLAY, "方案已冻结，只在最终独立holdout回放。")
        if view.task.phase == "E" and ActionCode.A12_EVALUATE_REPORT.value in safe:
            return self._decision(ActionCode.A12_EVALUATE_REPORT, "读取最终holdout并形成一次性终评。")

        if ActionCode.A01_CHECK_DATA.value not in actions and ActionCode.A01_CHECK_DATA.value in safe:
            return self._decision(ActionCode.A01_CHECK_DATA, "先验证资料与任务可用性。", ProblemHypothesis.DATA)
        if ActionCode.A03_VALIDATE_SCHEME.value not in actions and ActionCode.A03_VALIDATE_SCHEME.value in safe:
            return self._decision(ActionCode.A03_VALIDATE_SCHEME, "确认XAJ参数初值和方案合法。")
        if ActionCode.A05_FORECAST.value not in actions and ActionCode.A05_FORECAST.value in safe:
            return self._decision(ActionCode.A05_FORECAST, "建立初始过程证据。")
        if ActionCode.A06_DIAGNOSE.value not in actions and ActionCode.A06_DIAGNOSE.value in safe:
            return self._decision(ActionCode.A06_DIAGNOSE, "按当前水文阶段提取连续signature并诊断。")

        phase = str(view.hydro.calibration_phase)
        if phase == CalibrationPhase.DEVELOPMENT_VALIDATION.value:
            latest_phase_gate = next(
                (
                    item
                    for item in reversed(evidence)
                    if item.action == ActionCode.A08_GATE
                    and item.gates.get("calibration_phase") == phase
                ),
                None,
            )
            if latest_phase_gate is None and ActionCode.A08_GATE.value in safe:
                return self._decision(ActionCode.A08_GATE, "P6只做独立开发验证，不再生成新参数候选。")
            if latest_phase_gate is not None and ActionCode.A10_FREEZE.value in safe:
                hypothesis = (
                    ProblemHypothesis.FORCING
                    if latest_phase_gate.status == "FORCING_LIMIT"
                    else ProblemHypothesis.MODEL
                )
                return self._decision(ActionCode.A10_FREEZE, f"P6结束({latest_phase_gate.status})，冻结当前best并进入最终holdout。", hypothesis)

        if latest is not None and latest.action == ActionCode.A07_OPTIMIZE and ActionCode.A08_GATE.value in safe:
            return self._decision(ActionCode.A08_GATE, "新unique experiment已生成，运行当前HydrologicPhaseGate。")
        if latest is not None and latest.action == ActionCode.A08_GATE and ActionCode.A09_RESOLVE.value in safe:
            return self._decision(ActionCode.A09_RESOLVE, f"落实阶段Gate={latest.status}的采用/回滚/阶段切换。")
        if latest is not None and latest.action == ActionCode.A09_RESOLVE:
            status = str(latest.gates.get("status") or latest.status)
            if status in self._TERMINAL_LIMITS and ActionCode.A10_FREEZE.value in safe:
                hypothesis = ProblemHypothesis.FORCING if status == "FORCING_LIMIT" else ProblemHypothesis.MODEL
                return self._decision(ActionCode.A10_FREEZE, f"率定以{status}结束，冻结best用于透明的最终holdout评估。", hypothesis)
            if ActionCode.A06_DIAGNOSE.value in safe:
                return self._decision(ActionCode.A06_DIAGNOSE, f"上一实验={status}，按新的{phase}重新提取signature再决定下一实验。")

        if latest is not None and latest.action == ActionCode.A06_DIAGNOSE:
            if view.budget.optimization_cycles_remaining <= 0 and ActionCode.A10_FREEZE.value in safe:
                return self._decision(ActionCode.A10_FREEZE, "优化hard ceiling已到，冻结当前best并保留HARD_BUDGET证据。", ProblemHypothesis.RESOURCE)
            delegated = self.delegate.decide(view)
            if delegated.action != ActionCode.A07_OPTIMIZE:
                if delegated.hypothesis in {ProblemHypothesis.DATA, ProblemHypothesis.FORCING} and delegated.action == ActionCode.A10_FREEZE:
                    return delegated
                delegated = AgentDecision(
                    action=ActionCode.A07_OPTIMIZE,
                    hypothesis=delegated.hypothesis,
                    strategy_id=delegated.strategy_id or "xaj-local-refine-v1",
                    param_groups=None,
                    objective=None,
                    rationale_summary=f"{delegated.rationale_summary}；按当前phase执行最小范围率定实验。",
                )
            groups, objective = self._PHASE_DEFAULTS.get(
                phase,
                (("evap", "runoff", "routing"), "joint"),
            )
            selected = tuple(g for g in (delegated.param_groups or groups) if g in set(groups)) or groups
            return delegated.model_copy(
                update={
                    "param_groups": selected,
                    "objective": objective,
                    "strategy_id": delegated.strategy_id or "xaj-local-refine-v1",
                }
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
        # Final holdout is read once after Freeze. Add hydrologic signatures for research audit.
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
