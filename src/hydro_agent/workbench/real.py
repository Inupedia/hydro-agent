from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket
from hydro_agent.agent.research_closeout import ResearchFreezeToolHandler
from hydro_agent.agent.tools import (
    CheckDataHandler,
    DiagnoseHandler,
    EvaluateReportToolHandler,
    ForecastHandler,
    GateHandler,
    OptimizeHandler,
    ReplayToolHandler,
    ResolveHandler,
    ToolRouter,
    ValidateSchemeHandler,
)
from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.evaluation.service import EvaluationService
from hydro_agent.execution.contracts import ExecutionPolicy
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.registry import ModelRegistry, default_model_registry
from hydro_agent.optimization.candidates import CandidateSchemeService
from hydro_agent.optimization.contracts import GatePolicy
from hydro_agent.optimization.gate import GateEvaluator
from hydro_agent.replay.freeze import FreezeService
from hydro_agent.replay.planner import ReplayPlanner
from hydro_agent.replay.service import ReplayService
from hydro_agent.reporting.report import ReplayReportBuilder
from hydro_agent.services.calibration import CalibrationService
from hydro_agent.services.calibration_diagnostics import diagnose_prevalidation_window
from hydro_agent.services.calibration_evidence import (
    apply_calibration_evidence_to_diagnosis,
    build_calibration_evidence,
)
from hydro_agent.services.calibration_feedback import apply_latest_gate_feedback
from hydro_agent.services.forecast import ForecastService
from hydro_agent.services.snapshots import SnapshotResolver
from hydro_agent.services.workspace import MaterializingWorkspaceManager
from hydro_agent.skills import SkillRegistry
from hydro_agent.standards import StandardRepository
from hydro_agent.workbench.validation_gate import RealValidationGate

POLICY = ExecutionPolicy(
    timeout_seconds=600, network_access=False, max_output_bytes=20_000_000, device="cpu"
)


def gate_policy_from_standards(standards: StandardRepository | None = None) -> GatePolicy:
    repository = standards or StandardRepository()
    grade = repository.min_scheme_grade()
    return GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        min_candidate_primary=0.0,
        accept_primary_floor=repository.grade_dc_bing(),
        min_scheme_grade=grade,  # type: ignore[arg-type]
        require_gbt_grade=True,
    )


GATE_POLICY = gate_policy_from_standards()


