import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hydro_agent.agent.contracts import ActionCode, EvidencePacket

CREATE_BODY = {
    "basin_id": "camels_13235000",
    "model_id": "xaj",
    "start_date": "2025-05-01",
    "end_date": "2025-05-10",
    "forcing_mode": "R",
    "base_scheme_id": "scheme-base",
    "allow_optimization": True,
}


def test_agent_log_exposes_persisted_skill_invocation_audit(client, repository, app_dependencies):
    repository.create_task(
        task_id="skill-audit-task", basin_id="yaogu", phase="B", forcing_mode="R"
    )
    manifest = {
        "skill_id": "hydro-error-diagnosis",
        "source": "builtin",
        "skill_sha256": "b" * 64,
        "loaded_references": [{"path": "references/metric-patterns.md", "sha256": "c" * 64}],
    }
    repository.record_agent_decision(
        decision_id="dec-skill-audit",
        task_id="skill-audit-task",
        round_number=1,
        provider="siliconflow",
        model="fixture",
        world_state_hash="view-hash",
        action="A04_DIAGNOSE",
        hypothesis="MODEL",
        strategy_id=None,
        rationale_summary="Review evidence.",
        input_tokens=None,
        output_tokens=None,
        activated_skills_json=[manifest],
    )
    fallback = client.get("/api/tasks/skill-audit-task/agent-log").json()["rounds"][0]
    assert fallback["activated_skill_ids"] == ["hydro-error-diagnosis"]
    assert fallback["activated_skills_audit"] == [manifest]
    assert fallback["decision_id"] == "dec-skill-audit"
    assert fallback["tool_calls"][0]["tool_id"] == "hydrology.diagnose"
    assert fallback["tool_calls"][0]["status"] == "pending"
    assert fallback["tool_calls"][0]["trace_source"] == "legacy_inferred"
    app_dependencies.append_agent_round_log(
        "skill-audit-task",
        {"round_number": 1, "action": "A04_DIAGNOSE", "rationale_summary": "Review evidence."},
    )
    streamed = client.get("/api/tasks/skill-audit-task/agent-log").json()["rounds"][0]
    assert streamed["activated_skills_audit"] == [manifest]
    assert streamed["tool_calls"][0]["tool_name_zh"] == "模型诊断工具"
    assert streamed["decision_id"] == "dec-skill-audit"
    assert streamed["tool_calls"][0]["trace_source"] == "legacy_inferred"



def test_agent_log_exposes_persisted_experience_influence(client, repository, app_dependencies):
    repository.create_task(
        task_id="experience-audit-task", basin_id="yaogu", phase="B", forcing_mode="R"
    )
    repository.record_agent_decision(
        decision_id="dec-experience-audit",
        task_id="experience-audit-task",
        round_number=1,
        provider="fixture",
        model="fixture",
        world_state_hash="view-hash",
        action="A05_OPTIMIZE",
        hypothesis="MODEL",
        strategy_id="xaj-bounded-v1",
        rationale_summary="Use validated calibration experience.",
        input_tokens=None,
        output_tokens=None,
        activated_skills_json=[{"skill_id": "calibration-experience", "source": "agent"}],
        experience_audit_json={
            "skill_version": 4,
            "skill_hash": "e" * 64,
            "experience_refs": ["EXP-XAJ-0018"],
            "mode": "exploitation",
            "influence": [
                "same basin and model match",
                "routing experiments repeatedly improved peak timing",
            ],
        },
    )

    fallback = client.get("/api/tasks/experience-audit-task/agent-log").json()["rounds"][0]
    assert fallback["experience_skill_version"] == 4
    assert fallback["experience_skill_hash"] == "e" * 64
    assert fallback["experience_refs"] == ["EXP-XAJ-0018"]
    assert fallback["experience_mode"] == "exploitation"
    assert fallback["experience_influence"] == [
        "same basin and model match",
        "routing experiments repeatedly improved peak timing",
    ]

    app_dependencies.append_agent_round_log(
        "experience-audit-task",
        {
            "round_number": 1,
            "decision_id": "dec-experience-audit",
            "action": "A05_OPTIMIZE",
            "rationale_summary": "streamed row without durable audit fields",
        },
    )
    streamed = client.get("/api/tasks/experience-audit-task/agent-log").json()["rounds"][0]
    assert streamed["experience_skill_version"] == 4
    assert streamed["experience_refs"] == ["EXP-XAJ-0018"]
    assert streamed["experience_mode"] == "exploitation"

