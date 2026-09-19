from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, ProblemHypothesis
from hydro_agent.agent.tools import (
    DependencyToolTraceRecorder,
    ForecastHandler,
    GateHandler,
    OptimizeHandler,
    ResolveHandler,
    ToolExecutionContext,
    ToolRouter,
    ToolUnavailable,
)
from hydro_agent.api.deps import AppDependencies
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.services.calibration import CalibrationExecutionFailed


@dataclass
class FakeForecast:
    forecast_id: str = "fc-1"
    action_run_id: str = "run-fc-1"
    lead_values: dict | None = None
    artifact_ids: tuple = ("a1",)

    def __post_init__(self):
        if self.lead_values is None:
            self.lead_values = {1: 1.0, 2: 2.0, 3: 3.0}


class SpyForecastService:
    def __init__(self):
        self.calls = 0

    def forecast(self, **kwargs):
        self.calls += 1
        return FakeForecast()


class FakeCalibrationService:
    def calibrate(self, **kwargs):
        return SimpleNamespace(
            action_run_id="run-cal-1",
            strategy_id="xaj-bounded-v1",
            base_scheme_id="scheme-base",
            candidate_parameters={"K": 0.8},
            objective_value=0.42,
            objective="nse",
            param_groups=("evap",),
            artifact_ids=("cal-result",),
            result_payload={
                "optimizer": "dds",
                "evaluation_budget": 64,
                "model_evaluations": 61,
                "execution_attempts": 2,
                "resume_attempts": 1,
                "restored_model_evaluations": 17,
                "resumed_from_workspace": True,
                "objective_metric": "nse",
                "search_boundary_evidence": {
                    "local_hits": [],
                    "absolute_hits": [],
                },
            },
        )


class RecordingCalibrationService(FakeCalibrationService):
    def __init__(self):
        self.calls = []

    def calibrate(self, **kwargs):
        self.calls.append(kwargs)
        outcome = super().calibrate(**kwargs)
        budget = kwargs["evaluation_budget_override"]
        payload = dict(outcome.result_payload)
        payload.update({"evaluation_budget": budget, "model_evaluations": budget})
        return SimpleNamespace(**{**vars(outcome), "result_payload": payload})


class FailedCalibrationService:
    def calibrate(self, **kwargs):
        raise CalibrationExecutionFailed(
            "run-cal-failed",
            "timed_out",
            "timeout",
            model_evaluations=53,
            evaluation_budget=64,
            execution_attempts=4,
            resume_attempts=3,
        )


class FakeCandidateService:
    def __init__(self):
        self.payload = None

    def register_candidate(self, *, base_scheme_id, action_run_id, calibration_payload):
        self.payload = calibration_payload
        return "scheme-candidate"


@pytest.fixture
def repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="b1", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"parameters": {"K": 0.7}, "workbench": {"campaign_max_model_evaluations": 400}},
        content_hash="h",
    )
    repo.ensure_task_state("task-1", current_scheme_id="scheme-base")
    return repo


@pytest.fixture
def spy_forecast_service():
    return SpyForecastService()


@pytest.fixture
def forecast_decision():
    return AgentDecision(
        action=ActionCode.A03_FORECAST,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="Run the base forecast.",
    )


@pytest.fixture
def optimize_decision():
    return AgentDecision(
        action=ActionCode.A05_OPTIMIZE,
        hypothesis=ProblemHypothesis.MODEL,
        strategy_id="xaj-bounded-v1",
        param_groups=("evap",),
        objective="nse",
        rationale_summary="Run the preregistered calibration experiment.",
    )


@pytest.fixture
def tool_router(repository, spy_forecast_service):
    router = ToolRouter()
    router.register(
        ActionCode.A03_FORECAST,
        ForecastHandler(
            repository,
            forecast_service=spy_forecast_service,
            issue_time="2020-05-01T00:00:00Z",
            policy=object(),
        ),
    )
    return router


def test_forecast_action_calls_forecast_service_not_sandbox_directly(
    tool_router, forecast_decision, spy_forecast_service
):
    evidence = tool_router.execute("task-1", forecast_decision)
    assert spy_forecast_service.calls == 1
    assert evidence.action == ActionCode.A03_FORECAST
    assert evidence.status == "succeeded"


def test_tool_router_records_native_runtime_trace(repository):
    class InstantRuntime:
        def run_until_terminal(self, task_id):
            return []

    deps = AppDependencies(repository=repository, runtime_factory=lambda: InstantRuntime())

    class TracedForecastHandler:
        def execute(self, task_id, decision):
            return EvidencePacket(
                evidence_id="ev-trace",
                task_id=task_id,
                action=ActionCode.A03_FORECAST,
                status="KEEP",
                observations=("observed",),
                metrics={"NSE": 0.8},
                new_information_hash="hash-trace",
            )

    router = ToolRouter(trace_recorder=DependencyToolTraceRecorder(deps))
    router.register(ActionCode.A03_FORECAST, TracedForecastHandler())
    decision = AgentDecision(
        action=ActionCode.A03_FORECAST,
        hypothesis=ProblemHypothesis.MODEL,
        strategy_id="forecast-strategy",
        rationale_summary="Run forecast.",
    )
    packet = router.execute("task-1", decision, ToolExecutionContext("dec-trace", 1))
    row = deps.list_agent_round_logs("task-1")[0]
    call = row["tool_calls"][0]

    assert packet.decision_id == "dec-trace"
    assert row["decision_id"] == "dec-trace"
    assert call["trace_source"] == "runtime"
    assert call["tool_id"] == "hydrology.forecast"
    assert call["status"] == "completed"
    assert call["evidence_id"] == "ev-trace"
    assert call["duration_ms"] >= 0
    assert row["tool_status"] == "completed"