class RealWorkbenchKernel:
    """Shared real multi-model workbench stack (plugins + evaluation)."""

    def __init__(
        self,
        *,
        repository,
        work_root: Path,
        source_dir: Path,
        scheme_path: Path,
        report_root: Path,
        warmup_days: int = 30,
        model_registry: ModelRegistry | None = None,
    ):
        self.repository = repository
        self.work_root = Path(work_root)
        self.report_root = Path(report_root)
        self.models = model_registry or default_model_registry()
        self.source = load_normalized_source(source_dir)
        self.scheme_template = json.loads(Path(scheme_path).read_text(encoding="utf-8"))
        self.scheme_template["warmup_days"] = warmup_days
        self.scheme_template.setdefault("model_id", "xaj")
        self.skills = SkillRegistry(repository=repository)
        self.standards = self.skills.standards
        self.strategies = self.models.strategy_registry()
        self.gate_policy = gate_policy_from_standards(self.standards)
        self._task_configs: dict = {}

        self.snapshot_root = self.work_root / "snapshots"
        self.builder = SnapshotBuilder(self.snapshot_root, DataAccessPolicy(), repository)
        self.resolver = SnapshotResolver(
            repository,
            builder=self.builder,
            source=self.source,
            history_days=max(60, warmup_days + 60),
        )
        workspaces = MaterializingWorkspaceManager(
            self.work_root / "runs", repository, snapshot_root=self.snapshot_root
        )
        runner = SandboxRunner(self.models.runtime_registry(), workspaces)
        self.forecast = ForecastService(repository, resolver=self.resolver, runner=runner)
        self.calibration = CalibrationService(
            repository, runner=runner, strategies=self.strategies
        )
        self.candidates = CandidateSchemeService(repository)
        self.gate = GateEvaluator()
        self.freeze_service = FreezeService(repository, gate_policy=self.gate_policy.model_dump())
        self.planner = ReplayPlanner(repository, resolver=self.resolver)
        self.replay_service = ReplayService(
            repository, forecast_service=self.forecast, policy=POLICY
        )
        self.evaluation = EvaluationService(repository, snapshot_root=self.snapshot_root)
        self.report_builder = ReplayReportBuilder()
        self.validation_gate = RealValidationGate(
            repository=repository,
            forecast_service=self.forecast,
            source=self.source,
            policy=POLICY,
            task_configs=self._task_configs,
        )

    def scheme_config(self) -> dict:
        return json.loads(json.dumps(self.scheme_template))

    def _default_strategy_id(self, task_id: str) -> str:
        state = self.repository.ensure_task_state(task_id)
        model_id = str(self.scheme_template.get("model_id") or "xaj")
        if state.current_scheme_id:
            try:
                model_id = str(self.repository.get_scheme(state.current_scheme_id).model_id)
            except KeyError:
                pass
        try:
            return self.models.default_strategy_id(model_id)
        except KeyError:
            return "xaj-bounded-v1"

    def _workbench_config(self, task_id: str) -> dict:
        runtime = dict(self._task_configs.get(task_id) or {})
        if runtime:
            return runtime
        state = self.repository.ensure_task_state(task_id)
        if state.current_scheme_id:
            scheme = self.repository.get_scheme(state.current_scheme_id)
            return dict((scheme.config_json or {}).get("workbench") or {})
        return {}

    def ensure_eval_truth_snapshot(self, task_id: str, issue: datetime) -> str:
        snap_id = f"{task_id}--E--evaluate--{issue.strftime('%Y%m%dT%H%M%SZ')}"
        try:
            self.repository.get_snapshot(snap_id)
            return snap_id
        except KeyError:
            pass
        task = self.repository.get_task(task_id)
        cfg = self._workbench_config(task_id)
        final_days = int(cfg.get("final_test_days") or 0)
        history_days = int(
            cfg.get("evaluation_history_days")
            or (self.scheme_template["warmup_days"] + max(final_days, 60))
        )
        self.builder.build(
            SnapshotContext(
                task_id=task_id,
                snapshot_id=snap_id,
                basin_id=task.basin_id,
                phase="E",
                forcing_mode=task.forcing_mode,
                capability="evaluate",
                issue_time=issue,
                history_days=history_days,
                day_timezone=str(self.source.basin.get("day_timezone", "UTC")),
            ),
            forcing_rows=list(self.source.forcing_rows),
            flow_rows=list(self.source.flow_rows),
            basin=self.source.basin,
        )
        return snap_id

    def build_tools(self, *, task_configs: dict) -> ToolRouter:
        self._task_configs = task_configs
        self.validation_gate.task_configs = task_configs
        tools = ToolRouter()
        tools.register(ActionCode.A01_CHECK_DATA, CheckDataHandler(self.repository))
        tools.register(ActionCode.A02_VALIDATE_SCHEME, ValidateSchemeHandler(self.repository))
        tools.register(
            ActionCode.A03_FORECAST,
            _TaskAwareForecastHandler(self, task_configs),
        )
        tools.register(
            ActionCode.A04_DIAGNOSE,
            DiagnoseHandler(self.repository, diagnose_fn=self._diagnose),
        )
        tools.register(
            ActionCode.A05_OPTIMIZE,
            _TaskAwareOptimizeHandler(self, task_configs),
        )
        tools.register(
            ActionCode.A06_GATE,
            GateHandler(
                self.repository,
                gate_evaluator=self.gate,
                policy=self.gate_policy,
                bundle_provider=self.validation_gate.bundles,
                gbt_config_provider=lambda _task_id: self.skills.gbt_accuracy_config(),
            ),
        )
        tools.register(ActionCode.A07_RESOLVE, ResolveHandler(self.repository))
        tools.register(
            ActionCode.A08_FREEZE,
            ResearchFreezeToolHandler(self.repository, freeze_service=self.freeze_service),
        )
        tools.register(
            ActionCode.A09_REPLAY,
            _TaskAwareReplayHandler(self, task_configs),
        )
        tools.register(
            ActionCode.A10_EVALUATE_REPORT,
            _TaskAwareEvaluateHandler(self, task_configs),
        )
        from hydro_agent.workflow.handlers import assert_tool_router

        assert_tool_router(tools)
        return tools

    def _diagnose(self, task_id: str) -> dict:
        state = self.repository.ensure_task_state(task_id)
        scheme_id = state.current_scheme_id
        if not scheme_id:
            return {
                "hypothesis": "DATA",
                "phenomenon": "尚无当前方案，无法诊断",
                "recommended_action": "A02_VALIDATE_SCHEME",
                "recommended_strategy_id": None,
                "metrics": {},
                "notes": ["no current scheme"],
            }
        window = self.validation_gate.window_for(task_id)
        scoring_source = replace(
            self.source,
            flow_rows=tuple(row for row in self.source.flow_rows if row.eligible_for_scoring),
        )
        model_id = "xaj"
        get_scheme = getattr(self.repository, "get_scheme", None)
        if callable(get_scheme):
            try:
                model_id = str(get_scheme(scheme_id).model_id or "xaj")
            except (KeyError, AttributeError, TypeError):
                model_id = str(getattr(self, "scheme_template", {}).get("model_id") or "xaj")
        elif getattr(self, "scheme_template", None):
            model_id = str(self.scheme_template.get("model_id") or "xaj")
        result = diagnose_prevalidation_window(
            repository=self.repository,
            forecast_service=self.forecast,
            source=scoring_source,
            policy=POLICY,
            task_id=task_id,
            scheme_id=scheme_id,
            validation_start=window.start,
            model_id=model_id,
        )

        cfg = self._workbench_config(task_id)
        raw_cal_start = cfg.get("calibration_start_date")
        raw_cal_end = cfg.get("calibration_end_date")
        if raw_cal_start and raw_cal_end:
            cal_start = date.fromisoformat(str(raw_cal_start)[:10])
            cal_end = date.fromisoformat(str(raw_cal_end)[:10])
            scheme = self.repository.get_scheme(scheme_id)
            try:
                full_evidence = build_calibration_evidence(
                    source=self.source,
                    scheme_config=dict(scheme.config_json or {}),
                    calibration_start=cal_start,
                    calibration_end=cal_end,
                )
                result = apply_calibration_evidence_to_diagnosis(
                    result,
                    full_evidence,
                    dc_bing_floor=self.standards.grade_dc_bing(),
                )
            except (KeyError, ValueError) as exc:
                notes = list(result.get("notes") or [])
                notes.append(f"continuous_calibration_evidence_unavailable={exc}")
                result["notes"] = notes

        result = apply_latest_gate_feedback(
            result,
            self.repository.list_evidence(task_id),
        )
        notes = list(result.get("notes") or [])
        notes.insert(0, f"scheme_id={scheme_id}")
        notes.insert(
            1,
            f"held_out_development_window={window.start.isoformat()}..{window.end.isoformat()}",
        )
        feedback = result.get("gate_feedback")
        if isinstance(feedback, dict):
            notes.insert(
                2,
                "gate_feedback="
                + str(feedback.get("status") or "unknown")
                + ":"
                + ",".join(str(item) for item in feedback.get("reasons") or []),
            )
        result["notes"] = notes
        return result


