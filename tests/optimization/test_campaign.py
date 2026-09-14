from types import SimpleNamespace

import pytest

from hydro_agent.optimization.campaign import (
    DEFAULT_SMOKE_MAX_MODEL_EVALUATIONS,
    CampaignPolicy,
    policy_from_workbench,
    rebuild_campaign,
)
from hydro_agent.optimization.experiments import TrialRecord
from hydro_agent.optimization.ledger import TrialLedgerBuilder


def _trial(
    index: int,
    *,
    strategy: str = "xaj-bounded-v1",
    search_score: float,
    base_primary: float,
    selected_primary: float,
    adopted: bool = True,
    qualification: str = "UNQUALIFIED",
    evaluations: int = 512,
) -> TrialRecord:
    candidate = f"scheme-{index}"
    return TrialRecord(
        trial_id=f"trial-{index}",
        plan_id=f"plan-{index}",
        experiment_signature=f"sig-{index}",
        strategy_id=strategy,
        base_scheme_id=f"scheme-{index - 1}",
        candidate_scheme_id=candidate,
        model_evaluations=evaluations,
        search_score=search_score,
        base_primary=base_primary,
        candidate_primary=selected_primary if adopted else base_primary,
        selected_primary=selected_primary,
        candidate_adopted=adopted,
        resolve_recorded=True,
        development_gate="ACCEPT" if adopted else "KEEP",
        adoption_status="ADOPT" if adopted else "KEEP",
        qualification_status=qualification,
    )


def test_smoke_policy_defaults_to_model_evaluation_budget_not_trial_count():
    policy = policy_from_workbench({"campaign_mode": "smoke", "max_optimization_cycles": 2})

    assert policy.max_model_evaluations == DEFAULT_SMOKE_MAX_MODEL_EVALUATIONS
    assert policy.search_objective_policy == "fixed"
    assert not hasattr(policy, "smoke_max_trials")


def test_policy_surfaces_adaptive_search_objective():
    policy = policy_from_workbench(
        {"campaign_mode": "convergence", "search_objective_policy": "adaptive"}
    )

    assert policy.search_objective_policy == "adaptive"


def test_campaign_separates_search_selected_and_release_best():
    records = (
        _trial(
            1,
            search_score=0.4,
            base_primary=-154.392,
            selected_primary=-0.891,
            evaluations=495,
        ),
        _trial(
            2,
            search_score=0.6,
            base_primary=-0.891,
            selected_primary=-0.762,
            evaluations=512,
        ),
    )
    snapshot = rebuild_campaign(
        records,
        current_scheme_id="scheme-2",
        policy=CampaignPolicy(mode="smoke", max_model_evaluations=1000),
    )

    assert snapshot.search_best_scheme_id == "scheme-2"
    assert snapshot.search_best_score == 0.6
    assert snapshot.selected_best_scheme_id == "scheme-2"
    assert snapshot.selected_primary_score == -0.762
    assert snapshot.release_candidate_scheme_id is None
    assert snapshot.total_model_evaluations == 1007
    assert snapshot.stop_reason == "BUDGET_EXHAUSTED"
    assert snapshot.converged is False


def test_adaptive_campaign_never_ranks_cross_objective_search_scores():
    records = (
        _trial(1, search_score=100.0, base_primary=0.5, selected_primary=0.6000),
        _trial(2, search_score=-50.0, base_primary=0.6000, selected_primary=0.6005),
        _trial(
            3,
            strategy="xaj-broadened-refine-v1",
            search_score=0.9,
            base_primary=0.6005,
            selected_primary=0.6010,
        ),
    )
    snapshot = rebuild_campaign(
        records,
        current_scheme_id="scheme-3",
        policy=CampaignPolicy(
            mode="convergence",
            search_objective_policy="adaptive",
            max_model_evaluations=5000,
            min_model_evaluations=1000,
            plateau_window=2,
            plateau_abs_epsilon=0.001,
            restart_distinct_strategies=2,
        ),
    )

    assert snapshot.search_best_scheme_id is None
    assert snapshot.search_best_score is None
    assert snapshot.selected_primary_score == 0.6010
    assert snapshot.plateau_candidate is True
    assert snapshot.restart_check_satisfied is True
    assert snapshot.stop_reason == "CONVERGED"
    assert "not cross-comparable" in " ".join(snapshot.notes)


def test_convergence_mode_does_not_stop_only_because_candidate_is_qualified():
    records = (
        _trial(
            1,
            search_score=0.7,
            base_primary=0.3,
            selected_primary=0.7,
            qualification="QUALIFIED",
        ),
    )
    snapshot = rebuild_campaign(
        records,
        current_scheme_id="scheme-1",
        policy=CampaignPolicy(
            mode="convergence",
            max_model_evaluations=5000,
            min_model_evaluations=1000,
            plateau_window=2,
            plateau_abs_epsilon=0.001,
        ),
    )

    assert snapshot.release_candidate_scheme_id == "scheme-1"
    assert snapshot.stop_reason is None
    assert snapshot.can_continue_search is True
    assert snapshot.converged is False