def test_tool_router_records_failed_runtime_trace(repository):
    class InstantRuntime:
        def run_until_terminal(self, task_id):
            return []

    deps = AppDependencies(repository=repository, runtime_factory=lambda: InstantRuntime())

    class FailingHandler:
        def execute(self, task_id, decision):
            raise RuntimeError("tool failed")

    router = ToolRouter(trace_recorder=DependencyToolTraceRecorder(deps))
    router.register(ActionCode.A04_DIAGNOSE, FailingHandler())
    decision = AgentDecision(
        action=ActionCode.A04_DIAGNOSE,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="Diagnose errors.",
    )
    with pytest.raises(RuntimeError, match="tool failed"):
        router.execute("task-1", decision, ToolExecutionContext("dec-failed", 1))
    row = deps.list_agent_round_logs("task-1")[0]
    call = row["tool_calls"][0]
    assert call["trace_source"] == "runtime"
    assert call["status"] == "failed"
    assert call["output_summary"]["error"] == "tool failed"


def test_unregistered_action_raises_tool_unavailable(tool_router):
    decision = AgentDecision(
        action=ActionCode.A04_DIAGNOSE,
        hypothesis=ProblemHypothesis.UNKNOWN,
        rationale_summary="Diagnose without a registered tool.",
    )
    with pytest.raises(ToolUnavailable):
        tool_router.execute("task-1", decision)


def test_optimize_evidence_exposes_resume_audit_fields(repository, optimize_decision):
    candidates = FakeCandidateService()
    handler = OptimizeHandler(
        repository,
        calibration_service=FakeCalibrationService(),
        candidate_service=candidates,
        calibration_snapshot_id="snap-cal",
        validation_snapshot_id=None,
        policy=object(),
    )

    packet = handler.execute("task-1", optimize_decision)

    assert packet.status == "succeeded"
    assert packet.gates["execution_attempts"] == "2"
    assert packet.gates["resume_attempts"] == "1"
    assert packet.gates["restored_model_evaluations"] == "17"
    assert packet.gates["resumed_from_workspace"] == "true"
    assert packet.metrics["resume_attempts"] == 1.0
    assert "resumed_from_workspace=true" in packet.observations
    assert candidates.payload["resume_attempts"] == 1
    assert candidates.payload["resumed_from_workspace"] is True


def test_optimizer_receives_only_remaining_campaign_budget(repository, optimize_decision):
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-prior-optimize",
            task_id="task-1",
            action=ActionCode.A05_OPTIMIZE,
            status="succeeded",
            metrics={"model_evaluations": 366.0},
            gates={"model_evaluations": "366", "strategy_id": "xaj-bounded-v1"},
            new_information_hash="prior-optimize",
        )
    )
    service = RecordingCalibrationService()
    handler = OptimizeHandler(
        repository,
        calibration_service=service,
        candidate_service=FakeCandidateService(),
        calibration_snapshot_id="snap-cal",
        validation_snapshot_id=None,
        policy=object(),
    )

    packet = handler.execute("task-1", optimize_decision)

    assert service.calls[0]["evaluation_budget_override"] == 34
    assert packet.metrics["model_evaluations"] == 34.0
    assert 366 + packet.metrics["model_evaluations"] == 400


def test_optimizer_does_not_start_with_one_evaluation_left(repository, optimize_decision):
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-almost-exhausted",
            task_id="task-1",
            action=ActionCode.A05_OPTIMIZE,
            status="succeeded",
            gates={"model_evaluations": "399"},
            new_information_hash="almost-exhausted",
        )
    )
    service = RecordingCalibrationService()
    handler = OptimizeHandler(
        repository,
        calibration_service=service,
        candidate_service=FakeCandidateService(),
        calibration_snapshot_id="snap-cal",
        validation_snapshot_id=None,
        policy=object(),
    )

    packet = handler.execute("task-1", optimize_decision)

    assert packet.status == "blocked"
    assert packet.gates["reason"] == "campaign_budget_exhausted"
    assert service.calls == []