def _issue_from_config(cfg: dict) -> datetime:
    end = cfg.get("end_date") or "2020-05-01"
    day = date.fromisoformat(end[:10]) if isinstance(end, str) else end
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _dates_from_config(cfg: dict) -> tuple[date, date]:
    start = cfg.get("start_date") or "2020-04-29"
    end = cfg.get("end_date") or "2020-05-01"
    start_d = date.fromisoformat(start[:10]) if isinstance(start, str) else start
    end_d = date.fromisoformat(end[:10]) if isinstance(end, str) else end
    return start_d, end_d


def _final_test_dates_from_config(cfg: dict) -> tuple[date, date]:
    start = cfg.get("final_test_start_date") or cfg.get("start_date") or "2020-04-29"
    end = cfg.get("final_test_end_date") or cfg.get("end_date") or "2020-05-01"
    start_d = date.fromisoformat(start[:10]) if isinstance(start, str) else start
    end_d = date.fromisoformat(end[:10]) if isinstance(end, str) else end
    return start_d, end_d


def _final_test_issue_from_config(cfg: dict) -> datetime:
    _start, end = _final_test_dates_from_config(cfg)
    return datetime(end.year, end.month, end.day, tzinfo=timezone.utc)


class _TaskAwareForecastHandler:
    def __init__(self, kernel: RealWorkbenchKernel, task_configs: dict):
        self.kernel = kernel
        self.task_configs = task_configs

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        cfg = self.task_configs.get(task_id) or {}
        issue = _issue_from_config(cfg).isoformat().replace("+00:00", "Z")
        handler = ForecastHandler(
            self.kernel.repository,
            forecast_service=self.kernel.forecast,
            issue_time=issue,
            policy=POLICY,
        )
        return handler.execute(task_id, decision)


