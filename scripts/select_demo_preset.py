"""Select an explicitly development-tuned demo; final-test is read only once.

Uses the real DEM/XAJ/tool stack with a deterministic decision provider, not an
LLM performance claim. Does not change model parameters or Gate thresholds.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

# Run as `python scripts/select_demo_preset.py`; scripts/ is then on sys.path.
from smoke_yaogu_full_flow import wait_plan

from hydro_agent.agent.contracts import ActionCode
from hydro_agent.agent.permissions import pending_calibration_action
from hydro_agent.agent.providers.calibration_scientist import CalibrationScientistDecisionProvider
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.schemas import TaskCreateRequest
from hydro_agent.api.services import build_runtime_task_config, create_workbench_task
from hydro_agent.modeling.plans import ModelPlanService, PlanRequest, bundled_academy_root
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.workbench.calibration_scientist import CalibrationScientistWorkbenchKernel


def rank_demo_candidate(row: dict) -> tuple:
    """Prefer all-ACCEPT gates, then development NSE. Final-test must not rank."""
    gates = [action for action in row.get("actions") or [] if action.get("action") == "A06_GATE"]
    score = row.get("development_score")
    return (
        bool(gates) and all(action.get("status") == "ACCEPT" for action in gates),
        float("-inf") if score is None else float(score),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan-root", type=Path)
    parser.add_argument("--plan-id")
    parser.add_argument("--closeout-only", action="store_true")
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=args.closeout_only)
    plans = ModelPlanService(args.plan_root or root / "model-plans", bundled_academy_root())
    try:
        plan = (
            plans.get(args.plan_id)
            if args.plan_id
            else plans.create(
                PlanRequest(
                    basin_id="yaogu",
                    model_mode="lumped",
                    warmup_days=365,
                    resolution_m=90,
                    stream_area_km2=50,
                    unit_area_km2=50,
                )
            )
        )
        plan_id = str(plan["plan_id"])
        plan = wait_plan(plans, plan_id)
        if plan["status"] == "awaiting_review":
            plans.confirm(plan_id, str(plan["boundary_hash"]))
            plan = wait_plan(plans, plan_id)
        if plan["status"] != "ready":
            raise RuntimeError(f"plan not ready: {plan}")
        plan_dir = plans.directory(plan_id)
        db = Database(f"sqlite+pysqlite:///{root / 'hydro.db'}")
        db.create_schema()
        repo = HydroRepository(db)
        deps = AppDependencies(
            repository=repo,
            runtime_factory=lambda: None,
            report_root=str(root / "reports"),
            mode="real",
        )
        deps.model_plans = plans
        kernel = CalibrationScientistWorkbenchKernel(
            repository=repo,
            work_root=root / "runtime",
            source_dir=plan_dir / "normalized",
            scheme_path=plan_dir / "scheme.json",
            report_root=root / "reports",
            warmup_days=365,
        )
        world = WorldStateBuilder(repo, skills=kernel.skills, strategies=kernel.strategies)
        choices = [
            ("plan-default", str(plan["suggested_start"]), str(plan["suggested_end"])),
            ("ui-default", "1991-01-01", "1991-01-31"),
            ("wet-1991", "1991-04-01", "1991-08-31"),
            ("wet-2000", "2000-04-01", "2000-08-31"),
        ]
        runs = []
        if args.closeout_only:
            if not args.plan_id:
                raise ValueError("closeout requires the original prepared plan")
            runs = json.loads((root / "selection.json").read_text(encoding="utf-8"))
            choices = []
        runtimes = {}
        for name, start, end in choices:
            request = TaskCreateRequest(
                basin_id="yaogu",
                model_id="xaj",
                model_plan_id=plan_id,
                start_date=date.fromisoformat(start),
                end_date=date.fromisoformat(end),
                forcing_mode="R",
                base_scheme_id="scheme-base",
                allow_optimization=True,
                validation_days=30,
                final_test_days=30,
                max_agent_decision_rounds=30,
                max_optimization_cycles=4,
                campaign_mode="smoke",
                campaign_max_model_evaluations=800,
            )
            task_id = create_workbench_task(deps, request)
            runtime = AgentRuntime(
                repo,
                provider=CalibrationScientistDecisionProvider(),
                tools=kernel.build_tools(task_configs=deps.task_configs),
                world_state=world,
                provider_name="calibration-scientist-deterministic",
            )
            runtimes[task_id] = runtime
            row = dict(
                name=name,
                task_id=task_id,
                request=request.model_dump(mode="json"),
                actions=[],
                final_test_accessed=False,
            )
            print("START", name, task_id, flush=True)
            try:
                for _ in range(27):
                    view = world.build(task_id)
                    if view.hydro.campaign.stop_reason and pending_calibration_action(view) is None:
                        break
                    packet = runtime.run_round(task_id)
                    if packet.action in (
                        ActionCode.A08_FREEZE,
                        ActionCode.A09_REPLAY,
                        ActionCode.A10_EVALUATE_REPORT,
                    ):
                        raise RuntimeError("selection must stop before final-test closeout")
                    row["actions"].append(
                        dict(
                            action=packet.action.value,
                            status=packet.status,
                            metrics=dict(packet.metrics),
                            gates=dict(packet.gates),
                        )
                    )
                    print("ACTION", name, packet.action.value, packet.status, flush=True)
                row["campaign"] = world.build(task_id).hydro.campaign.model_dump(mode="json")
                row["development_score"] = row["campaign"]["selected_primary_score"]
                row["adopted"] = any(
                    a["gates"].get("candidate_adopted") == "true" for a in row["actions"]
                )
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            runs.append(row)
            (root / "selection.json").write_text(
                json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                "RESULT",
                name,
                {k: v for k, v in row.items() if k not in ("actions", "request")},
                flush=True,
            )
        eligible = [
            r
            for r in runs
            if not r.get("error")
            and r.get("adopted")
            and r.get("development_score") is not None
            and r["campaign"]["stop_reason"]
        ]
        if not eligible:
            raise RuntimeError("No adopted demo configuration; defaults remain unchanged")

        # For a live demo, prefer all candidates passing Gate over a higher
        # score with a later rollback. Rank only by development evidence.
        winner = max(eligible, key=rank_demo_candidate)
        # Selection is now immutable. Final evaluation cannot change the winner.
        (root / "demo-default.json").write_text(
            json.dumps(winner, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("SELECTED", winner["name"], winner["development_score"], flush=True)
        if args.closeout_only:
            task_id = winner["task_id"]
            if any(
                r.action == ActionCode.A10_EVALUATE_REPORT.value
                for r in repo.list_evidence(task_id)
            ):
                raise RuntimeError("final-test was already consumed; do not run it twice")
            state = repo.ensure_task_state(task_id)
            cfg = repo.get_scheme(state.current_scheme_id).config_json
            deps.task_configs[task_id] = build_runtime_task_config(
                cfg["workbench"], model_plan_id=plan_id
            )
            runtimes[task_id] = AgentRuntime(
                repo,
                provider=CalibrationScientistDecisionProvider(),
                tools=kernel.build_tools(task_configs=deps.task_configs),
                world_state=world,
                provider_name="calibration-scientist-deterministic",
            )
        runtime = runtimes[winner["task_id"]]
        for _ in range(3):
            packet = runtime.run_round(winner["task_id"])
            print("FINAL", packet.action.value, packet.status, dict(packet.metrics), flush=True)
            if packet.status == "blocked":
                raise RuntimeError("selected demo closeout blocked")
        print("OUTPUT", root, flush=True)
    finally:
        plans.pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
