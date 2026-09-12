#!/usr/bin/env python3
"""Run the real bundled Yaogu XAJ path through model-plan, Agent actions and knowledge Gate.

This smoke intentionally uses the user-supplied Yaogu academy materials and the vendored
teacher XAJ kernel. It does not call an LLM: a scripted provider is used so the test isolates
whether the deterministic hydrology/data/knowledge execution path itself is runnable.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import date
from pathlib import Path

from hydro_agent.agent.contracts import ActionCode, AgentDecision, ProblemHypothesis
from hydro_agent.agent.providers.scripted import ScriptedDecisionProvider
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.schemas import TaskCreateRequest
from hydro_agent.api.services import create_workbench_task
from hydro_agent.knowledge import KnowledgeRepository
from hydro_agent.modeling.plans import ModelPlanService, PlanRequest, bundled_academy_root
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.workbench.real import RealWorkbenchKernel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "yaogu-flow-smoke"
PLAN_ROOT = OUT / "model-plans"
DB_PATH = OUT / "hydro.db"
REPORT_ROOT = OUT / "reports"
WORK_ROOT = OUT / "runtime"


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


def decisions() -> list[AgentDecision]:
    return [
        AgentDecision(
            action=ActionCode.A03_VALIDATE_SCHEME,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Validate the generated Yaogu XAJ scheme.",
        ),
        AgentDecision(
            action=ActionCode.A05_FORECAST,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Run a real Yaogu forecast from the teacher XAJ kernel.",
        ),
        AgentDecision(
            action=ActionCode.A06_DIAGNOSE,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Diagnose the real forecast before calibration.",
        ),
        AgentDecision(
            action=ActionCode.A07_OPTIMIZE,
            hypothesis=ProblemHypothesis.MODEL,
            strategy_id="xaj-bounded-v1",
            param_groups=("evap", "runoff", "routing"),
            objective="nse",
            rationale_summary="Run bounded XAJ calibration on the legal pre-validation window.",
        ),
        AgentDecision(
            action=ActionCode.A08_GATE,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Evaluate the Yaogu candidate with aligned validation forecasts and GB/T knowledge.",
        ),
        AgentDecision(
            action=ActionCode.A09_RESOLVE,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Apply ACCEPT/KEEP/ROLLBACK without bypassing the standard report.",
        ),
        AgentDecision(
            action=ActionCode.A10_FREEZE,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Freeze the resolved scheme for replay.",
        ),
        AgentDecision(
            action=ActionCode.A11_REPLAY,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Replay the frozen Yaogu scheme across the validation issue dates.",
        ),
        AgentDecision(
            action=ActionCode.A12_EVALUATE_REPORT,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Run read-only final evaluation and report generation.",
        ),
    ]


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

        # Ten issued days are enough to exercise aligned lead-1/2/3 Gate statistics,
        # while remaining comfortably inside the bundled 1989-2003 daily record.
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
        kernel = RealWorkbenchKernel(
            repository=repository,
            work_root=WORK_ROOT,
            source_dir=plan_dir / "normalized",
            scheme_path=plan_dir / "scheme.json",
            report_root=REPORT_ROOT,
            warmup_days=warmup_days,
        )
        tools = kernel.build_tools(task_configs=deps.task_configs)
        provider = ScriptedDecisionProvider(decisions())
        runtime = AgentRuntime(
            repository,
            provider=provider,
            tools=tools,
            world_state=WorldStateBuilder(
                repository,
                skills=kernel.skills,
                strategies=kernel.strategies,
            ),
            provider_name="scripted-yaogu-smoke",
        )

        packets = []
        for expected in [item.action for item in decisions()]:
            packet = runtime.run_round(task_id)
            packets.append(packet)
            print(
                "ACTION",
                expected.value,
                "=>",
                packet.action.value,
                packet.status,
                json.dumps(dict(packet.metrics), ensure_ascii=False, allow_nan=False),
                flush=True,
            )
            if packet.action != expected:
                raise RuntimeError(f"expected {expected.value}, got {packet.action.value}")

        task = repository.get_task(task_id)
        state = repository.ensure_task_state(task_id)
        evidence = repository.list_evidence(task_id)
        gate_packet = next(packet for packet in packets if packet.action == ActionCode.A08_GATE)
        eval_packet = next(
            packet for packet in packets if packet.action == ActionCode.A12_EVALUATE_REPORT
        )
        knowledge = KnowledgeRepository()
        standard = knowledge.standard()
        policy = knowledge.policy()
        summary = {
            "ok": task.phase == "E" and eval_packet.status == "succeeded",
            "task_id": task_id,
            "phase": task.phase,
            "current_scheme_id": state.current_scheme_id,
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
                }
                for packet in packets
            ],
            "evidence_actions": [row.action for row in evidence],
            "gate": {
                "status": gate_packet.status,
                "metrics": dict(gate_packet.metrics),
                "gates": dict(gate_packet.gates),
            },
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
                "profile": knowledge.standard_profile(),
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
            raise RuntimeError("Yaogu full-flow smoke did not finish in E phase")
        return 0
    finally:
        plans.pool.shutdown(wait=True)


if __name__ == "__main__":
    raise SystemExit(main())