def test_plateau_requires_distinct_restart_check_before_convergence():
    records = (
        _trial(1, search_score=0.6, base_primary=0.5, selected_primary=0.6),
        _trial(2, search_score=0.601, base_primary=0.6, selected_primary=0.6005),
        _trial(3, search_score=0.602, base_primary=0.6005, selected_primary=0.6010),
    )
    policy = CampaignPolicy(
        mode="convergence",
        max_model_evaluations=5000,
        min_model_evaluations=1000,
        plateau_window=2,
        plateau_abs_epsilon=0.001,
        restart_distinct_strategies=2,
    )
    first = rebuild_campaign(records, current_scheme_id="scheme-3", policy=policy)

    assert first.plateau_candidate is True
    assert first.restart_check_satisfied is False
    assert first.stop_reason is None
    assert first.converged is False

    restarted = (
        *records,
        _trial(
            4,
            strategy="xaj-broadened-refine-v1",
            search_score=0.603,
            base_primary=0.6010,
            selected_primary=0.6014,
        ),
    )
    second = rebuild_campaign(restarted, current_scheme_id="scheme-4", policy=policy)

    assert second.plateau_candidate is True
    assert second.restart_check_satisfied is True
    assert second.stop_reason == "CONVERGED"
    assert second.converged is True


def test_budget_exhaustion_while_still_improving_is_not_convergence():
    records = (
        _trial(1, search_score=0.4, base_primary=0.1, selected_primary=0.3),
        _trial(2, search_score=0.6, base_primary=0.3, selected_primary=0.5),
    )
    snapshot = rebuild_campaign(
        records,
        current_scheme_id="scheme-2",
        policy=CampaignPolicy(
            mode="convergence",
            max_model_evaluations=1024,
            min_model_evaluations=512,
            plateau_window=2,
            plateau_abs_epsilon=0.001,
        ),
    )

    assert snapshot.stop_reason == "BUDGET_EXHAUSTED"
    assert snapshot.plateau_candidate is False
    assert snapshot.converged is False
    assert "without operational convergence" in " ".join(snapshot.notes)


def test_campaign_resume_rebuilds_identical_state_from_persisted_evidence():
    rows = [
        SimpleNamespace(
            action="A07_OPTIMIZE",
            evidence_id="ev-07",
            action_run_id="run-07",
            gates_json={
                "strategy_id": "xaj-bounded-v1",
                "base_scheme_id": "scheme-0",
                "candidate_scheme_id": "scheme-1",
                "model_evaluations": "512",
                "objective": "nse",
            },
            metrics_json={"objective_value": 0.55, "model_evaluations": 512.0},
        ),
        SimpleNamespace(
            action="A08_GATE",
            evidence_id="ev-08",
            status="ACCEPT",
            gates_json={
                "status": "ACCEPT",
                "adoption_status": "ADOPT",
                "qualification_status": "UNQUALIFIED",
            },
            metrics_json={
                "base_primary": 0.2,
                "candidate_primary": 0.4,
                "primary_delta": 0.2,
            },
        ),
        SimpleNamespace(
            action="A09_RESOLVE",
            evidence_id="ev-09",
            status="KEEP",
            gates_json={
                "gate_status": "ACCEPT",
                "adoption_status": "ADOPT",
                "qualification_status": "UNQUALIFIED",
                "candidate_adopted": "true",
            },
            metrics_json={},
        ),
    ]
    policy = CampaignPolicy(mode="smoke", max_model_evaluations=1024)

    before_restart = rebuild_campaign(
        TrialLedgerBuilder().build(rows).records,
        current_scheme_id="scheme-1",
        policy=policy,
    )
    after_restart = rebuild_campaign(
        TrialLedgerBuilder().build(list(rows)).records,
        current_scheme_id="scheme-1",
        policy=policy,
    )

    assert before_restart == after_restart
    assert after_restart.selected_best_scheme_id == "scheme-1"
    assert after_restart.selected_primary_score == 0.4
    assert after_restart.total_model_evaluations == 512


@pytest.mark.parametrize("scores", [(0.2, 0.4, 0.6), (0.6, None, 0.6)])
def test_unchanged_selected_scheme_is_not_search_convergence(scores):
    records = tuple(
        _trial(
            index,
            strategy="xaj-bounded-v1" if index < 3 else "xaj-broadened-refine-v1",
            search_score=score if score is not None else 0.6,
            base_primary=0.5,
            selected_primary=0.5,
            adopted=False,
        ).model_copy(update={"search_score": score})
        for index, score in enumerate(scores, start=1)
    )
    snapshot = rebuild_campaign(
        records,
        current_scheme_id="scheme-0",
        policy=CampaignPolicy(
            mode="convergence",
            max_model_evaluations=5000,
            min_model_evaluations=1000,
            plateau_window=2,
            plateau_abs_epsilon=0.001,
        ),
    )
    assert not snapshot.plateau_candidate
    assert not snapshot.converged
    assert snapshot.can_continue_search


def test_repeated_gate_rejection_requires_review_not_infeasibility_claim():
    snapshot = rebuild_campaign(
        [_trial(1, search_score=0.7, base_primary=0.5, selected_primary=0.5, adopted=False)],
        current_scheme_id="scheme-0",
        policy=CampaignPolicy(mode="smoke", max_no_gain_gates=1),
    )
    assert snapshot.stop_reason == "HUMAN_HANDOVER"
    assert not snapshot.converged
