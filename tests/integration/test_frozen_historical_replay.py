import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from hydro_agent.data.contracts import FlowObservation, SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.evaluation.service import EvaluationService
from hydro_agent.execution.contracts import ExecutionPolicy
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.replay.freeze import FreezeService
from hydro_agent.replay.planner import ReplayPlanner
from hydro_agent.replay.service import ReplayService
from hydro_agent.reporting.report import ReplayReportBuilder
from hydro_agent.services.forecast import ForecastService
from hydro_agent.services.snapshots import SnapshotResolver
from hydro_agent.services.workspace import MaterializingWorkspaceManager

REAL_SNAPSHOT = os.getenv("HYDRO_AGENT_LOWMAN_SNAPSHOT")
SOURCE_DIR = Path(__file__).resolve().parents[2] / "data" / "source" / "camels_13235000"
SCHEME_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "xaj" / "lowman_scheme.json"
pytestmark = pytest.mark.skipif(
    not REAL_SNAPSHOT or not SOURCE_DIR.exists(),
    reason="set HYDRO_AGENT_LOWMAN_SNAPSHOT and prepare data/source/camels_13235000",
)

ISSUE_START = date(2020, 4, 29)
ISSUE_END = date(2020, 5, 1)
AVAILABLE = datetime(2019, 1, 1, tzinfo=timezone.utc)
POLICY = ExecutionPolicy(
    timeout_seconds=600, network_access=False, max_output_bytes=20_000_000, device="cpu"
)


class RealReplayFlow:
    def __init__(self, tmp_path: Path):
        self.source = load_normalized_source(SOURCE_DIR)
        # Prepared MultiMet source may omit discharge; synthesize historically available truth.
        if not self.source.flow_rows:
            self.flow_rows = [
                FlowObservation(
                    valid_date=row.valid_date,
                    discharge_m3s=8.0 + (i % 11) * 0.25,
                    source="synthetic-eval-obs",
                    available_at=AVAILABLE,
                )
                for i, row in enumerate(self.source.forcing_rows)
            ]
        else:
            self.flow_rows = list(self.source.flow_rows)
        db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
        db.create_schema()
        self.repository = HydroRepository(db)
        basin_id = str(self.source.basin["basin_id"])
        self.repository.create_task(
            task_id="lowman-replay-001",
            basin_id=basin_id,
            phase="B",
            forcing_mode="R",
        )
        scheme = json.loads(SCHEME_PATH.read_text())
        scheme["warmup_days"] = 30
        self.repository.create_scheme(
            scheme_id="scheme-base",
            task_id="lowman-replay-001",
            model_id="xaj",
            status="base",
            config=scheme,
            content_hash="lowman-base-hash",
        )
        self.repository.ensure_task_state("lowman-replay-001", current_scheme_id="scheme-base")
        self.snapshot_root = tmp_path / "snapshots"
        self.builder = SnapshotBuilder(self.snapshot_root, DataAccessPolicy(), self.repository)
        self.resolver = SnapshotResolver(
            self.repository, builder=self.builder, source=self.source, history_days=60
        )
        workspaces = MaterializingWorkspaceManager(
            tmp_path / "runs", self.repository, snapshot_root=self.snapshot_root
        )
        registry = RuntimeRegistry()
        registry.register(XajRuntimeAdapter())
        self.forecast = ForecastService(
            self.repository,
            resolver=self.resolver,
            runner=SandboxRunner(registry, workspaces),
            model_id="xaj",
        )
        self.freeze_service = FreezeService(self.repository)
        self.planner = ReplayPlanner(self.repository, resolver=self.resolver)
        self.replay_service = ReplayService(
            self.repository, forecast_service=self.forecast, policy=POLICY
        )
        self.evaluation = EvaluationService(self.repository, snapshot_root=self.snapshot_root)
        self.report_builder = ReplayReportBuilder()
        self.report_dir = tmp_path / "reports"
        self.frozen_id = None

    def freeze(self) -> str:
        self.frozen_id = self.freeze_service.freeze(
            task_id="lowman-replay-001", source_scheme_id="scheme-base"
        )
        self.repository.set_task_phase("lowman-replay-001", "F")
        return self.frozen_id

    def replay(self, frozen_id: str):
        assert frozen_id == self.frozen_id
        plan = self.planner.plan("lowman-replay-001", ISSUE_START, ISSUE_END)
        return self.replay_service.execute(plan)

    def evaluate_and_report(self):
        self.repository.set_task_phase("lowman-replay-001", "E")
        eval_id = "lowman-eval-truth"
        issue = datetime(2020, 5, 1, tzinfo=timezone.utc)
        self.builder.build(
            SnapshotContext(
                task_id="lowman-replay-001",
                snapshot_id=eval_id,
                basin_id=str(self.source.basin["basin_id"]),
                phase="E",
                forcing_mode="R",
                capability="evaluate",
                issue_time=issue,
                history_days=60,
            ),
            forcing_rows=list(self.source.forcing_rows),
            flow_rows=self.flow_rows,
            basin=self.source.basin,
        )
        evaluation = self.evaluation.evaluate("lowman-replay-001", eval_id)
        artifacts = self.report_builder.build(evaluation, self.report_dir)
        return evaluation, artifacts


def test_freeze_replay_evaluate_report_end_to_end(tmp_path):
    flow = RealReplayFlow(tmp_path)
    source_hash = flow.repository.get_scheme("scheme-base").content_hash
    frozen_id = flow.freeze()
    forecasts = flow.replay(frozen_id)
    evaluation, report_artifacts = flow.evaluate_and_report()

    assert len(forecasts) >= 3
    assert {f.scheme_id for f in forecasts} == {frozen_id}
    assert flow.repository.get_scheme("scheme-base").content_hash == source_hash
    assert evaluation.scheme_id == frozen_id
    assert set(evaluation.metrics) >= {"NSE", "KGE", "MAE", "Bias"}
    assert len(report_artifacts) == 2
    for forecast in forecasts:
        action = flow.repository.get_action_run(forecast.action_run_id)
        assert action.capability == "forecast"
        assert action.scheme_id == frozen_id
    assert flow.repository.get_task("lowman-replay-001").phase == "E"
    assert flow.repository.get_task_state("lowman-replay-001").optimization_cycles_used == 0
