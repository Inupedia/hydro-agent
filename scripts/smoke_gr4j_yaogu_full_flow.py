#!/usr/bin/env python3
"""Real Yaogu materials × source_verified GR4J full research-loop smoke.

Reuses a ready ModelPlan (academy forcing/flow) but binds the task to GR4J
defaults and product calibration (no allow_unverified_model_calibration).
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
from hydro_agent.models.registry import default_model_registry
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.skills import SkillRegistry
from hydro_agent.workbench.calibration_scientist import CalibrationScientistWorkbenchKernel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "gr4j-yaogu-flow-smoke"
PLAN_ROOT = OUT / "model-plans"
DB_PATH = OUT / "hydro.db"
REPORT_ROOT = OUT / "reports"
WORK_ROOT = OUT / "runtime"
# Prefer an already-built ready plan from the XAJ smoke if present.
LEGACY_PLAN = ROOT / "artifacts" / "yaogu-flow-smoke" / "model-plans"


def wait_plan(service: ModelPlanService, plan_id: str, *, timeout: float = 900.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        plan = service.get(plan_id)
        status = str(plan.get("status"))
        print("MODEL_PLAN", status, plan.get("current_stage"), flush=True)
        if status in {"awaiting_review", "ready", "failed"}:
            return plan
        time.sleep(2)
    raise TimeoutError(f"model plan {plan_id} did not finish within {timeout}s")


def resolve_ready_plan(plans: ModelPlanService) -> dict:
    if LEGACY_PLAN.is_dir():
        for path in sorted(LEGACY_PLAN.glob("plan-*/plan.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") == "ready" and payload.get("basin_id") == "yaogu":
                target = PLAN_ROOT / payload["plan_id"]
                if not target.exists():
                    PLAN_ROOT.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(path.parent, target)
                print("REUSE_PLAN", payload["plan_id"], flush=True)
                return plans.get(payload["plan_id"])
    plan = plans.create(
        PlanRequest(
            basin_id="yaogu",
            model_mode="lumped",
            warmup_days=365,
            resolution_m=90,
            stream_area_km2=50,
            unit_area_km2=50,
            name="GR4J 腰古真实流程",
        )
    )
    plan_id = str(plan["plan_id"])
    plan = wait_plan(plans, plan_id)
    if plan["status"] == "awaiting_review":
        plans.confirm(plan_id, str(plan["boundary_hash"]))
        plan = wait_plan(plans, plan_id)
    if plan["status"] != "ready":
        raise RuntimeError(f"plan not ready: {plan.get('status')} {plan.get('error')}")
    return plan


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    plugin = default_model_registry().get("gr4j")
    if (
        plugin.descriptor.validation_status != "source_verified"
        or not plugin.descriptor.supports_calibration
    ):
        raise RuntimeError("GR4J must be source_verified before this product-path smoke")

    plans = ModelPlanService(PLAN_ROOT, bundled_academy_root())
    plan = resolve_ready_plan(plans)
    plan_id = str(plan["plan_id"])
    plan_dir = plans.directory(plan_id)
    warmup_days = int(plan.get("config", {}).get("warmup_days") or 365)

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
        model_id="gr4j",
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
        name="GR4J 腰古真实率定烟雾",
    )
    task_id = create_workbench_task(deps, request)
    scheme = repository.get_scheme(f"{task_id}--scheme-base")
    view0 = WorldStateBuilder(repository, skills=deps.skills).build(task_id)
    print(
        "TASK",
        json.dumps(
            {
                "task_id": task_id,
                "model_id": scheme.model_id,
                "parameters": sorted((scheme.config_json or {}).get("parameters") or {}),
                "validation_status": view0.model.validation_status,
                "capabilities": list(view0.model.capabilities),
                "allow_optimization": view0.task.allow_optimization,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if "calibrate" not in view0.model.capabilities:
        raise RuntimeError("product path must advertise calibrate for source_verified GR4J")
    if set((scheme.config_json or {}).get("parameters") or {}) != {"X1", "X2", "X3", "X4"}:
        raise RuntimeError("GR4J task must bind X1–X4 defaults, not XAJ parameters")

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
                    "observations": list(packet.observations)[:8],
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
        raise RuntimeError("GR4J scientist did not close out within smoke resource limit")

    task = repository.get_task(task_id)
    state = repository.ensure_task_state(task_id)
    campaign = world_state.build(task_id).hydro.campaign
    actions = [p.action.value for p in packets]
    optimizations = [p for p in packets if p.action == ActionCode.A05_OPTIMIZE]
    gates = [p for p in packets if p.action == ActionCode.A06_GATE]
    summary = {
        "task_id": task_id,
        "plan_id": plan_id,
        "model_id": "gr4j",
        "phase": task.phase,
        "terminal_status": task.terminal_status,
        "current_scheme_id": state.current_scheme_id,
        "actions": actions,
        "optimize_count": len(optimizations),
        "gate_count": len(gates),
        "campaign": campaign.model_dump(mode="json"),
        "last_gate": dict(gates[-1].gates) if gates else {},
        "report_dir": str(REPORT_ROOT / task_id),
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)

    required = {
        ActionCode.A02_VALIDATE_SCHEME.value,
        ActionCode.A03_FORECAST.value,
        ActionCode.A04_DIAGNOSE.value,
        ActionCode.A05_OPTIMIZE.value,
        ActionCode.A06_GATE.value,
        ActionCode.A08_FREEZE.value,
        ActionCode.A09_REPLAY.value,
        ActionCode.A10_EVALUATE_REPORT.value,
    }
    missing = sorted(required - set(actions))
    if missing:
        raise RuntimeError(f"incomplete GR4J path, missing actions: {missing}")
    if not any(p.action == ActionCode.A05_OPTIMIZE and p.status == "succeeded" for p in packets):
        raise RuntimeError("GR4J formal calibration did not succeed")
    print("OK gr4j yaogu product-path smoke completed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
