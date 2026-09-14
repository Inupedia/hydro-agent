import json
from pathlib import Path

from hydro_agent.agent.contracts import ActionCode, EvidencePacket

CREATE_BODY = {
    "basin_id": "camels_13235000",
    "model_id": "xaj",
    "start_date": "2025-05-01",
    "end_date": "2025-05-10",
    "forcing_mode": "R",
    "base_scheme_id": "scheme-base",
    "allow_optimization": True,
    "validation_days": 3,
    "final_test_days": 3,
}


def test_research_summary_rebuilds_protocol_trials_and_short_final_test(
    client, repository, app_dependencies
):
    task_id = client.post("/api/tasks", json=CREATE_BODY).json()["task_id"]

    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-06",
            task_id=task_id,
            action=ActionCode.A06_DIAGNOSE,
            status="succeeded",
            observations=("diagnosis",),
            new_information_hash="hash-06",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-07",
            task_id=task_id,
            action=ActionCode.A07_OPTIMIZE,
            status="succeeded",
            observations=("candidate",),
            metrics={"model_evaluations": 120.0},
            gates={
                "experiment_plan_id": "plan-water-balance",
                "experiment_signature": "sig-water-balance",
                "experiment_reason_codes": "diagnosis_recommendation,water_balance_groups",
                "experiment_evidence_refs": "ev-06",
                "strategy_id": "xaj-water-balance-v1",
                "optimizer": "dds",
                "objective": "composite",
                "objective_metric": "kge",
                "param_groups": "evap,runoff",
                "evaluation_budget": "384",
                "model_evaluations": "120",
                "active_parameters": "K,B,SM",
                "sensitivity_method": "morris",
                "base_scheme_id": "base",
                "candidate_scheme_id": "candidate",
            },
            new_information_hash="hash-07",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-08",
            task_id=task_id,
            action=ActionCode.A08_GATE,
            status="ROLLBACK",
            observations=("development rejected candidate",),
            metrics={"primary_delta": -0.1},
            gates={
                "status": "ROLLBACK",
                "adoption_status": "REJECT",
                "qualification_status": "UNQUALIFIED",
                "candidate_scheme_id": "candidate",
            },
            new_information_hash="hash-08",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-09",
            task_id=task_id,
            action=ActionCode.A09_RESOLVE,
            status="ROLLBACK",
            observations=("resolved",),
            gates={
                "gate_status": "ROLLBACK",
                "adoption_status": "REJECT",
                "qualification_status": "UNQUALIFIED",
            },
            new_information_hash="hash-09",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-12",
            task_id=task_id,
            action=ActionCode.A12_EVALUATE_REPORT,
            status="succeeded",
            observations=(
                "final_test_window=2025-05-08..2025-05-10",
                "final_test_read_only=true",
                "final_test_consumption=1/1",
            ),
            new_information_hash="hash-12",
        )
    )

    report_dir = Path(app_dependencies.report_root) / task_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "test-hydrograph.json").write_text(
        json.dumps(
            {
                "kind": "independent_test",
                "series": [
                    {
                        "time": "2025-05-08",
                        "observed_m3s": 10.0,
                        "frozen_m3s": 9.0,
                        "window": "final_test",
                    },
                    {
                        "time": "2025-05-09",
                        "observed_m3s": 20.0,
                        "frozen_m3s": 18.0,
                        "window": "final_test",
                    },
                    {
                        "time": "2025-05-10",
                        "observed_m3s": 15.0,
                        "frozen_m3s": 14.0,
                        "window": "final_test",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    response = client.get(f"/api/tasks/{task_id}/research")
    assert response.status_code == 200
    payload = response.json()

    assert payload["protocol"]["protocol_mode"] == "research"
    assert payload["protocol"]["calibration_start_date"] == "2025-05-01"
    assert payload["protocol"]["calibration_end_date"] == "2025-05-04"
    assert payload["protocol"]["development_start_date"] == "2025-05-05"
    assert payload["protocol"]["development_end_date"] == "2025-05-07"
    assert payload["protocol"]["final_test_start_date"] == "2025-05-08"
    assert payload["protocol"]["final_test_end_date"] == "2025-05-10"

    plan = payload["latest_experiment_plan"]
    assert plan["plan_id"] == "plan-water-balance"
    assert plan["objective"] == "kge"
    assert plan["reason_codes"] == ["diagnosis_recommendation", "water_balance_groups"]
    assert plan["active_parameters"] == ["K", "B", "SM"]

    assert len(payload["trials"]) == 1
    assert payload["trials"][0]["hypothesis_outcome"] == "refuted"
    assert payload["trials"][0]["model_evaluations"] == 120

    final = payload["final_test_evidence"]
    assert final["quality"]["valid_count"] == 3
    assert final["overall"]["status"] == "available"
    assert final["overall"]["sample_count"] == 3
    assert final["fdc"]["status"] == "insufficient_data"
    assert final["years"]["2025"]["status"] == "insufficient_data"

    assert payload["final_test_audit"] == {
        "consumed": True,
        "read_only": True,
        "single_use": True,
        "window": "2025-05-08..2025-05-10",
    }
    assert payload["contracts"]["rolling_continuous_separated"] is True
    assert payload["contracts"]["final_test_used_for_selection"] is False