class _TaskAwareOptimizeHandler:
    def __init__(self, kernel: RealWorkbenchKernel, task_configs: dict):
        self.kernel = kernel
        self.task_configs = task_configs

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        window = self.kernel.validation_gate.window_for(task_id)
        cfg = self.kernel._workbench_config(task_id)
        cal_day = date.fromisoformat(
            str(cfg.get("calibration_end_date") or window.calibration_issue)[:10]
        )
        if cal_day >= window.start:
            raise ValueError("calibration must end before development starts")
        # The final daily observation becomes available at the next midnight.
        # Keep the history anchored to calibration end, not the access timestamp.
        cal_issue = datetime.combine(
            cal_day + timedelta(days=1),
            time.min,
            ZoneInfo(str(self.kernel.source.basin.get("day_timezone", "UTC"))),
        )
        # Retrospective observations can be published after local midnight.
        # Availability time is independent of the immutable scoring window;
        # advancing it must not extend that window into development.
        cal_start = date.fromisoformat(str(cfg.get("calibration_start_date") or cal_day)[:10])
        cal_issue = max(
            [cal_issue]
            + [
                row.available_at
                for row in self.kernel.source.flow_rows
                if cal_start <= row.valid_date <= cal_day and row.eligible_for_scoring
            ]
        )
        cal_iso = cal_issue.isoformat().replace("+00:00", "Z")
        cal_id = self.kernel.resolver.resolve(
            task_id,
            "calibrate",
            cal_iso,
            history_end_date=cal_day,
        )
        strategy_id = decision.strategy_id
        param_groups = decision.param_groups
        objective = decision.objective
        if not strategy_id or not param_groups or not objective:
            for row in reversed(self.kernel.repository.list_evidence(task_id)):
                if row.action != ActionCode.A04_DIAGNOSE.value:
                    continue
                gates = row.gates_json or {}
                strategy_id = strategy_id or gates.get("recommended_strategy_id") or None
                if not param_groups:
                    raw_groups = str(gates.get("recommended_param_groups") or "").strip()
                    if raw_groups and raw_groups != "-":
                        param_groups = (
                            tuple(g.strip() for g in raw_groups.split(",") if g.strip()) or None
                        )
                objective = objective or gates.get("recommended_objective") or None
                break
        strategy_id = strategy_id or self.kernel._default_strategy_id(task_id)
        handler = OptimizeHandler(
            self.kernel.repository,
            calibration_service=self.kernel.calibration,
            candidate_service=self.kernel.candidates,
            calibration_snapshot_id=cal_id,
            validation_snapshot_id=None,
            policy=POLICY,
        )
        decision = AgentDecision(
            action=decision.action,
            hypothesis=decision.hypothesis,
            strategy_id=strategy_id,
            param_groups=param_groups,  # type: ignore[arg-type]
            objective=objective,  # type: ignore[arg-type]
            calibration_hypothesis_id=decision.calibration_hypothesis_id,
            diagnostic_signature=decision.diagnostic_signature,
            adjustment_direction=decision.adjustment_direction,
            direction_evidence_ids=decision.direction_evidence_ids,
            direction_verification_required=decision.direction_verification_required,
            rationale_summary=decision.rationale_summary,
        )
        packet = handler.execute(task_id, decision)
        self._promote_calibration_hydrograph(task_id, packet.action_run_id)
        extra = (
            f"calibration_snapshot_id={cal_id}",
            f"calibration_issue={cal_iso}",
            f"calibration_history_end={cal_day.isoformat()}",
            f"development_window={window.start.isoformat()}..{window.end.isoformat()}",
            "development_evaluated_by=A06_GATE",
            "final_test_accessed=false",
        )
        return packet.model_copy(update={"observations": tuple(packet.observations) + extra})

    def _promote_calibration_hydrograph(self, task_id: str, action_run_id: str | None) -> None:
        if not action_run_id:
            return
        src = self.kernel.calibration.runner.workspaces.root / task_id / action_run_id / "output"
        dest = self.kernel.report_root / task_id
        dest.mkdir(parents=True, exist_ok=True)
        for name in (
            "calibration-comparison.csv",
            "calibration-comparison.json",
            "calibration-comparison.png",
            "calibration-metrics.json",
        ):
            path = src / name
            if path.is_file():
                shutil.copy2(path, dest / name)