def test_agent_log_combines_skills_tools_and_evidence_for_legacy_rows(
    client, repository, app_dependencies
):
    repository.create_task(task_id="tool-audit-task", basin_id="yaogu", phase="B", forcing_mode="R")
    repository.record_agent_decision(
        decision_id="dec-tool-audit",
        task_id="tool-audit-task",
        round_number=1,
        provider="fixture",
        model="fixture",
        world_state_hash="view-hash",
        action="A05_OPTIMIZE",
        hypothesis="MODEL",
        strategy_id="xaj-bounded-v1",
        rationale_summary="Run a bounded experiment.",
        input_tokens=None,
        output_tokens=None,
        activated_skills_json=[{"skill_id": "xaj-calibration-diagnosis"}],
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-tool-audit",
            task_id="tool-audit-task",
            action=ActionCode.A05_OPTIMIZE,
            status="succeeded",
            observations=("optimizer=sce-ua", "model_evaluations=48"),
            metrics={"NSE": 0.781},
            gates={"param_groups": "runoff,routing", "objective": "nse"},
            new_information_hash="tool-audit-hash",
        )
    )
    payload = client.get("/api/tasks/tool-audit-task/agent-log").json()["rounds"][0]
    assert payload["activated_skill_ids"] == ["xaj-calibration-diagnosis"]
    assert payload["tool_calls"][0]["tool_id"] == "calibration.optimize"
    assert payload["tool_calls"][0]["status"] == "completed"
    assert payload["tool_calls"][0]["trace_source"] == "evidence_inferred"
    assert payload["tool_calls"][0]["input_summary"]["optimizer"] == "sce-ua"
    assert payload["tool_calls"][0]["metrics"]["model_evaluations"] == 48
    assert payload["evidence_summary"]["evidence_id"] == "ev-tool-audit"


def test_run_summary_exposes_current_round_coordinates(client, repository):
    task_id = client.post("/api/tasks", json=CREATE_BODY).json()["task_id"]
    repository.record_agent_decision(
        decision_id="dec-run-round",
        task_id=task_id,
        round_number=1,
        provider="fixture",
        model="fixture",
        world_state_hash="view-hash",
        action="A04_DIAGNOSE",
        hypothesis="MODEL",
        strategy_id=None,
        rationale_summary="Inspect errors.",
        input_tokens=None,
        output_tokens=None,
        activated_skills_json=[],
    )
    payload = client.get(f"/api/tasks/{task_id}/run").json()
    assert payload["current_round_number"] == 1
    assert payload["current_decision_id"] == "dec-run-round"


def test_paused_run_returns_last_real_round(client, repository, app_dependencies):
    task_id = client.post("/api/tasks", json=CREATE_BODY).json()["task_id"]
    repository.update_task_state(
        task_id,
        agent_rounds_used=6,
        paused=True,
        needs_follow_up=True,
    )
    repository.record_agent_decision(
        decision_id="dec-paused-round",
        task_id=task_id,
        round_number=6,
        provider="fixture",
        model="fixture",
        world_state_hash="view-hash",
        action="A05_OPTIMIZE",
        hypothesis="MODEL",
        strategy_id="xaj-bounded-v1",
        rationale_summary="Blocked for manual review.",
        input_tokens=None,
        output_tokens=None,
        activated_skills_json=[],
    )
    app_dependencies.begin_llm_trace(task_id, round_number=6)
    app_dependencies.finish_llm_trace(task_id, action="A05_OPTIMIZE")
    payload = client.get(f"/api/tasks/{task_id}/run").json()
    assert payload["current_round_number"] == 6
    assert payload["current_decision_id"] == "dec-paused-round"


