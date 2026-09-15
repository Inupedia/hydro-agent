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
        row("ev-06", "A04_DIAGNOSE"),
        row(
            "ev-07",
            "A05_OPTIMIZE",
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
                "parameter_delta_json": "{\"K\": -0.25, \"SM\": 10.0}",
            },
            metrics={"objective_value": 0.78, "baseline_nse": -6.3, "candidate_nse": 0.78},
        ),
        row(
            "ev-08",
            "A06_GATE",
            status="ROLLBACK",
            gates={
                "status": "ROLLBACK",
                "adoption_status": "REJECT",
                "qualification_status": "UNQUALIFIED",
                "candidate_scheme_id": "cand",
                "reasons": "lead_1_guardrail,lead_1_high_flow_guardrail,insufficient_absolute_skill",
                "qualification_reasons": "insufficient_absolute_skill",
            },
            metrics={"primary_delta": -0.2, "candidate_delta": -0.2},
        ),
        row(
            "ev-09",
            "A07_RESOLVE",
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
    assert trial.parameter_delta == {"K": -0.25, "SM": 10.0}
    assert trial.baseline_nse == -6.3
    assert trial.candidate_nse == 0.78
    assert trial.gate_reasons == (
        "lead_1_guardrail",
        "lead_1_high_flow_guardrail",
        "insufficient_absolute_skill",
    )


def test_ledger_prefers_persisted_plan_metadata_when_available():
    ledger = TrialLedgerBuilder().build(
        [
            row("diag", "A04_DIAGNOSE"),
            row(
                "opt",
                "A05_OPTIMIZE",
                gates={
                    "strategy_id": "xaj-broadened-refine-v1",
                    "experiment_plan_id": "plan-explicit",
                    "experiment_signature": "sig-explicit",
                    "experiment_reason_codes": "local_boundary_hit,diagnosis_recommendation",
                    "experiment_evidence_refs": "diag,ev-boundary",
                },
            ),
        ]
    )

    trial = ledger.records[0]
    assert trial.plan_id == "plan-explicit"
    assert trial.experiment_signature == "sig-explicit"
    assert trial.evidence_refs == ("diag", "ev-boundary", "opt")
    assert "local_boundary_hit" in trial.reason_codes
    assert "diagnosis_recommendation" in trial.reason_codes


def test_ledger_flushes_incomplete_trial_as_inconclusive():
    ledger = TrialLedgerBuilder().build(
        [
            row("ev-06", "A04_DIAGNOSE"),
            row(
                "ev-07",
                "A05_OPTIMIZE",
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
            row("diag-1", "A04_DIAGNOSE"),
            row("opt-1", "A05_OPTIMIZE", gates={"strategy_id": "xaj-bounded-v1"}),
            row("diag-2", "A04_DIAGNOSE"),
            row("opt-2", "A05_OPTIMIZE", gates={"strategy_id": "xaj-local-refine-v1"}),
            row(
                "gate-2",
                "A06_GATE",
                status="ACCEPT",
                gates={"status": "ACCEPT", "adoption_status": "ADOPT"},
                metrics={"primary_delta": 0.1},
            ),
            row(
                "resolve-2",
                "A07_RESOLVE",
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


def test_agent_calibration_document_lists_existing_chart_artifacts(tmp_path):
    from hydro_agent.optimization.ledger import agent_calibration_document

    (tmp_path / "calibration-comparison.png").write_bytes(b"png")
    payload = agent_calibration_document(
        [
            row(
                "ev-07",
                "A05_OPTIMIZE",
                gates={"strategy_id": "xaj-water-balance-v1", "parameter_delta_json": '{"K": -0.2}'},
                metrics={"baseline_nse": -1.0, "candidate_nse": 0.5},
            )
        ],
        tmp_path,
    )
    assert payload["artifacts"] == ["calibration-comparison.png"]
    trials = payload["trials"]
    assert len(trials) == 1
    assert trials[0]["parameter_delta"] == {"K": -0.2}
    assert trials[0]["baseline_nse"] == -1.0
