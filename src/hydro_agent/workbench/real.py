from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket
from hydro_agent.agent.tools import (
    CheckDataHandler,
    DiagnoseHandler,
    EvaluateReportToolHandler,
    ForecastHandler,
    FreezeToolHandler,
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
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter
from hydro_agent.optimization.candidates import CandidateSchemeService
from hydro_agent.optimization.contracts import GatePolicy
from hydro_agent.optimization.gate import GateEvaluator
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.replay.freeze import FreezeService
from hydro_agent.replay.planner import ReplayPlanner
from hydro_agent.replay.service import ReplayService
from hydro_agent.reporting.report import ReplayReportBuilder
from hydro_agent.services.calibration import CalibrationService
from hydro_agent.services.forecast import ForecastService
from hydro_agent.services.snapshots import SnapshotResolver
from hydro_agent.services.workspace import MaterializingWorkspaceManager
from hydro_agent.skills import SkillRegistry
from hydro_agent.workbench.validation_gate import (
    RealValidationGate,
    diagnose_forecast_errors,
    truth_from_source,
)

POLICY = ExecutionPolicy(
    timeout_seconds=600, network_access=False, max_output_bytes=20_000_000, device="cpu"
)


def gate_policy_from_skills(skills: SkillRegistry | None = None) -> GatePolicy:
    """Gate ACCEPT requires GB/T scheme grade from gbt-22482-accuracy skill."""
    registry = skills or SkillRegistry()
    grade = registry.min_scheme_grade()
    return GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        min_candidate_primary=0.0,
        accept_primary_floor=registry.nse_good_enough(),
        min_scheme_grade=grade,  # type: ignore[arg-type]
        require_gbt_grade=True,
    )


GATE_POLICY = gate_policy_from_skills()


class RealWorkbenchKernel:
    """Shared real XAJ + evaluation stack for the workbench API."""

    def __init__(
        self,
        *,
        repository,
        work_root: Path,
        source_dir: Path,
        scheme_path: Path,
        report_root: Path,
        warmup_days: int = 30,
    ):
        self.repository = repository
        self.work_root = Path(work_root)
        self.report_root = Path(report_root)
        self.source = load_normalized_source(source_dir)
        self.scheme_template = json.loads(Path(scheme_path).read_text(encoding="utf-8"))
        self.scheme_template["warmup_days"] = warmup_days
        self.scheme_template.setdefault("model_id", "xaj")
        self.skills = SkillRegistry()
        self.strategies = CalibrationStrategyRegistry()
        self.gate_policy = gate_policy_from_skills(self.skills)
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
        registry = RuntimeRegistry()
        registry.register(XajRuntimeAdapter())
        runner = SandboxRunner(registry, workspaces)
        self.forecast = ForecastService(
            repository, resolver=self.resolver, runner=runner, model_id="xaj"
        )
        self.calibration = CalibrationService(repository, runner=runner, model_id="xaj")
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

    def ensure_eval_truth_snapshot(self, task_id: str, issue: datetime) -> str:
        snap_id = f"{task_id}--E--evaluate--{issue.strftime('%Y%m%dT%H%M%SZ')}"
        try:
            self.repository.get_snapshot(snap_id)
            return snap_id
        except KeyError:
            pass
        task = self.repository.get_task(task_id)
        self.builder.build(
            SnapshotContext(
                task_id=task_id,
                snapshot_id=snap_id,
                basin_id=task.basin_id,
                phase="E",
                forcing_mode=task.forcing_mode,
                capability="evaluate",
                issue_time=issue,
                history_days=max(60, self.scheme_template["warmup_days"] + 60),
                day_timezone=str(self.source.basin.get("day_timezone", "UTC")),
            ),
            forcing_rows=list(self.source.forcing_rows),
            flow_rows=list(self.source.flow_rows),
            basin=self.source.basin,
        )
        return snap_id

    def build_tools(self, *, task_configs: dict) -> ToolRouter:
        # Share the live dict reference so create_task updates are visible to Gate/diagnose.
        self._task_configs = task_configs
        self.validation_gate.task_configs = task_configs
        tools = ToolRouter()
        tools.register(ActionCode.A01_CHECK_DATA, CheckDataHandler(self.repository))
        tools.register(ActionCode.A03_VALIDATE_SCHEME, ValidateSchemeHandler(self.repository))
        tools.register(
            ActionCode.A05_FORECAST,
            _TaskAwareForecastHandler(self, task_configs),
        )
        tools.register(
            ActionCode.A06_DIAGNOSE,
            DiagnoseHandler(self.repository, diagnose_fn=self._diagnose),
        )
        tools.register(
            ActionCode.A07_OPTIMIZE,
            _TaskAwareOptimizeHandler(self, task_configs),
        )
        tools.register(
            ActionCode.A08_GATE,
            GateHandler(
                self.repository,
                gate_evaluator=self.gate,
                policy=self.gate_policy,
                bundle_provider=self.validation_gate.bundles,
                gbt_config_provider=lambda _task_id: self.skills.gbt_accuracy_config(),
            ),
        )
        tools.register(ActionCode.A09_RESOLVE, ResolveHandler(self.repository))
        tools.register(
            ActionCode.A10_FREEZE,
            FreezeToolHandler(self.repository, freeze_service=self.freeze_service),
        )
        tools.register(
            ActionCode.A11_REPLAY,
            _TaskAwareReplayHandler(self, task_configs),
        )
        tools.register(
            ActionCode.A12_EVALUATE_REPORT,
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
                "recommended_action": "A03_VALIDATE_SCHEME",
                "recommended_strategy_id": None,
                "metrics": {},
                "notes": ["no current scheme"],
            }
        window = self.validation_gate.window_for(task_id)
        forecasts = [
            row
            for row in self.repository.list_forecasts(task_id)
            if row.scheme_id == scheme_id and window.start <= row.issue_time.date() <= window.end
        ]
        forecasts.sort(key=lambda row: (row.issue_time, row.forecast_id))
        if not forecasts:
            # Ensure at least the validation-end issue for the *current* scheme.
            issue = datetime(window.end.year, window.end.month, window.end.day, tzinfo=timezone.utc)
            issue_iso = issue.isoformat().replace("+00:00", "Z")
            self.forecast.forecast(
                task_id=task_id,
                scheme_id=scheme_id,
                issue_time=issue_iso,
                policy=POLICY,
            )
            forecasts = [
                row
                for row in self.repository.list_forecasts(task_id)
                if row.scheme_id == scheme_id
                and window.start <= row.issue_time.date() <= window.end
            ]
            forecasts.sort(key=lambda row: (row.issue_time, row.forecast_id))
        if not forecasts:
            return {
                "hypothesis": "DATA",
                "phenomenon": "尚无当前方案预报，无法诊断",
                "recommended_action": "A05_FORECAST",
                "recommended_strategy_id": None,
                "metrics": {},
                "notes": [f"scheme_id={scheme_id}", "no forecast"],
            }
        latest = forecasts[-1]
        leads = {int(k): float(v) for k, v in latest.lead_values_json.items()}
        result = diagnose_forecast_errors(
            truth=truth_from_source(self.source.flow_rows),
            lead_values=leads,
            issue_day=latest.issue_time.date(),
            nse_good_enough=self.skills.nse_good_enough(),
        )
        notes = list(result.get("notes") or [])
        notes.insert(0, f"scheme_id={scheme_id}")
        notes.insert(1, f"issue={latest.issue_time.date().isoformat()}")
        notes.insert(
            2,
            f"validation_window={window.start.isoformat()}..{window.end.isoformat()}",
        )
        result["notes"] = notes
        return result