def test_agent_log_binds_evidence_by_decision_id(client, repository, app_dependencies):
    task_id = client.post("/api/tasks", json=CREATE_BODY).json()["task_id"]
    for decision_id, evidence_id in (
        ("dec-earlier-a05", "ev-earlier-a05"),
        ("dec-current-a05", "ev-current-a05"),
    ):
        repository.record_agent_decision(
            decision_id=decision_id,
            task_id=task_id,
            round_number=1 if decision_id == "dec-earlier-a05" else 2,
            provider="fixture",
            model="fixture",
            world_state_hash="view-hash",
            action="A05_OPTIMIZE",
            hypothesis="MODEL",
            strategy_id="xaj-bounded-v1",
            rationale_summary="Run bounded optimization.",
            input_tokens=None,
            output_tokens=None,
            activated_skills_json=[],
        )
        repository.add_evidence(
            EvidencePacket(
                evidence_id=evidence_id,
                task_id=task_id,
                decision_id=decision_id,
                round_number=1 if decision_id == "dec-earlier-a05" else 2,
                action=ActionCode.A05_OPTIMIZE,
                status="succeeded",
                observations=("model_evaluations=48",),
                metrics={"NSE": 0.78},
                new_information_hash=f"hash-{evidence_id}",
            )
        )
    app_dependencies.append_agent_round_log(
        task_id,
        {
            "round_number": 2,
            "decision_id": "dec-current-a05",
            "action": "A05_OPTIMIZE",
            "rationale_summary": "Current optimization.",
        },
    )
    payload = client.get(f"/api/tasks/{task_id}/agent-log").json()["rounds"][0]
    assert payload["decision_id"] == "dec-current-a05"
    assert payload["tool_calls"][0]["evidence_id"] == "ev-current-a05"
    assert payload["evidence_summary"]["evidence_id"] == "ev-current-a05"


