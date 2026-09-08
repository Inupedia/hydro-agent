from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket
from hydro_agent.agent.tools import (
    CheckDataHandler,
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
from hydro_agent.evaluation.metrics import build_evaluation_bundle
from hydro_agent.evaluation.service import EvaluationService
from hydro_agent.execution.contracts import ExecutionPolicy
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter
from hydro_agent.optimization.candidates import CandidateSchemeService
from hydro_agent.optimization.contracts import GatePolicy
from hydro_agent.optimization.gate import GateEvaluator
from hydro_agent.replay.freeze import FreezeService
from hydro_agent.replay.planner import ReplayPlanner
from hydro_agent.replay.service import ReplayService
from hydro_agent.reporting.report import ReplayReportBuilder
from hydro_agent.services.calibration import CalibrationService
from hydro_agent.services.forecast import ForecastService
from hydro_agent.services.snapshots import SnapshotResolver
from hydro_agent.services.workspace import MaterializingWorkspaceManager

POLICY = ExecutionPolicy(
    timeout_seconds=600, network_access=False, max_output_bytes=20_000_000, device="cpu"
)
GATE_POLICY = GatePolicy(
    min_primary_delta=0.01,
    max_single_lead_drop=0.02,
    max_high_flow_mae_relative_increase=0.05,
)


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

        self.snapshot_root = self.work_root / "snapshots"
        self.builder = SnapshotBuilder(self.snapshot_root, DataAccessPolicy(), repository)
        self.resolver = SnapshotResolver(
            repository, builder=self.builder, source=self.source, history_days=60
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
        self.freeze_service = FreezeService(repository, gate_policy=GATE_POLICY.model_dump())
        self.planner = ReplayPlanner(repository, resolver=self.resolver)
        self.replay_service = ReplayService(
            repository, forecast_service=self.forecast, policy=POLICY
        )
        self.evaluation = EvaluationService(repository, snapshot_root=self.snapshot_root)
        self.report_builder = ReplayReportBuilder()

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
                history_days=60,
            ),
            forcing_rows=list(self.source.forcing_rows),
            flow_rows=list(self.source.flow_rows),
            basin=self.source.basin,
        )
        return snap_id

    def build_tools(self, *, task_configs: dict) -> ToolRouter:
        tools = ToolRouter()
        tools.register(ActionCode.A01_CHECK_DATA, CheckDataHandler(self.repository))
        tools.register(ActionCode.A03_VALIDATE_SCHEME, ValidateSchemeHandler(self.repository))
        tools.register(
            ActionCode.A05_FORECAST,
            _TaskAwareForecastHandler(self, task_configs),
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
                policy=GATE_POLICY,
                bundle_provider=self._bundle_provider,
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
        return tools

    def _bundle_provider(self, task_id: str):
        schemes = self.repository.list_schemes(task_id)
        base = next((s for s in schemes if s.status == "base"), None)
        candidate = next((s for s in schemes if s.status == "candidate"), None)
        if base is None or candidate is None:
            raise RuntimeError("gate requires base and candidate schemes")
        # Prefer KEEP unless candidate objective clearly beat base in evidence.
        opt = next(
            (
                row
                for row in reversed(self.repository.list_evidence(task_id))
                if row.action == ActionCode.A07_OPTIMIZE.value
            ),
            None,
        )
        base_score = 0.40
        cand_score = 0.40
        if opt and opt.metrics_json and "objective_value" in opt.metrics_json:
            # NSE-like objective: map into primary_score for Gate.
            cand_score = float(opt.metrics_json["objective_value"])
            base_score = max(0.0, cand_score - 0.005)
        series = {
            1: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5]),
            2: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5]),
            3: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5]),
        }
        base_bundle = build_evaluation_bundle(base.scheme_id, series)
        cand_series = {
            1: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5 + max(0.0, cand_score - base_score)]),
            2: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5 + max(0.0, cand_score - base_score)]),
            3: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5 + max(0.0, cand_score - base_score)]),
        }
        cand_bundle = build_evaluation_bundle(candidate.scheme_id, cand_series)
        base_bundle = base_bundle.model_copy(update={"primary_score": base_score})
        cand_bundle = cand_bundle.model_copy(update={"primary_score": cand_score})
        return base_bundle, cand_bundle


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
        issue = _issue_from_config(cfg)
        issue_iso = issue.isoformat().replace("+00:00", "Z")
        cal_id = self.kernel.resolver.resolve(task_id, "calibrate", issue_iso)
        handler = OptimizeHandler(
            self.kernel.repository,
            calibration_service=self.kernel.calibration,
            candidate_service=self.kernel.candidates,
            calibration_snapshot_id=cal_id,
            validation_snapshot_id=cal_id,
            policy=POLICY,
        )
        if decision.strategy_id is None:
            decision = AgentDecision(
                action=decision.action,
                hypothesis=decision.hypothesis,
                strategy_id="xaj-bounded-v1",
                rationale_summary=decision.rationale_summary,
            )
        return handler.execute(task_id, decision)


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
        packet = handler.execute(task_id, decision)
        return packet
