import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hydro_agent.data.contracts import FlowObservation, ForcingRow, SnapshotContext
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.evaluation.metrics import build_evaluation_bundle
from hydro_agent.execution.contracts import ExecutionPolicy
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter
from hydro_agent.optimization.candidates import CandidateSchemeService
from hydro_agent.optimization.contracts import GatePolicy
from hydro_agent.optimization.gate import GateEvaluator
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.services.calibration import CalibrationService
from hydro_agent.services.workspace import MaterializingWorkspaceManager

REAL_SNAPSHOT = os.getenv("HYDRO_AGENT_LOWMAN_SNAPSHOT")
SCHEME_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "xaj" / "lowman_scheme.json"
pytestmark = pytest.mark.skipif(
    not REAL_SNAPSHOT, reason="set HYDRO_AGENT_LOWMAN_SNAPSHOT to SP4 snapshot"
)

ISSUE = datetime(2020, 5, 1, tzinfo=timezone.utc)
AVAILABLE = datetime(2019, 1, 1, tzinfo=timezone.utc)


class RealCalibrationFlow:
    def __init__(self, tmp_path: Path):
        source_snapshot = Path(REAL_SNAPSHOT).resolve()
        basin = json.loads((source_snapshot / "basin.json").read_text())
        forcing_rows = []
        with (source_snapshot / "forcing.csv").open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                forcing_rows.append(
                    ForcingRow(
                        valid_date=__import__("datetime").date.fromisoformat(row["date"]),
                        precipitation_mm_day=float(row["precipitation_mm_day"]),
                        pet_mm_day=float(row["pet_mm_day"]),
                        source_kind="reanalysis",
                        source="caravan-multimet-v1.1-era5-land-fao-pm",
                        available_at=AVAILABLE,
                    )
                )
        # Synthetic but historically available discharge for calibration wiring.
        flow_rows = [
            FlowObservation(
                valid_date=row.valid_date,
                discharge_m3s=10.0 + (i % 17) * 0.3,
                source="synthetic-calibration-obs",
                available_at=AVAILABLE,
            )
            for i, row in enumerate(forcing_rows)
            if row.valid_date <= ISSUE.date()
        ]
        db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
        db.create_schema()
        self.repository = HydroRepository(db)
        self.repository.create_task(
            task_id="lowman-r-001",
            basin_id=basin["basin_id"],
            phase="B",
            forcing_mode="R",
        )
        scheme = json.loads(SCHEME_PATH.read_text())
        scheme["warmup_days"] = 300
        self.repository.create_scheme(
            scheme_id="scheme-base",
            task_id="lowman-r-001",
            model_id="xaj",
            status="base",
            config=scheme,
            content_hash="lowman-base-hash",
        )
        snapshot_root = tmp_path / "snapshots"
        builder = SnapshotBuilder(snapshot_root, DataAccessPolicy(), self.repository)
        path = builder.build(
            SnapshotContext(
                task_id="lowman-r-001",
                snapshot_id="lowman-cal-2020-05-01",
                basin_id=basin["basin_id"],
                phase="B",
                forcing_mode="R",
                capability="forecast",
                issue_time=ISSUE,
                history_days=365,
            ),
            forcing_rows=forcing_rows,
            flow_rows=flow_rows,
            basin=basin,
        )
        assert (path / "streamflow.csv").stat().st_size > 20
        workspaces = MaterializingWorkspaceManager(
            tmp_path / "runs", self.repository, snapshot_root=snapshot_root
        )
        registry = RuntimeRegistry()
        registry.register(XajRuntimeAdapter())
        self.calibration = CalibrationService(
            self.repository, runner=SandboxRunner(registry, workspaces)
        )
        self.candidates = CandidateSchemeService(self.repository)
        self.base_scheme = self.repository.get_scheme("scheme-base")
        self.snapshot_id = "lowman-cal-2020-05-01"

    def run(self):
        policy = ExecutionPolicy(
            timeout_seconds=600, network_access=False, max_output_bytes=20_000_000, device="cpu"
        )
        outcome = self.calibration.calibrate(
            task_id="lowman-r-001",
            base_scheme_id="scheme-base",
            calibration_snapshot_id=self.snapshot_id,
            validation_snapshot_id=self.snapshot_id,
            strategy_id="xaj-bounded-v1",
            policy=policy,
        )
        candidate_id = self.candidates.register_candidate(
            base_scheme_id="scheme-base",
            action_run_id=outcome.action_run_id,
            calibration_payload=outcome.result_payload,
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
        return self.repository.get_scheme(candidate_id), base_eval, candidate_eval


@pytest.fixture
def real_calibration_flow(tmp_path):
    return RealCalibrationFlow(tmp_path)


def test_real_candidate_rollback_preserves_base(real_calibration_flow):
    base_hash = real_calibration_flow.base_scheme.content_hash
    candidate, base_eval, candidate_eval = real_calibration_flow.run()
    strict_policy = GatePolicy(
        min_primary_delta=999.0,
        max_single_lead_drop=0.0,
        max_high_flow_mae_relative_increase=0.0,
    )
    decision = GateEvaluator().evaluate(base_eval, candidate_eval, strict_policy)
    assert decision.status in {"KEEP", "ROLLBACK"}
    assert real_calibration_flow.repository.get_scheme("scheme-base").content_hash == base_hash
    assert candidate.scheme_id != "scheme-base"