def test_results_are_read_from_persisted_scheme_forecast_gate_report(
    client, repository, app_dependencies
):
    task_id = client.post("/api/tasks", json=CREATE_BODY).json()["task_id"]
    state = repository.get_task_state(task_id)
    base_row = repository.get_scheme(state.current_scheme_id)
    base_config = dict(base_row.config_json or {})
    base_params = dict(base_config.get("parameters") or {})
    changed_key = next(iter(base_params))
    candidate_params = dict(base_params)
    candidate_params[changed_key] = float(candidate_params[changed_key]) + 0.01
    candidate_id = f"{state.current_scheme_id}--candidate"
    repository.create_scheme(
        scheme_id=candidate_id,
        task_id=task_id,
        model_id="xaj",
        status="candidate",
        config={
            **base_config,
            "parameters": candidate_params,
            "provenance": {"base_scheme_id": state.current_scheme_id},
        },
        content_hash="candidate-hash",
    )
    # Promote current scheme to frozen for result assembly.
    frozen_id = f"{state.current_scheme_id}--frozen"
    repository.create_scheme(
        scheme_id=frozen_id,
        task_id=task_id,
        model_id="xaj",
        status="frozen",
        config={
            "model_id": "xaj",
            "warmup_days": 2,
            "parameters": base_params,
            "provenance": {"source_scheme_id": state.current_scheme_id},
        },
        content_hash="frozen-hash",
    )
    repository.update_task_state(task_id, current_scheme_id=frozen_id)
    repository.set_task_phase(task_id, "F")
    repository.set_task_phase(task_id, "E")
    snap = f"{task_id}-snap"
    repository.create_snapshot(
        snapshot_id=snap,
        task_id=task_id,
        source="fixture",
        available_at=datetime(2020, 5, 1, tzinfo=timezone.utc),
        manifest={"files": []},
        content_hash="snap-hash",
    )
    repository.create_action_run(
        task_id=task_id,
        action_run_id="run-fc-1",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id=snap,
        scheme_id=frozen_id,
        issue_time="2020-05-01T00:00:00Z",
    )
    repository.create_forecast(
        forecast_id="fc-1",
        task_id=task_id,
        action_run_id="run-fc-1",
        scheme_id=frozen_id,
        data_snapshot_id=snap,
        issue_time="2020-05-01T00:00:00Z",
        lead_values={1: 10.0, 2: 11.0, 3: 12.0},
        unit="m3/s",
        artifact_ids=(),
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-optimize",
            task_id=task_id,
            action=ActionCode.A05_OPTIMIZE,
            status="succeeded",
            observations=(f"candidate_scheme_id={candidate_id}",),
            gates={
                "candidate_scheme_id": candidate_id,
                "base_scheme_id": state.current_scheme_id,
                "strategy_id": "xaj-peak-bias-v1",
                "param_groups": "runoff,routing",
                "objective": "composite",
            },
            new_information_hash="hash-optimize",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-gate",
            task_id=task_id,
            action=ActionCode.A06_GATE,
            status="KEEP",
            observations=("insufficient_primary_delta",),
            gates={"status": "KEEP", "candidate_scheme_id": candidate_id},
            new_information_hash="hash-gate",
        )
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-report",
            task_id=task_id,
            action=ActionCode.A10_EVALUATE_REPORT,
            status="succeeded",
            metrics={"NSE": 0.55, "KGE": 0.44, "MAE": 1.1, "Bias": -0.05},
            artifact_ids=("report.json", "report.md"),
            new_information_hash="hash-report",
        )
    )
    app_dependencies.report_artifacts[task_id] = ("report.json", "report.md")
    hydro_dir = Path(app_dependencies.report_root) / task_id
    hydro_dir.mkdir(parents=True, exist_ok=True)
    (hydro_dir / "test-hydrograph.json").write_text(
        json.dumps(
            {
                "kind": "independent_test",
                "title": "placeholder",
                "calibrated": False,
                "warmup_days": 1,
                "evaluated_days": 2,
                "series": [
                    {
                        "time": "2020-05-01",
                        "observed_m3s": 10.0,
                        "frozen_m3s": 9.0,
                        "window": "warmup",
                        "is_warmup": True,
                    },
                    {
                        "time": "2020-05-02",
                        "observed_m3s": 11.0,
                        "frozen_m3s": 10.5,
                        "window": "test",
                        "is_warmup": False,
                    },
                ],
                "frozen_metrics": {
                    "nse": 0.4,
                    "count": 2,
                    "peak_timing_lag_steps": -2,
                    "window": "final_test",
                    "start_date": "2020-05-01",
                    "end_date": "2020-05-02",
                },
            }
        ),
        encoding="utf-8",
    )
    payload = client.get(f"/api/tasks/{task_id}/results").json()
    assert payload["scheme"]["status"] == "frozen"
    assert payload["scheme"]["parameter_delta"] == {}
    assert payload["scheme"]["adopted_parameter_delta"] == {}
    assert payload["scheme"]["candidate_scheme_id"] == candidate_id
    assert payload["scheme"]["candidate_parameter_delta"][changed_key] == pytest.approx(0.01)
    assert payload["optimize"]["strategy_id"] == "xaj-peak-bias-v1"
    assert payload["forecasts"]
    assert payload["metrics"]["NSE"] is not None
    assert payload["report_artifacts"]
    assert payload["test_hydrograph"]["kind"] == "independent_test"
    assert payload["test_hydrograph"]["calibrated"] is False
    assert "独立检验" in payload["test_hydrograph"]["title"]
    assert payload["test_hydrograph"]["gate_status"] == "KEEP"
    assert payload["test_hydrograph"]["frozen_metrics"]["window"] == "final_test"
    assert payload["test_hydrograph"]["frozen_metrics"]["start_date"] == "2020-05-01"