def test_failed_optimize_records_spent_budget_without_registering_candidate(
    repository, optimize_decision
):
    candidates = FakeCandidateService()
    handler = OptimizeHandler(
        repository,
        calibration_service=FailedCalibrationService(),
        candidate_service=candidates,
        calibration_snapshot_id="snap-cal",
        validation_snapshot_id=None,
        policy=object(),
    )

    packet = handler.execute("task-1", optimize_decision)

    assert packet.status == "failed"
    assert packet.action_run_id == "run-cal-failed"
    assert packet.metrics["model_evaluations"] == 53.0
    assert packet.gates["evaluation_budget"] == "64"
    assert packet.gates["execution_attempts"] == "4"
    assert packet.gates["resume_attempts"] == "3"
    assert packet.gates["resumed_from_workspace"] == "true"
    assert packet.gates["candidate_scheme_id"] == ""
    assert packet.gates["reason"] == "calibration_execution_failed"
    assert candidates.payload is None



def test_refuted_direction_does_not_register_candidate(repository, optimize_decision):
    class RefutedCalibrationService(FakeCalibrationService):
        def calibrate(self, **kwargs):
            outcome = super().calibrate(**kwargs)
            payload = dict(outcome.result_payload)
            payload.update(
                {
                    "direction_verification_status": "refuted",
                    "direction_verification_evidence_ids": ["event-001"],
                    "optimizer_calls": 0,
                }
            )
            return SimpleNamespace(**{**vars(outcome), "result_payload": payload})

    candidates = FakeCandidateService()
    handler = OptimizeHandler(
        repository,
        calibration_service=RefutedCalibrationService(),
        candidate_service=candidates,
        calibration_snapshot_id="snap-cal",
        validation_snapshot_id=None,
        policy=object(),
    )

    packet = handler.execute("task-1", optimize_decision)

    assert packet.status == "blocked"
    assert packet.gates["reason"] == "direction_refuted"
    assert packet.gates["direction_verification_status"] == "refuted"
    assert candidates.payload is None



def test_gate_handler_forwards_development_event_comparison(repository):
    from hydro_agent.optimization.contracts import (
        EvaluationBundle,
        GatePolicy,
        LeadMetrics,
    )

    def bundle(scheme_id, score):
        return EvaluationBundle(
            scheme_id=scheme_id,
            leads=(
                LeadMetrics(lead=1, nse=score, mae=1.0, bias=0.0, high_flow_mae=1.0),
            ),
            primary_score=score,
        )

    event_comparison = {
        "base": [{"event_id": "event-001", "peak_relative_error": 0.1}],
        "candidate": [{"event_id": "event-001", "peak_relative_error": 0.05}],
    }

    class CapturingGate:
        def __init__(self):
            self.event_comparison = None

        def evaluate(self, base, candidate, policy, *, gbt_report=None, event_comparison=None):
            self.event_comparison = event_comparison
            return SimpleNamespace(
                status="ACCEPT",
                adoption_status="ADOPT",
                research_qualification="QUALIFIED",
                qualification_status="NOT_EVALUATED",
                base_scheme_id=base.scheme_id,
                candidate_scheme_id=candidate.scheme_id,
                reasons=("meaningful_primary_improvement",),
                qualification_reasons=("missing_standard_evaluation",),
                primary_delta=candidate.primary_score - base.primary_score,
                scheme_grade=None,
                gbt_summary=None,
            )

    gate = CapturingGate()
    handler = GateHandler(
        repository,
        gate_evaluator=gate,
        policy=GatePolicy(
            min_primary_delta=0.01,
            max_single_lead_drop=0.02,
            max_high_flow_mae_relative_increase=0.05,
        ),
        bundle_provider=lambda _task_id: (
            bundle("scheme-base", 0.3),
            bundle("scheme-candidate", 0.6),
            None,
            event_comparison,
        ),
    )
    decision = AgentDecision(
        action=ActionCode.A06_GATE,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="Compare development evidence.",
    )

    packet = handler.execute("task-1", decision)

    assert packet.status == "ACCEPT"
    assert gate.event_comparison == event_comparison
    assert "event_comparison_json" in packet.gates



def test_resolve_accepts_research_adoption_without_standard_qualification(repository):
    repository.create_scheme(
        scheme_id="scheme-research-adopted",
        task_id="task-1",
        model_id="xaj",
        status="candidate",
        config={"parameters": {"K": 0.8}},
        content_hash="research-adopted",
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-research-gate",
            task_id="task-1",
            action=ActionCode.A06_GATE,
            status="ACCEPT",
            observations=(),
            metrics={},
            gates={
                "status": "ACCEPT",
                "adoption_status": "ADOPT",
                "research_qualification": "QUALIFIED",
                "qualification_status": "NOT_EVALUATED",
                "candidate_scheme_id": "scheme-research-adopted",
            },
            new_information_hash="research-gate-hash",
        )
    )
    handler = ResolveHandler(repository)
    decision = AgentDecision(
        action=ActionCode.A07_RESOLVE,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="Apply the research adoption transaction.",
    )

    packet = handler.execute("task-1", decision)

    assert packet.status == "ACCEPT"
    assert packet.gates["research_qualification"] == "QUALIFIED"
    assert packet.gates["qualification_status"] == "NOT_EVALUATED"
    assert packet.gates["candidate_adopted"] == "true"
    assert repository.get_task_state("task-1").current_scheme_id == "scheme-research-adopted"