class _TaskAwareReplayHandler:
    def __init__(self, kernel: RealWorkbenchKernel, task_configs: dict):
        self.kernel = kernel
        self.task_configs = task_configs

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        cfg = self.task_configs.get(task_id) or {}
        start_d, end_d = _final_test_dates_from_config(cfg)
        handler = ReplayToolHandler(
            self.kernel.repository,
            planner=self.kernel.planner,
            replay_service=self.kernel.replay_service,
            start_date=start_d,
            end_date=end_d,
        )
        packet = handler.execute(task_id, decision)
        extra = (f"final_test_window={start_d.isoformat()}..{end_d.isoformat()}",)
        return packet.model_copy(update={"observations": tuple(packet.observations) + extra})


class _TaskAwareEvaluateHandler:
    def __init__(self, kernel: RealWorkbenchKernel, task_configs: dict):
        self.kernel = kernel
        self.task_configs = task_configs

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        previous = self.kernel.repository.list_evidence(task_id)
        if any(
            row.action == ActionCode.A10_EVALUATE_REPORT.value and row.status == "succeeded"
            for row in previous
        ):
            raise RuntimeError(
                "final_test already consumed; A10 evaluation is read-only and single-use"
            )

        cfg = self.task_configs.get(task_id) or {}
        issue = _final_test_issue_from_config(cfg)
        truth_id = self.kernel.ensure_eval_truth_snapshot(task_id, issue)
        out_dir = self.kernel.report_root / task_id
        out_dir.mkdir(parents=True, exist_ok=True)
        handler = EvaluateReportToolHandler(
            self.kernel.repository,
            evaluation_service=self.kernel.evaluation,
            report_builder=self.kernel.report_builder,
            observation_snapshot_id=truth_id,
            output_dir=out_dir,
        )
        packet = handler.execute(task_id, decision)
        start_d, end_d = _final_test_dates_from_config(cfg)
        extra = (
            f"final_test_window={start_d.isoformat()}..{end_d.isoformat()}",
            "final_test_read_only=true",
            "final_test_consumption=1/1",
        )
        return packet.model_copy(update={"observations": tuple(packet.observations) + extra})
