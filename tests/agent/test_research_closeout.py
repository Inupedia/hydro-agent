from __future__ import annotations

import pytest

from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    EvidencePacket,
    ProblemHypothesis,
)
from hydro_agent.agent.research_closeout import ResearchFreezeToolHandler
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


class SpyFreezeService:
    def __init__(self):
        self.calls = 0
        self.research_closeout = None
        self.source_scheme_id = None

    def freeze(
        self,
        *,
        task_id,
        source_scheme_id,
        gate_decision_id=None,
        research_closeout=None,
    ):
        self.calls += 1
        self.source_scheme_id = source_scheme_id
        self.research_closeout = dict(research_closeout or {})
        return f"frozen-{source_scheme_id}"


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
        config={
            "model_id": "xaj",
            "warmup_days": 2,
            "parameters": {"K": 0.7},
            "workbench": {
                "campaign_mode": "smoke",
                "campaign_max_model_evaluations": 100,
            },
        },
        content_hash="base-hash",
    )
    repo.create_scheme(
        scheme_id="scheme-candidate",
        task_id="task-1",
        model_id="xaj",
        status="candidate",
        config={
            "model_id": "xaj",
            "warmup_days": 2,
            "parameters": {"K": 0.8},
            "workbench": {
                "campaign_mode": "smoke",
                "campaign_max_model_evaluations": 100,
            },
        },
        content_hash="candidate-hash",
    )
    repo.ensure_task_state("task-1", current_scheme_id="scheme-base")
    return repo


def _decision() -> AgentDecision:
    return AgentDecision(
        action=ActionCode.A10_FREEZE,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="Close out the preregistered research campaign.",
    )


def _add_trial(
    repository,
    *,
    model_evaluations: int,
    qualification_status: str,
    adopted: bool,
) -> None:
    candidate_id = "scheme-candidate"
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-a07",
            task_id="task-1",
            action=ActionCode.A07_OPTIMIZE,
            status="succeeded",
            observations=("final_test_accessed=false",),
            metrics={
                "objective_value": 0.5,
                "model_evaluations": float(model_evaluations),
            },
            gates={
                "base_scheme_id": "scheme-base",
                "candidate_scheme_id": candidate_id,
                "strategy_id": "xaj-test-v1",
                "objective": "nse",
                "objective_metric": "nse",
                "param_groups": "evap,runoff",
                "model_evaluations": str(model_evaluations),
            },
            new_information_hash="hash-a07",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-a08",
            task_id="task-1",
            action=ActionCode.A08_GATE,
            status="ACCEPT",
            observations=(f"qualification_status={qualification_status}",),
            metrics={
                "base_primary": 0.2,
                "candidate_primary": 0.4,
                "primary_delta": 0.2,
            },
            gates={
                "status": "ACCEPT",
                "adoption_status": "ADOPT" if adopted else "KEEP",
                "qualification_status": qualification_status,
                "candidate_scheme_id": candidate_id,
            },
            new_information_hash="hash-a08",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-a09",
            task_id="task-1",
            action=ActionCode.A09_RESOLVE,
            status="ACCEPT" if qualification_status == "QUALIFIED" else "KEEP",
            observations=(f"qualification_status={qualification_status}",),
            gates={
                "status": "ACCEPT" if qualification_status == "QUALIFIED" else "KEEP",
                "gate_status": "ACCEPT",
                "adoption_status": "ADOPT" if adopted else "KEEP",
                "qualification_status": qualification_status,
                "candidate_adopted": "true" if adopted else "false",
                "candidate_scheme_id": candidate_id,
            },
            new_information_hash="hash-a09",
        )
    )
    if adopted:
        repository.update_task_state("task-1", current_scheme_id=candidate_id)


def test_campaign_not_stopped_blocks_final_test_even_when_latest_gate_qualified(repository):
    _add_trial(
        repository,
        model_evaluations=10,
        qualification_status="QUALIFIED",
        adopted=True,
    )
    freeze = SpyFreezeService()

    packet = ResearchFreezeToolHandler(repository, freeze_service=freeze).execute(
        "task-1", _decision()
    )

    assert packet.status == "blocked"
    assert packet.gates["reason"] == "campaign_stop_required_before_freeze"
    assert packet.gates["final_test_consumed"] == "false"
    assert packet.gates["release_approved"] == "false"
    assert freeze.calls == 0
    assert repository.get_task("task-1").phase == "B"


def test_budget_stopped_unqualified_result_enters_research_final_test_without_release(repository):
    _add_trial(
        repository,
        model_evaluations=100,
        qualification_status="UNQUALIFIED",
        adopted=True,
    )
    freeze = SpyFreezeService()

    packet = ResearchFreezeToolHandler(repository, freeze_service=freeze).execute(
        "task-1", _decision()
    )

    assert packet.status == "succeeded"
    assert packet.gates["campaign_stop_reason"] == "BUDGET_EXHAUSTED"
    assert packet.gates["qualification_status"] == "UNQUALIFIED"
    assert packet.gates["release_approved"] == "false"
    assert packet.gates["final_test_consumed"] == "false"
    assert freeze.calls == 1
    assert freeze.research_closeout["purpose"] == "research_final_evaluation"
    assert freeze.research_closeout["release_approved"] is False
    assert freeze.research_closeout["final_test_access"] == "read_only_after_freeze"
    assert repository.get_task("task-1").phase == "F"


def test_stopped_selected_qualified_candidate_is_release_approved(repository):
    _add_trial(
        repository,
        model_evaluations=100,
        qualification_status="QUALIFIED",
        adopted=True,
    )
    freeze = SpyFreezeService()

    packet = ResearchFreezeToolHandler(repository, freeze_service=freeze).execute(
        "task-1", _decision()
    )

    assert packet.status == "succeeded"
    assert packet.gates["release_approved"] == "true"
    assert freeze.source_scheme_id == "scheme-candidate"
    assert freeze.research_closeout["qualification_status"] == "QUALIFIED"
    assert freeze.research_closeout["release_approved"] is True
