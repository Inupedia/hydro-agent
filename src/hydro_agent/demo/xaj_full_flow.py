from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from hydro_agent.agent.contracts import ActionCode, AgentDecision, ProblemHypothesis
from hydro_agent.agent.providers.scripted import ScriptedDecisionProvider
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.tools import (
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
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.data.contracts import FlowObservation, SnapshotContext
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
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.replay.freeze import FreezeService
from hydro_agent.replay.planner import ReplayPlanner
from hydro_agent.replay.service import ReplayService
from hydro_agent.reporting.report import ReplayReportBuilder
from hydro_agent.services.calibration import CalibrationService
from hydro_agent.services.forecast import ForecastService
from hydro_agent.services.snapshots import SnapshotResolver
from hydro_agent.services.workspace import MaterializingWorkspaceManager

TASK_ID = "lowman-full-001"
ISSUE = datetime(2020, 5, 1, tzinfo=timezone.utc)
ISSUE_ISO = "2020-05-01T00:00:00Z"
AVAILABLE = datetime(2019, 1, 1, tzinfo=timezone.utc)
REPLAY_START = date(2020, 4, 29)
REPLAY_END = date(2020, 5, 1)
POLICY = ExecutionPolicy(
    timeout_seconds=600, network_access=False, max_output_bytes=20_000_000, device="cpu"
)
GATE_POLICY = GatePolicy(
    min_primary_delta=0.01,
    max_single_lead_drop=0.02,
    max_high_flow_mae_relative_increase=0.05,
)


class XajFullResearchFlow:
    """Orchestrates the SP3-SP7 XAJ research claim as one auditable Task."""

    def __init__(
        self,
        output_dir: Path,
        *,
        source_dir: Path,
        scheme_path: Path,
        warmup_days: int = 30,
    ):
        self.tmp_path = Path(output_dir)
        self.source = load_normalized_source(source_dir)
        if not self.source.flow_rows:
            self.flow_rows = [
                FlowObservation(
                    valid_date=row.valid_date,
                    discharge_m3s=8.0 + (i % 11) * 0.25,
                    source="synthetic-full-flow-obs",
                    available_at=AVAILABLE,
                )
                for i, row in enumerate(self.source.forcing_rows)
            ]
        else:
            self.flow_rows = list(self.source.flow_rows)

        db = Database(f"sqlite+pysqlite:///{self.tmp_path}/hydro.db")
        db.create_schema()
        self.repository = HydroRepository(db)
        basin_id = str(self.source.basin["basin_id"])
        self.repository.create_task(task_id=TASK_ID, basin_id=basin_id, phase="B", forcing_mode="R")
        scheme = json.loads(Path(scheme_path).read_text(encoding="utf-8"))
        scheme["warmup_days"] = warmup_days
        self.repository.create_scheme(
            scheme_id="scheme-base",
            task_id=TASK_ID,
            model_id="xaj",
            status="base",
            config=scheme,
            content_hash="lowman-base-hash",
        )
        self.repository.ensure_task_state(TASK_ID, current_scheme_id="scheme-base")

        self.snapshot_root = self.tmp_path / "snapshots"
        self.builder = SnapshotBuilder(self.snapshot_root, DataAccessPolicy(), self.repository)
        self.cal_snapshot_id = "lowman-full-cal-2020-05-01"
        self.builder.build(
            SnapshotContext(
                task_id=TASK_ID,
                snapshot_id=self.cal_snapshot_id,
                basin_id=basin_id,
                phase="B",
                forcing_mode="R",
                capability="calibrate",
                issue_time=ISSUE,
                history_days=60,
            ),
            forcing_rows=list(self.source.forcing_rows),
            flow_rows=self.flow_rows,
            basin=self.source.basin,
        )
        self.resolver = SnapshotResolver(
            self.repository, builder=self.builder, source=self.source, history_days=60
        )
        workspaces = MaterializingWorkspaceManager(
            self.tmp_path / "runs", self.repository, snapshot_root=self.snapshot_root
        )
        registry = RuntimeRegistry()
        registry.register(XajRuntimeAdapter())
        runner = SandboxRunner(registry, workspaces)
        self.forecast = ForecastService(
            self.repository, resolver=self.resolver, runner=runner, model_id="xaj"
        )
        self.calibration = CalibrationService(self.repository, runner=runner, model_id="xaj")
        self.candidates = CandidateSchemeService(self.repository)
        self.gate = GateEvaluator()
        self.freeze_service = FreezeService(self.repository, gate_policy=GATE_POLICY.model_dump())
        self.planner = ReplayPlanner(self.repository, resolver=self.resolver)
        self.replay_service = ReplayService(
            self.repository, forecast_service=self.forecast, policy=POLICY
        )
        self.evaluation = EvaluationService(self.repository, snapshot_root=self.snapshot_root)
        self.report_builder = ReplayReportBuilder()
        self.report_dir = self.tmp_path / "reports"
        self._gate_bundles = None

    def _bundle_provider(self, task_id: str):
        assert self._gate_bundles is not None
        return self._gate_bundles

    def _build_agent(self) -> AgentRuntime:
        tools = ToolRouter()
        tools.register(ActionCode.A03_VALIDATE_SCHEME, ValidateSchemeHandler(self.repository))
        tools.register(
            ActionCode.A05_FORECAST,
            ForecastHandler(
                self.repository,
                forecast_service=self.forecast,
                issue_time=ISSUE_ISO,
                policy=POLICY,
            ),
        )
        tools.register(
            ActionCode.A07_OPTIMIZE,
            OptimizeHandler(
                self.repository,
                calibration_service=self.calibration,
                candidate_service=self.candidates,
                calibration_snapshot_id=self.cal_snapshot_id,
                validation_snapshot_id=self.cal_snapshot_id,
                policy=POLICY,
            ),
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
            ReplayToolHandler(
                self.repository,
                planner=self.planner,
                replay_service=self.replay_service,
                start_date=REPLAY_START,
                end_date=REPLAY_END,
            ),
        )
        tools.register(
            ActionCode.A12_EVALUATE_REPORT,
            EvaluateReportToolHandler(
                self.repository,
                evaluation_service=self.evaluation,
                report_builder=self.report_builder,
                observation_snapshot_id="lowman-full-eval-truth",
                output_dir=self.report_dir,
            ),
        )
        provider = ScriptedDecisionProvider(
            [
                AgentDecision(
                    action=ActionCode.A03_VALIDATE_SCHEME,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary="Confirm the base scheme is executable before forecasting.",
                ),
                AgentDecision(
                    action=ActionCode.A05_FORECAST,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary="Run the audited base XAJ forecast.",
                ),
                AgentDecision(
                    action=ActionCode.A07_OPTIMIZE,
                    hypothesis=ProblemHypothesis.MODEL,
                    strategy_id="xaj-bounded-v1",
                    rationale_summary="Bounded calibration produces one candidate scheme.",
                ),
            ]
        )
        return AgentRuntime(
            self.repository,
            provider=provider,
            tools=tools,
            world_state=WorldStateBuilder(self.repository),
            provider_name="scripted-full-flow",
        )

    def run(self) -> dict:
        base_hash = self.repository.get_scheme("scheme-base").content_hash
        runtime = self._build_agent()

        validate_ev = runtime.run_round(TASK_ID)
        forecast_ev = runtime.run_round(TASK_ID)
        optimize_ev = runtime.run_round(TASK_ID)
        if validate_ev.status != "succeeded":
            raise RuntimeError(f"validate failed: {validate_ev.status}")
        if forecast_ev.status != "succeeded":
            raise RuntimeError(f"forecast failed: {forecast_ev.status}")
        if optimize_ev.status != "succeeded":
            raise RuntimeError(f"optimize failed: {optimize_ev.status}")

        candidate_id = next(
            s.scheme_id for s in self.repository.list_schemes(TASK_ID) if s.status == "candidate"
        )
        base_eval = build_evaluation_bundle(
            "scheme-base",
            {
                1: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5]),
                2: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5]),
                3: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.5]),
            },
        )
        candidate_eval = build_evaluation_bundle(
            candidate_id,
            {
                1: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.6]),
                2: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.6]),
                3: ([1.0, 2.0, 3.0], [1.0, 2.0, 2.6]),
            },
        )
        self._gate_bundles = (base_eval, candidate_eval)

        runtime.provider.queue(
            [
                AgentDecision(
                    action=ActionCode.A08_GATE,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary="Compare candidate against base with Gate guardrails.",
                ),
                AgentDecision(
                    action=ActionCode.A09_RESOLVE,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary="Apply Gate outcome to the current scheme pointer.",
                ),
                AgentDecision(
                    action=ActionCode.A10_FREEZE,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary="Freeze the operational scheme for historical replay.",
                ),
            ]
        )
        gate_ev = runtime.run_round(TASK_ID)
        resolve_ev = runtime.run_round(TASK_ID)
        freeze_ev = runtime.run_round(TASK_ID)
        if gate_ev.status not in {"ACCEPT", "KEEP", "ROLLBACK"}:
            raise RuntimeError(f"unexpected gate status: {gate_ev.status}")
        if freeze_ev.status != "succeeded":
            raise RuntimeError(f"freeze failed: {freeze_ev.status}")
        if self.repository.get_task(TASK_ID).phase != "F":
            raise RuntimeError("freeze did not advance task to F")

        frozen_id = self.repository.get_task_state(TASK_ID).current_scheme_id
        if self.repository.get_scheme(frozen_id).status != "frozen":
            raise RuntimeError("current scheme is not frozen")
        if self.repository.get_scheme("scheme-base").content_hash != base_hash:
            raise RuntimeError("base scheme mutated during freeze path")

        runtime.provider.queue(
            [
                AgentDecision(
                    action=ActionCode.A11_REPLAY,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary="Replay the frozen scheme across legal historical issues.",
                ),
            ]
        )
        replay_ev = runtime.run_round(TASK_ID)
        if replay_ev.status != "succeeded":
            raise RuntimeError(f"replay failed: {replay_ev.status}")

        if self.repository.get_task(TASK_ID).phase != "E":
            raise RuntimeError("replay did not advance task to E")
        self.builder.build(
            SnapshotContext(
                task_id=TASK_ID,
                snapshot_id="lowman-full-eval-truth",
                basin_id=str(self.source.basin["basin_id"]),
                phase="E",
                forcing_mode="R",
                capability="evaluate",
                issue_time=ISSUE,
                history_days=60,
            ),
            forcing_rows=list(self.source.forcing_rows),
            flow_rows=self.flow_rows,
            basin=self.source.basin,
        )
        runtime.provider.queue(
            [
                AgentDecision(
                    action=ActionCode.A12_EVALUATE_REPORT,
                    hypothesis=ProblemHypothesis.MODEL,
                    rationale_summary="Read-only E-phase metrics and deterministic report artifacts.",
                ),
            ]
        )
        eval_ev = runtime.run_round(TASK_ID)
        if eval_ev.status != "succeeded":
            raise RuntimeError(f"evaluate/report failed: {eval_ev.status}")

        forecasts = [
            row for row in self.repository.list_forecasts(TASK_ID) if row.scheme_id == frozen_id
        ]
        evidence_actions = [row.action for row in self.repository.list_evidence(TASK_ID)]
        return {
            "base_hash": base_hash,
            "frozen_id": frozen_id,
            "candidate_id": candidate_id,
            "gate_status": gate_ev.status,
            "resolve_status": resolve_ev.status,
            "replay_forecast_count": len(forecasts),
            "evidence_actions": evidence_actions,
            "eval_metrics": dict(eval_ev.metrics),
            "report_paths": sorted(p.name for p in self.report_dir.iterdir()),
            "phase": self.repository.get_task(TASK_ID).phase,
            "optimization_cycles": self.repository.get_task_state(TASK_ID).optimization_cycles_used,
        }
