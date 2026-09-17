"""Fixture-backed PDCA path for plugin models (no CAMELS / Lowman dependency)."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from hydro_agent.agent.contracts import ActionCode, AgentDecision, ProblemHypothesis
from hydro_agent.agent.providers.scripted import ScriptedDecisionProvider
from hydro_agent.agent.research_closeout import ResearchFreezeToolHandler
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.tools import (
    CheckDataHandler,
    ForecastHandler,
    GateHandler,
    OptimizeHandler,
    ReplayToolHandler,
    ResolveHandler,
    ToolRouter,
    ValidateSchemeHandler,
)
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.data.contracts import FlowObservation, ForcingRow, SnapshotContext
from hydro_agent.data.lowman import NormalizedSource
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.evaluation.metrics import build_evaluation_bundle
from hydro_agent.execution.contracts import ExecutionPolicy
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.diagnosis_defaults import water_balance_plan
from hydro_agent.models.registry import default_model_registry
from hydro_agent.optimization.candidates import CandidateSchemeService
from hydro_agent.optimization.contracts import GatePolicy
from hydro_agent.optimization.gate import GateEvaluator
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.replay.freeze import FreezeService
from hydro_agent.replay.planner import ReplayPlanner
from hydro_agent.replay.service import ReplayService
from hydro_agent.services.calibration import CalibrationService
from hydro_agent.services.forecast import ForecastService
from hydro_agent.services.snapshots import SnapshotResolver
from hydro_agent.services.workspace import MaterializingWorkspaceManager

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ISSUE_HOUR = datetime(2026, 1, 1, tzinfo=timezone.utc)  # overwritten per fixture
POLICY = ExecutionPolicy(
    timeout_seconds=120, network_access=False, max_output_bytes=5_000_000, device="cpu"
)
GATE_POLICY = GatePolicy(
    min_primary_delta=0.01,
    max_single_lead_drop=0.02,
    max_high_flow_mae_relative_increase=0.05,
)
PLUGIN_MODELS = ("gr4j", "hbv", "tank", "sac-sma")
FIXTURE_DIR = {"gr4j": "gr4j", "hbv": "hbv", "tank": "tank", "sac-sma": "sacsma"}


def _load_fixture_source(model_id: str):
    root = FIXTURES / FIXTURE_DIR[model_id]
    basin = json.loads((root / "basin.json").read_text(encoding="utf-8"))
    basin.setdefault("day_timezone", "UTC")
    scheme = json.loads((root / "scheme.json").read_text(encoding="utf-8"))
    available = datetime(2019, 1, 1, tzinfo=timezone.utc)
    forcing_rows = []
    with (root / "forcing.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            temp = row.get("temperature_c")
            forcing_rows.append(
                ForcingRow(
                    valid_date=date.fromisoformat(row["date"]),
                    precipitation_mm_day=float(row["precipitation_mm_day"]),
                    pet_mm_day=float(row["pet_mm_day"]),
                    temperature_c=None if temp in (None, "") else float(temp),
                    source_kind="observation",
                    source="fixture",
                    available_at=available,
                )
            )
    flow_rows = [
        FlowObservation(
            valid_date=row.valid_date,
            discharge_m3s=8.0 + (index % 7) * 0.4,
            source="fixture-obs",
            available_at=available,
        )
        for index, row in enumerate(forcing_rows)
    ]
    source = NormalizedSource(
        basin=basin,
        forcing_rows=tuple(forcing_rows),
        flow_rows=tuple(flow_rows),
    )
    return source, scheme


def _issue_from_source(source) -> datetime:
    last = source.forcing_rows[-1].valid_date
    issue_day = last - timedelta(days=3)
    return datetime(issue_day.year, issue_day.month, issue_day.day, tzinfo=timezone.utc)


@pytest.mark.parametrize("model_id", PLUGIN_MODELS)
def test_plugin_pdca_forecast_calibrate_freeze(tmp_path, model_id):
    plugin = default_model_registry().get(model_id)
    assert water_balance_plan(model_id)[0].startswith(f"{model_id}-")
    assert plugin.descriptor.diagnosis_policy is not None

    source, scheme = _load_fixture_source(model_id)
    issue = _issue_from_source(source)
    issue_iso = issue.isoformat().replace("+00:00", "Z")
    task_id = f"plugin-{model_id}"
    history_days = len(source.forcing_rows) - 3

    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repository = HydroRepository(db)
    basin_id = str(source.basin["basin_id"])
    repository.create_task(task_id=task_id, basin_id=basin_id, phase="B", forcing_mode="R")
    scheme = dict(scheme)
    scheme["warmup_days"] = min(int(scheme.get("warmup_days") or 30), max(1, history_days - 3))
    workbench = dict(scheme.get("workbench") or {})
    workbench.update(
        {
            "campaign_mode": "smoke",
            "campaign_max_model_evaluations": 8,
            "allow_optimization": True,
            # This test exercises plumbing only. Product/API tasks cannot opt in;
            # scientific calibration remains blocked until each kernel is validated.
            "allow_unverified_model_calibration": True,
        }
    )
    scheme["workbench"] = workbench
    repository.create_scheme(
        scheme_id="scheme-base",
        task_id=task_id,
        model_id=model_id,
        status="base",
        config=scheme,
        content_hash=f"{model_id}-base-hash",
    )
    repository.ensure_task_state(task_id, current_scheme_id="scheme-base")

    snapshot_root = tmp_path / "snapshots"
    builder = SnapshotBuilder(snapshot_root, DataAccessPolicy(), repository)
    cal_id = f"{model_id}-cal"
    builder.build(
        SnapshotContext(
            task_id=task_id,
            snapshot_id=cal_id,
            basin_id=basin_id,
            phase="B",
            forcing_mode="R",
            capability="calibrate",
            issue_time=issue,
            history_days=history_days,
            history_end_date=source.forcing_rows[-4].valid_date,
        ),
        forcing_rows=list(source.forcing_rows),
        flow_rows=list(source.flow_rows),
        basin=source.basin,
    )
    resolver = SnapshotResolver(repository, builder=builder, source=source, history_days=history_days)
    workspaces = MaterializingWorkspaceManager(tmp_path / "runs", repository, snapshot_root=snapshot_root)
    runner = SandboxRunner(default_model_registry().runtime_registry(), workspaces)
    forecast = ForecastService(repository, resolver=resolver, runner=runner)
    calibration = CalibrationService(
        repository, runner=runner, strategies=default_model_registry().strategy_registry()
    )
    candidates = CandidateSchemeService(repository)
    freeze_service = FreezeService(repository, gate_policy=GATE_POLICY.model_dump())
    gate_bundles = None

    def bundle_provider(_task_id: str):
        assert gate_bundles is not None
        return gate_bundles

    tools = ToolRouter()
    tools.register(ActionCode.A01_CHECK_DATA, CheckDataHandler(repository))
    tools.register(ActionCode.A02_VALIDATE_SCHEME, ValidateSchemeHandler(repository))
    tools.register(
        ActionCode.A03_FORECAST,
        ForecastHandler(repository, forecast_service=forecast, issue_time=issue_iso, policy=POLICY),
    )
    tools.register(
        ActionCode.A05_OPTIMIZE,
        OptimizeHandler(
            repository,
            calibration_service=calibration,
            candidate_service=candidates,
            calibration_snapshot_id=cal_id,
            validation_snapshot_id=cal_id,
            policy=POLICY,
        ),
    )
    tools.register(
        ActionCode.A06_GATE,
        GateHandler(
            repository,
            gate_evaluator=GateEvaluator(),
            policy=GATE_POLICY,
            bundle_provider=bundle_provider,
        ),
    )
    tools.register(ActionCode.A07_RESOLVE, ResolveHandler(repository))
    tools.register(
        ActionCode.A08_FREEZE,
        ResearchFreezeToolHandler(repository, freeze_service=freeze_service),
    )
    replay_start = issue.date()
    planner = ReplayPlanner(repository, resolver=resolver)
    replay_service = ReplayService(repository, forecast_service=forecast, policy=POLICY)
    tools.register(
        ActionCode.A09_REPLAY,
        ReplayToolHandler(
            repository,
            planner=planner,
            replay_service=replay_service,
            start_date=replay_start,
            end_date=replay_start,
        ),
    )
    provider = ScriptedDecisionProvider(
        [
            AgentDecision(
                action=ActionCode.A01_CHECK_DATA,
                hypothesis=ProblemHypothesis.DATA,
                rationale_summary="check plugin task data",
            ),
            AgentDecision(
                action=ActionCode.A02_VALIDATE_SCHEME,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="validate plugin scheme",
            ),
            AgentDecision(
                action=ActionCode.A03_FORECAST,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="forecast plugin scheme",
            ),
            AgentDecision(
                action=ActionCode.A05_OPTIMIZE,
                hypothesis=ProblemHypothesis.MODEL,
                strategy_id=plugin.descriptor.default_strategy_id,
                param_groups=tuple(plugin.descriptor.parameter_groups),
                objective="nse",
                rationale_summary="bounded calibration",
            ),
        ]
    )
    runtime = AgentRuntime(
        repository,
        provider=provider,
        tools=tools,
        world_state=WorldStateBuilder(repository, model_registry=default_model_registry()),
        provider_name="scripted-plugin-flow",
    )

    check_ev = runtime.run_round(task_id)
    validate_ev = runtime.run_round(task_id)
    forecast_ev = runtime.run_round(task_id)
    optimize_ev = runtime.run_round(task_id)
    assert check_ev.status == "succeeded", check_ev.observations
    assert validate_ev.status == "succeeded", validate_ev.observations
    assert forecast_ev.status == "succeeded", forecast_ev.observations
    assert optimize_ev.status == "succeeded", optimize_ev.observations

    candidate_id = next(
        row.scheme_id for row in repository.list_schemes(task_id) if row.status == "candidate"
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
    gate_bundles = (base_eval, candidate_eval)

    provider.queue(
        [
            AgentDecision(
                action=ActionCode.A06_GATE,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="gate",
            ),
            AgentDecision(
                action=ActionCode.A07_RESOLVE,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="resolve",
            ),
            AgentDecision(
                action=ActionCode.A08_FREEZE,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="freeze",
            ),
        ]
    )
    gate_ev = runtime.run_round(task_id)
    runtime.run_round(task_id)
    freeze_ev = runtime.run_round(task_id)
    assert gate_ev.status in {"ACCEPT", "KEEP", "ROLLBACK"}
    assert freeze_ev.status == "succeeded"
    frozen = repository.get_scheme(repository.get_task_state(task_id).current_scheme_id)
    assert frozen.status == "frozen"
    assert frozen.model_id == model_id

    provider.queue(
        [
            AgentDecision(
                action=ActionCode.A09_REPLAY,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="replay frozen scheme",
            ),
        ]
    )
    replay_ev = runtime.run_round(task_id)
    assert replay_ev.status == "succeeded", replay_ev.observations
    actions = [row.action for row in repository.list_evidence(task_id)]
    assert actions == [
        "A01_CHECK_DATA",
        "A02_VALIDATE_SCHEME",
        "A03_FORECAST",
        "A05_OPTIMIZE",
        "A06_GATE",
        "A07_RESOLVE",
        "A08_FREEZE",
        "A09_REPLAY",
    ]
