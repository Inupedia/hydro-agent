#!/usr/bin/env python3
"""Real Yaogu calibration-scientist E2E smoke.

The smoke uses the user-supplied Yaogu academy materials, the vendored teacher
XAJ kernel, leakage-safe diagnostics, structured calibration plans, SCE-UA,
independent GB/T Gate, reflection/rollback, case memory, replay and evaluation.

For reproducibility this CI smoke uses the deterministic CalibrationScientist
policy provider rather than an external LLM. The provider obeys the same
WorldStateView -> AgentDecision contract as LLM providers.
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
from hydro_agent.knowledge import (
    CalibrationCase,
    CalibrationCaseMemory,
    KnowledgeRepository,
    lesson_from_gate,
)
from hydro_agent.modeling.plans import ModelPlanService, PlanRequest, bundled_academy_root
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.workbench.calibration_scientist import CalibrationScientistWorkbenchKernel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "yaogu-flow-smoke"
PLAN_ROOT = OUT / "model-plans"
DB_PATH = OUT / "hydro.db"
REPORT_ROOT = OUT / "reports"
WORK_ROOT = OUT / "runtime"
CASE_PATH = OUT / "knowledge" / "calibration-cases.jsonl"


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


def write_case_memory(repository, task_id: str) -> list[CalibrationCase]:
    """Convert A06→A07→A08 evidence triples into persistent calibration cases."""

    rows = repository.list_evidence(task_id)
    memory = CalibrationCaseMemory(CASE_PATH)
    cases: list[CalibrationCase] = []
    last_diagnosis = None
    pending_opt = None
    case_index = 0
    for row in rows:
        if row.action == ActionCode.A06_DIAGNOSE.value:
            last_diagnosis = row
            continue
        if row.action == ActionCode.A07_OPTIMIZE.value:
            pending_opt = (row, last_diagnosis)
            continue
        if row.action != ActionCode.A08_GATE.value or pending_opt is None:
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
        val_metrics = {
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
        case = CalibrationCase(
            case_id=f"{task_id}-case-{case_index:02d}",
            basin_id="yaogu",
            hypothesis=str(dgates.get("hypothesis") or "UNKNOWN"),
            phenomenon=str(dgates.get("phenomenon") or ""),
            strategy_id=str(ogates.get("strategy_id") or "unknown"),
            optimizer="sce-ua",
            param_groups=groups,
            objective=str(ogates.get("objective") or "nse"),
            calibration_metrics=cal_metrics,
            validation_metrics=val_metrics,
            gate_status=gate_status,
            parameter_delta=_parse_delta(ogates),
            lesson=lesson_from_gate(gate_status),
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
            # CI cannot visually click the map. We only auto-confirm the exact immutable
            # boundary hash after the builder's numerical boundary check has passed.
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

        request = TaskCreateRequest(
            basin_id="yaogu",
            model_id="xaj",
            start_date=date(2000, 5, 1),
            end_date=date(2000, 5, 10),
            forcing_mode="R",
            base_scheme_id="scheme-base",
            model_plan_id=plan_id,
            allow_optimization=True,
            max_agent_decision_rounds=20,
            max_optimization_cycles=4,
        )
        task_id = create_workbench_task(deps, request)
        kernel = CalibrationScientistWorkbenchKernel(
            repository=repository,
            work_root=WORK_ROOT,
            source_dir=plan_dir / "normalized",
            scheme_path=plan_dir / "scheme.json",
            report_root=REPORT_ROOT,
            warmup_days=warmup_days,
        )
        tools = kernel.build_tools(task_configs=deps.task_configs)
        provider = CalibrationScientistDecisionProvider(max_experiments=2)
        runtime = AgentRuntime(
            repository,
            provider=provider,
            tools=tools,
            world_state=WorldStateBuilder(
                repository,
                skills=kernel.skills,
                strategies=kernel.strategies,
            ),
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
            if packet.action == ActionCode.A12_EVALUATE_REPORT and packet.status == "succeeded":
                break
        else:
            raise RuntimeError("calibration scientist did not close out within 20 rounds")

        task = repository.get_task(task_id)
        state = repository.ensure_task_state(task_id)
        evidence = repository.list_evidence(task_id)
        gate_packets = [packet for packet in packets if packet.action == ActionCode.A08_GATE]
        eval_packet = next(
            packet for packet in packets if packet.action == ActionCode.A12_EVALUATE_REPORT
        )
        cases = write_case_memory(repository, task_id)
        knowledge = KnowledgeRepository()
        standard = knowledge.standard()
        policy = knowledge.policy()
        area_km2 = float(plan["area_km2"]) if plan.get("area_km2") is not None else None
        diagnoses = [packet for packet in packets if packet.action == ActionCode.A06_DIAGNOSE]
        optimizations = [packet for packet in packets if packet.action == ActionCode.A07_OPTIMIZE]
        strict_prevalidation = all(
            any("diagnostic_truth_strictly_precedes_validation=true" in obs for obs in packet.observations)
            for packet in diagnoses
        )
        summary = {
            "ok": (
                task.phase == "E"
                and eval_packet.status == "succeeded"
                and strict_prevalidation
                and bool(optimizations)
                and bool(cases)
            ),
            "task_id": task_id,
            "phase": task.phase,
            "current_scheme_id": state.current_scheme_id,
            "provider": "calibration-scientist-deterministic",
            "diagnostic_truth_strictly_precedes_validation": strict_prevalidation,
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
            "evaluation": {
                "status": eval_packet.status,
                "metrics": dict(eval_packet.metrics),
                "artifacts": list(eval_packet.artifact_ids),
            },
            "knowledge": {
                "standard_id": standard["standard_id"],
                "standard_status": standard["status"],
                "standard_effective_from": standard["effective_from"],
                "policy_id": policy["policy_id"],
                "policy_gate": policy["gate"],
                "profile": knowledge.gbt_accuracy_metadata(area_km2=area_km2),
                "provenance": knowledge.provenance(),
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