def _issue_from_config(cfg: dict) -> datetime:
    end = cfg.get("end_date") or "2020-05-01"
    if isinstance(end, str):
        day = date.fromisoformat(end[:10])
    else:
        day = end
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _dates_from_config(cfg: dict) -> tuple[date, date]:
    start = cfg.get("start_date") or "2020-04-29"
    end = cfg.get("end_date") or "2020-05-01"
    if isinstance(start, str):
        start_d = date.fromisoformat(start[:10])
    else:
        start_d = start
    if isinstance(end, str):
        end_d = date.fromisoformat(end[:10])
    else:
        end_d = end
    return start_d, end_d


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
        cfg = self.task_configs.get(task_id) or {}
        window = self.kernel.validation_gate.window_for(task_id)
        cal_day = window.calibration_issue
        cal_issue = datetime(cal_day.year, cal_day.month, cal_day.day, tzinfo=timezone.utc)
        cal_iso = cal_issue.isoformat().replace("+00:00", "Z")
        # Independent validation snapshot keyed by validation end issue (held-out window).
        val_issue = _issue_from_config(cfg)
        val_iso = val_issue.isoformat().replace("+00:00", "Z")
        cal_id = self.kernel.resolver.resolve(task_id, "calibrate", cal_iso)
        val_id = self.kernel.resolver.resolve(task_id, "calibrate", val_iso)
        if cal_id == val_id and window.start <= window.end:
            # Force distinct snapshot ids when issue dates differ; resolver already does.
            pass
        strategy_id = decision.strategy_id
        param_groups = decision.param_groups
        objective = decision.objective
        if not strategy_id or not param_groups or not objective:
            for row in reversed(self.kernel.repository.list_evidence(task_id)):
                if row.action != ActionCode.A06_DIAGNOSE.value:
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
        strategy_id = strategy_id or "xaj-bounded-v1"
        handler = OptimizeHandler(
            self.kernel.repository,
            calibration_service=self.kernel.calibration,
            candidate_service=self.kernel.candidates,
            calibration_snapshot_id=cal_id,
            validation_snapshot_id=val_id,
            policy=POLICY,
        )
        decision = AgentDecision(
            action=decision.action,
            hypothesis=decision.hypothesis,
            strategy_id=strategy_id,
            param_groups=param_groups,  # type: ignore[arg-type]
            objective=objective,  # type: ignore[arg-type]
            rationale_summary=decision.rationale_summary,
        )
        packet = handler.execute(task_id, decision)
        self._promote_calibration_hydrograph(task_id, packet.action_run_id)
        # Attach calibration/validation separation into observations for the agent log.
        extra = (
            f"calibration_snapshot_id={cal_id}",
            f"validation_snapshot_id={val_id}",
            f"calibration_issue={cal_iso}",
            f"validation_window={window.start.isoformat()}..{window.end.isoformat()}",
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
        start_d, end_d = _dates_from_config(cfg)
        handler = ReplayToolHandler(
            self.kernel.repository,
            planner=self.kernel.planner,
            replay_service=self.kernel.replay_service,
            start_date=start_d,
            end_date=end_d,
        )
        return handler.execute(task_id, decision)


class _TaskAwareEvaluateHandler:
    def __init__(self, kernel: RealWorkbenchKernel, task_configs: dict):
        self.kernel = kernel
        self.task_configs = task_configs

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        cfg = self.task_configs.get(task_id) or {}
        issue = _issue_from_config(cfg)
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
        return handler.execute(task_id, decision)
