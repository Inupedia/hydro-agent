#!/usr/bin/env python3
"""Real Yaogu calibration-scientist E2E smoke.

The smoke uses the user-supplied Yaogu academy materials, the vendored teacher
XAJ kernel, the same full-calibration diagnosis path as the product API, a
budget-aware numerical optimizer, independent development Gate and scientific
closeout semantics.

The short Yaogu smoke window is intentionally too small to establish formal
qualification or convergence. It uses a small model-execution budget only to
validate wiring. Budget exhaustion must be reported as not-converged; only after
that preregistered stop may the selected research result consume final-test once.
An unqualified research result must remain explicitly not approved for release.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import date
from pathlib import Path

from hydro_agent.agent.contracts import ActionCode
from hydro_agent.agent.providers.calibration_scientist import CalibrationScientistDecisionProvider
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.schemas import TaskCreateRequest
from hydro_agent.api.services import create_workbench_task
from hydro_agent.modeling.plans import ModelPlanService, PlanRequest, bundled_academy_root
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.research import CalibrationCase, CalibrationCaseMemory, lesson_from_gate
from hydro_agent.skills import SkillRegistry
from hydro_agent.standards import StandardRepository
from hydro_agent.workbench.calibration_scientist import CalibrationScientistWorkbenchKernel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "yaogu-flow-smoke"
PLAN_ROOT = OUT / "model-plans"
DB_PATH = OUT / "hydro.db"
REPORT_ROOT = OUT / "reports"
WORK_ROOT = OUT / "runtime"
CASE_PATH = OUT / "research" / "calibration-cases.jsonl"


def wait_plan(service: ModelPlanService, plan_id: str, *, timeout: float = 900.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        plan = service.get(plan_id)
        status = str(plan.get("status"))
        print(
            "MODEL_PLAN",
            status,
            plan.get("current_stage"),
            next(
                (
                    stage.get("detail")
                    for stage in plan.get("stages", [])
                    if stage.get("code") == plan.get("current_stage")
                ),
                "",
            ),
            flush=True,
        )
        if status in {"awaiting_review", "ready", "failed"}:
            return plan
        time.sleep(2)
    raise TimeoutError(f"model plan {plan_id} did not finish within {timeout}s")


def _parse_delta(gates: dict) -> dict[str, float]:
    raw = gates.get("parameter_delta_json")
    if not raw:
        return {}
    try:
        payload = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return {str(k): float(v) for k, v in payload.items() if isinstance(v, (int, float))}


def _has_observation(packet, expected: str) -> bool:
    return expected in tuple(packet.observations)


def write_case_memory(repository, task_id: str) -> list[CalibrationCase]:
    rows = repository.list_evidence(task_id)
    memory = CalibrationCaseMemory(CASE_PATH)
    cases: list[CalibrationCase] = []
    last_diagnosis = None
    pending_opt = None
    case_index = 0
    for row in rows:
        if row.action == ActionCode.A04_DIAGNOSE.value:
            last_diagnosis = row
            continue
        if row.action == ActionCode.A05_OPTIMIZE.value:
            pending_opt = (row, last_diagnosis)
            continue
        if row.action != ActionCode.A06_GATE.value or pending_opt is None:
            continue
        opt, diagnosis = pending_opt
        case_index += 1
        dgates = dict(diagnosis.gates_json or {}) if diagnosis is not None else {}
        ogates = dict(opt.gates_json or {})
        gate_gates = dict(row.gates_json or {})
        cal_metrics = {
            str(k): float(v)
            for k, v in dict(opt.metrics_json or {}).items()
            if isinstance(v, (int, float))
        }
        development_metrics = {
            str(k): float(v)
            for k, v in dict(row.metrics_json or {}).items()
            if isinstance(v, (int, float))
        }
        groups = tuple(
            item.strip()
            for item in str(ogates.get("param_groups") or "").split(",")
            if item.strip()
        )
        gate_status = str(gate_gates.get("status") or row.status)
        adoption_status = str(gate_gates.get("adoption_status") or "UNKNOWN")
        qualification_status = str(
            gate_gates.get("qualification_status") or "NOT_EVALUATED"
        )
        case = CalibrationCase(
            case_id=f"{task_id}-case-{case_index:02d}",
            basin_id="yaogu",
            hypothesis=str(dgates.get("hypothesis") or "UNKNOWN"),
            phenomenon=str(dgates.get("phenomenon") or ""),
            strategy_id=str(ogates.get("strategy_id") or "unknown"),
            optimizer=str(ogates.get("optimizer") or "unknown"),
            param_groups=groups,
            objective=str(ogates.get("objective_metric") or ogates.get("objective") or "nse"),
            calibration_metrics=cal_metrics,
            development_metrics=development_metrics,
            gate_status=gate_status,
            adoption_status=adoption_status,
            qualification_status=qualification_status,
            parameter_delta=_parse_delta(ogates),
            lesson=lesson_from_gate(
                gate_status,
                adoption_status=adoption_status,
                qualification_status=qualification_status,
            ),
        )
        memory.append(case)
        cases.append(case)
        pending_opt = None
    return cases


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    academy = bundled_academy_root()
    print("ACADEMY", academy, flush=True)

    plans = ModelPlanService(PLAN_ROOT, academy)
    try:
        created = plans.create(
            PlanRequest(
                basin_id="yaogu",
                model_mode="lumped",
                warmup_days=365,
                resolution_m=90,
                stream_area_km2=50,
                unit_area_km2=50,
            )
        )
        plan_id = str(created["plan_id"])
        plan = wait_plan(plans, plan_id)
        if plan.get("status") == "failed":
            raise RuntimeError(f"Yaogu model-plan failed before review: {plan.get('error')}")
        if plan.get("status") == "awaiting_review":
            plans.confirm(plan_id, str(plan["boundary_hash"]))
            plan = wait_plan(plans, plan_id)
        if plan.get("status") != "ready":
            raise RuntimeError(f"Yaogu model-plan did not become ready: {plan}")

        plan_dir = plans.directory(plan_id)
        scheme_payload = json.loads((plan_dir / "scheme.json").read_text(encoding="utf-8"))
        warmup_days = int(scheme_payload["warmup_days"])
        print(
            "MODEL_PLAN_READY",
            json.dumps(
                {
                    "plan_id": plan_id,
                    "area_km2": plan.get("area_km2"),
                    "unit_count": plan.get("unit_count"),
                    "suggested_start": plan.get("suggested_start"),
                    "suggested_end": plan.get("suggested_end"),
                    "content_hash": plan.get("content_hash"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        db = Database(f"sqlite+pysqlite:///{DB_PATH}")
        db.create_schema()
        repository = HydroRepository(db)
        deps = AppDependencies(
            repository=repository,
            runtime_factory=lambda: None,  # type: ignore[arg-type,return-value]
            report_root=str(REPORT_ROOT),
            mode="real",
        )
        deps.model_plans = plans
        deps.skills = SkillRegistry(repository=repository)

        request = TaskCreateRequest(
            basin_id="yaogu",
            model_id="xaj",
            start_date=date(2000, 5, 1),
            end_date=date(2000, 5, 10),
            forcing_mode="R",
            base_scheme_id="scheme-base",
            model_plan_id=plan_id,
            allow_optimization=True,
            validation_days=30,
            final_test_days=30,
            max_agent_decision_rounds=20,
            max_optimization_cycles=2,
            campaign_mode="smoke",
        )
        task_id = create_workbench_task(deps, request)
        task_config = deps.task_configs[task_id]
        protocol = {
            "mode": task_config.get("protocol_mode"),
            "calibration": (
                task_config.get("calibration_start_date"),
                task_config.get("calibration_end_date"),
            ),
            "development": (
                task_config.get("development_start_date"),
                task_config.get("development_end_date"),
            ),
            "final_test": (
                task_config.get("final_test_start_date"),
                task_config.get("final_test_end_date"),
            ),
            "runtime_gate_alias": (task_config.get("start_date"), task_config.get("end_date")),
            "calibration_history_days": task_config.get("calibration_history_days"),
        }
        expected_protocol = {
            "mode": "smoke",
            "calibration": ("2000-05-01", "2000-05-04"),
            "development": ("2000-05-05", "2000-05-07"),
            "final_test": ("2000-05-08", "2000-05-10"),
            "runtime_gate_alias": ("2000-05-05", "2000-05-07"),
            "calibration_history_days": 369,
        }
        protocol_ok = protocol == expected_protocol
        print("PROTOCOL", json.dumps(protocol, ensure_ascii=False), flush=True)
        if not protocol_ok:
            raise RuntimeError(
                f"unexpected Yaogu smoke protocol: actual={protocol!r} expected={expected_protocol!r}"
            )

        kernel = CalibrationScientistWorkbenchKernel(
            repository=repository,
            work_root=WORK_ROOT,
            source_dir=plan_dir / "normalized",
            scheme_path=plan_dir / "scheme.json",
            report_root=REPORT_ROOT,
            warmup_days=warmup_days,
        )
        tools = kernel.build_tools(task_configs=deps.task_configs)
        provider = CalibrationScientistDecisionProvider(repository=repository)
        world_state = WorldStateBuilder(
            repository,
            skills=kernel.skills,
            strategies=kernel.strategies,
        )
        runtime = AgentRuntime(
            repository,
            provider=provider,
            tools=tools,
            world_state=world_state,
            provider_name="calibration-scientist-deterministic",
        )

        packets = []
        for _ in range(20):
            packet = runtime.run_round(task_id)
            packets.append(packet)
            print(
                "ACTION",
                packet.action.value,
                packet.status,
                json.dumps(
                    {
                        "metrics": dict(packet.metrics),
                        "gates": dict(packet.gates),
                        "observations": list(packet.observations),
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                flush=True,
            )
            if packet.action == ActionCode.A10_EVALUATE_REPORT and packet.status == "succeeded":
                break
            if packet.action == ActionCode.A08_FREEZE and packet.status == "blocked":
                break
        else:
            raise RuntimeError("calibration scientist did not close out within smoke resource limit")

        task = repository.get_task(task_id)
        state = repository.ensure_task_state(task_id)
        campaign = world_state.build(task_id).hydro.campaign
        evidence = repository.list_evidence(task_id)
        gate_packets = [packet for packet in packets if packet.action == ActionCode.A06_GATE]
        cases = write_case_memory(repository, task_id)
        standards = StandardRepository()
        standard = standards.standard()
        policy = standards.policy()
        area_km2 = float(plan["area_km2"]) if plan.get("area_km2") is not None else None
        diagnoses = [packet for packet in packets if packet.action == ActionCode.A04_DIAGNOSE]
        optimizations = [packet for packet in packets if packet.action == ActionCode.A05_OPTIMIZE]
        freeze_packets = [packet for packet in packets if packet.action == ActionCode.A08_FREEZE]
        replay_packets = [packet for packet in packets if packet.action == ActionCode.A09_REPLAY]
        eval_packets = [packet for packet in packets if packet.action == ActionCode.A10_EVALUATE_REPORT]
        strict_predevelopment = all(
            any(
                "diagnostic_truth_strictly_precedes_development=true" in obs
                for obs in packet.observations
            )
            for packet in diagnoses
        )
        full_calibration_diagnosis = bool(diagnoses) and all(
            _has_observation(packet, "diagnosis_primary_evidence=continuous_calibration")
            and _has_observation(packet, "calibration_evidence_development_accessed=false")
            and _has_observation(packet, "calibration_evidence_final_test_accessed=false")
            for packet in diagnoses
        )
        optimization_protocol_safe = bool(optimizations) and all(
            _has_observation(packet, "development_window=2000-05-05..2000-05-07")
            and _has_observation(packet, "development_evaluated_by=A06_GATE")
            and _has_observation(packet, "final_test_accessed=false")
            for packet in optimizations
        )

        latest_gate_qualification = (
            str(gate_packets[-1].gates.get("qualification_status") or "NOT_EVALUATED")
            if gate_packets
            else "NOT_EVALUATED"
        )
        freeze_packet = freeze_packets[-1] if freeze_packets else None
        frozen_scheme = (
            repository.get_scheme(state.current_scheme_id)
            if state.current_scheme_id and task.phase in {"F", "E"}
            else None
        )
        frozen_closeout = (
            dict((frozen_scheme.config_json or {}).get("freeze_contract", {})).get(
                "research_closeout", {}
            )
            if frozen_scheme is not None
            else {}
        )
        smoke_budget_honest = (
            campaign.mode == "smoke"
            and campaign.stop_reason == "BUDGET_EXHAUSTED"
            and campaign.converged is False
            and campaign.trial_count == 2
        )
        research_closeout_safe = bool(
            freeze_packet
            and freeze_packet.status == "succeeded"
            and latest_gate_qualification != "QUALIFIED"
            and str(freeze_packet.gates.get("campaign_stop_reason")) == "BUDGET_EXHAUSTED"
            and str(freeze_packet.gates.get("release_approved")) == "false"
            and _has_observation(freeze_packet, "research_final_evaluation_enabled=true")
            and _has_observation(freeze_packet, "release_approved=false")
            and frozen_closeout.get("purpose") == "research_final_evaluation"
            and frozen_closeout.get("campaign_stop_reason") == "BUDGET_EXHAUSTED"
            and frozen_closeout.get("qualification_status") == "UNQUALIFIED"
            and frozen_closeout.get("release_approved") is False
            and frozen_closeout.get("final_test_access") == "read_only_after_freeze"
        )

        research_evidence_path = REPORT_ROOT / task_id / "research-evidence.json"
        final_test_consumed_once = bool(
            task.phase == "E"
            and len(replay_packets) == 1
            and len(eval_packets) == 1
            and research_evidence_path.exists()
            and _has_observation(replay_packets[0], "final_test_window=2000-05-08..2000-05-10")
            and _has_observation(eval_packets[0], "final_test_window=2000-05-08..2000-05-10")
            and _has_observation(eval_packets[0], "final_test_read_only=true")
            and _has_observation(eval_packets[0], "final_test_consumption=1/1")
        )

        summary = {
            "ok": (
                research_closeout_safe
                and final_test_consumed_once
                and strict_predevelopment
                and full_calibration_diagnosis
                and protocol_ok
                and optimization_protocol_safe
                and smoke_budget_honest
                and bool(optimizations)
                and bool(cases)
            ),
            "task_id": task_id,
            "phase": task.phase,
            "paused": bool(state.paused),
            "current_scheme_id": state.current_scheme_id,
            "provider": "calibration-scientist-deterministic",
            "protocol": protocol,
            "protocol_ok": protocol_ok,
            "diagnostic_truth_strictly_precedes_development": strict_predevelopment,
            "full_calibration_diagnosis": full_calibration_diagnosis,
            "optimization_protocol_safe": optimization_protocol_safe,
            "campaign": campaign.model_dump(mode="json"),
            "smoke_budget_honest": smoke_budget_honest,
            "research_closeout_safe": research_closeout_safe,
            "latest_gate_qualification": latest_gate_qualification,
            "release_approved": bool(frozen_closeout.get("release_approved", False)),
            "final_test_consumed_once": final_test_consumed_once,
            "research_evidence_exists": research_evidence_path.exists(),
            "model_plan": {
                "plan_id": plan_id,
                "area_km2": plan.get("area_km2"),
                "unit_count": plan.get("unit_count"),
                "content_hash": plan.get("content_hash"),
            },
            "actions": [
                {
                    "action": packet.action.value,
                    "status": packet.status,
                    "metrics": dict(packet.metrics),
                    "gates": dict(packet.gates),
                    "observations": list(packet.observations),
                }
                for packet in packets
            ],
            "evidence_actions": [row.action for row in evidence],
            "optimization_count": len(optimizations),
            "gate_history": [
                {
                    "status": packet.status,
                    "metrics": dict(packet.metrics),
                    "gates": dict(packet.gates),
                }
                for packet in gate_packets
            ],
            "calibration_cases": [case.model_dump(mode="json") for case in cases],
            "research_closeout": {
                "status": freeze_packet.status if freeze_packet is not None else None,
                "gates": dict(freeze_packet.gates) if freeze_packet is not None else {},
                "observations": list(freeze_packet.observations) if freeze_packet is not None else [],
                "frozen_contract": frozen_closeout,
            },
            "evaluation": (
                {
                    "status": eval_packets[-1].status,
                    "metrics": dict(eval_packets[-1].metrics),
                    "observations": list(eval_packets[-1].observations),
                }
                if eval_packets
                else None
            ),
            "knowledge": {
                "standard_id": standard["standard_id"],
                "standard_status": standard["status"],
                "standard_effective_from": standard["effective_from"],
                "policy_id": policy["policy_id"],
                "policy_gate": policy["gate"],
                "profile": standards.gbt_accuracy_metadata(area_km2=area_km2),
                "provenance": standards.provenance(),
            },
        }
        summary_path = OUT / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print("SUMMARY_PATH", summary_path, flush=True)
        print("SUMMARY", json.dumps(summary, ensure_ascii=False, allow_nan=False), flush=True)
        if not summary["ok"]:
            raise RuntimeError("Yaogu calibration-scientist smoke did not satisfy all assertions")
        return 0
    finally:
        plans.pool.shutdown(wait=True)


if __name__ == "__main__":
    raise SystemExit(main())
