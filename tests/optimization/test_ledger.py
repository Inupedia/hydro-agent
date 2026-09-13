from types import SimpleNamespace

from hydro_agent.optimization.ledger import TrialLedgerBuilder


def row(evidence_id, action, *, status="succeeded", gates=None, metrics=None, action_run_id=None):
    return SimpleNamespace(
        evidence_id=evidence_id,
        action=action,
        status=status,
        gates_json=gates or {},
        metrics_json=metrics or {},
        action_run_id=action_run_id,
    )


def test_ledger_reconstructs_complete_calibration_cycle():
    rows = [
        row("ev-06", "A06_DIAGNOSE"),
        row(
            "ev-07",
            "A07_OPTIMIZE",
            action_run_id="run-1",
            gates={
                "strategy_id": "xaj-water-balance-v1",
                "objective": "composite",
                "objective_metric": "kge",
                "param_groups": "evap,runoff",
                "evaluation_budget": "384",
                "model_evaluations": "384",
                "base_scheme_id": "base",
                "candidate_scheme_id": "cand",
            },
        ),
        row(
            "ev-08",
            "A08_GATE",
            status="ROLLBACK",
            gates={
                "status": "ROLLBACK",
                "adoption_status": "REJECT",
                "qualification_status": "UNQUALIFIED",
                "candidate_scheme_id": "cand",
            },
            metrics={"primary_delta": -0.2, "candidate_delta": -0.2},
        ),
        row(
            "ev-09",
            "A09_RESOLVE",
            status="ROLLBACK",
            gates={
                "gate_status": "ROLLBACK",
                "adoption_status": "REJECT",
                "qualification_status": "UNQUALIFIED",
            },
        ),
    ]

    ledger = TrialLedgerBuilder().build(rows)

    assert len(ledger.records) == 1
    trial = ledger.records[0]
    assert trial.strategy_id == "xaj-water-balance-v1"
    assert trial.base_scheme_id == "base"
    assert trial.candidate_scheme_id == "cand"
    assert trial.action_run_id == "run-1"
    assert trial.model_evaluations == 384
    assert trial.development_gate == "ROLLBACK"
    assert trial.hypothesis_outcome == "refuted"
    assert trial.evidence_refs == ("ev-06", "ev-07", "ev-08", "ev-09")
    assert trial.metric_deltas["primary_delta"] == -0.2


def test_ledger_flushes_incomplete_trial_as_inconclusive():
    ledger = TrialLedgerBuilder().build(
        [
            row("ev-06", "A06_DIAGNOSE"),
            row(
                "ev-07",
                "A07_OPTIMIZE",
                gates={"strategy_id": "xaj-bounded-v1", "model_evaluations": "100"},
            ),
        ]
    )

    assert len(ledger.records) == 1
    trial = ledger.records[0]
    assert trial.hypothesis_outcome == "inconclusive"
    assert trial.development_gate == "NOT_EVALUATED"
    assert trial.evidence_refs == ("ev-06", "ev-07")


def test_new_a07_flushes_previous_open_trial_without_cross_cycle_gate_leakage():
    ledger = TrialLedgerBuilder().build(
        [
            row("diag-1", "A06_DIAGNOSE"),
            row("opt-1", "A07_OPTIMIZE", gates={"strategy_id": "xaj-bounded-v1"}),
            row("diag-2", "A06_DIAGNOSE"),
            row("opt-2", "A07_OPTIMIZE", gates={"strategy_id": "xaj-local-refine-v1"}),
            row(
                "gate-2",
                "A08_GATE",
                status="ACCEPT",
                gates={"status": "ACCEPT", "adoption_status": "ADOPT"},
                metrics={"primary_delta": 0.1},
            ),
            row(
                "resolve-2",
                "A09_RESOLVE",
                status="KEEP",
                gates={"gate_status": "ACCEPT", "adoption_status": "ADOPT"},
            ),
        ]
    )

    first, second = ledger.records
    assert first.evidence_refs == ("diag-1", "opt-1")
    assert first.hypothesis_outcome == "inconclusive"
    assert second.evidence_refs == ("diag-2", "opt-2", "gate-2", "resolve-2")
    assert second.hypothesis_outcome == "supported"
