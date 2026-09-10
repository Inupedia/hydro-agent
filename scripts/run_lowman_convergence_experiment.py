#!/usr/bin/env python3
"""Run Lowman XAJ calibration with convergence-controlled Agent Gate.

Three disjoint data roles are enforced:
1. multi-year calibration period: numerical parameter search;
2. multi-year development Gate: iterative Agent feedback + convergence curve;
3. final holdout flood period: visible only after freeze/replay/evaluate.

`max_opt_cycles` and `max_rounds` are hard safety ceilings. Normal stopping is
scientific convergence of held-out development NSE/GB&T skill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from hydro_agent.agent.providers.siliconflow import SiliconFlowDecisionProvider
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.llm.settings import LLMSettings
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.workbench.convergence import (
    ConvergenceDecisionProvider,
    ConvergenceWorkbenchKernel,
)

TASK_ID = "lowman-convergence-e2e"
BASIN_ID = "camels_13235000"


def stable_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TracingProvider:
    def __init__(self, provider, traces: list[dict]):
        self.provider = provider
        self.traces = traces

    def decide(self, view):
        decision = self.provider.decide(view)
        self.traces.append(
            {
                "round": view.budget.max_agent_rounds - view.budget.agent_rounds_remaining + 1,
                "phase": view.task.phase,
                "scheme_id": view.scheme.scheme_id,
                "safe_actions": [a.value for a in view.permissions.safe_actions],
                "budget": view.budget.model_dump(mode="json"),
                "hydro": view.hydro.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            }
        )
        return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/source/camels_13235000"))
    parser.add_argument("--scheme", type=Path, default=Path("tests/fixtures/xaj/lowman_scheme.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/lowman-convergence-e2e"))
    parser.add_argument("--calibration-start", default="2011-01-01")
    parser.add_argument("--calibration-end", default="2017-12-31")
    parser.add_argument("--gate-start", default="2018-01-01")
    parser.add_argument("--gate-end", default="2019-12-31")
    parser.add_argument("--final-start", default="2020-04-01")
    parser.add_argument("--final-end", default="2020-07-31")
    parser.add_argument("--warmup-days", type=int, default=365)
    parser.add_argument("--diagnostic-days", type=int, default=60)
    parser.add_argument("--max-rounds", type=int, default=100)
    parser.add_argument("--max-opt-cycles", type=int, default=20)
    args = parser.parse_args()

    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True, exist_ok=True)

    scheme = json.loads(args.scheme.read_text(encoding="utf-8"))
    scheme["warmup_days"] = args.warmup_days
    scheme.setdefault("model_id", "xaj")
    scheme["workbench"] = {
        **dict(scheme.get("workbench") or {}),
        "allow_optimization": True,
        "max_agent_decision_rounds": args.max_rounds,
        "max_optimization_cycles": args.max_opt_cycles,
        "calibration_start_date": args.calibration_start,
        "calibration_end_date": args.calibration_end,
        "gate_start_date": args.gate_start,
        "gate_end_date": args.gate_end,
        "start_date": args.final_start,
        "end_date": args.final_end,
        "experiment": "lowman-long-period-convergence-gate",
    }

    db = Database(f"sqlite+pysqlite:///{args.output / 'hydro.db'}")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id=TASK_ID, basin_id=BASIN_ID, phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id=TASK_ID,
        model_id="xaj",
        status="base",
        config=scheme,
        content_hash=stable_hash(scheme),
    )
    repo.ensure_task_state(TASK_ID, current_scheme_id="scheme-base")

    task_configs = {
        TASK_ID: {
            "calibration_start_date": args.calibration_start,
            "calibration_end_date": args.calibration_end,
            "gate_start_date": args.gate_start,
            "gate_end_date": args.gate_end,
            "start_date": args.final_start,
            "end_date": args.final_end,
            "model_id": "xaj",
        }
    }
    kernel = ConvergenceWorkbenchKernel(
        repository=repo,
        work_root=args.output / "runtime",
        source_dir=args.source,
        scheme_path=args.scheme,
        report_root=args.output / "reports",
        warmup_days=args.warmup_days,
        diagnostic_days=args.diagnostic_days,
        history_days=max(args.warmup_days + args.diagnostic_days + 10, 450),
    )
    tools = kernel.build_tools(task_configs=task_configs)
    traces: list[dict] = []
    settings = LLMSettings.from_env(None)
    live = SiliconFlowDecisionProvider(settings=settings, skills=kernel.skills)
    provider = TracingProvider(ConvergenceDecisionProvider(live), traces)
    world = WorldStateBuilder(repo, skills=kernel.skills, strategies=kernel.strategies)
    runtime = AgentRuntime(
        repo,
        provider=provider,
        tools=tools,
        world_state=world,
        provider_name="siliconflow-convergence",
        provider_model=settings.model,
    )

    error: str | None = None
    for _ in range(args.max_rounds + 8):
        state = repo.get_task_state(TASK_ID)
        if not state.needs_follow_up:
            break
        try:
            packet = runtime.run_round(TASK_ID)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            break
        if traces:
            traces[-1]["evidence"] = packet.model_dump(mode="json")
            after = repo.get_task_state(TASK_ID)
            traces[-1]["state_after"] = {
                "phase": repo.get_task(TASK_ID).phase,
                "current_scheme_id": after.current_scheme_id,
                "agent_rounds_used": after.agent_rounds_used,
                "optimization_cycles_used": after.optimization_cycles_used,
                "needs_follow_up": after.needs_follow_up,
            }

    state = repo.get_task_state(TASK_ID)
    task = repo.get_task(TASK_ID)
    evidence = repo.list_evidence(TASK_ID)
    decisions = repo.list_agent_decisions(TASK_ID)
    schemes = repo.list_schemes(TASK_ID)

    gate_curve = []
    stop_status = None
    for row in evidence:
        if row.action != "A08_GATE":
            continue
        metrics = dict(row.metrics_json or {})
        status = str((row.gates_json or {}).get("status") or row.status)
        gate_curve.append(
            {
                "status": status,
                "base_nse": metrics.get("base_primary"),
                "candidate_nse": metrics.get("candidate_primary"),
                "best_nse": metrics.get("best_primary"),
                "delta_nse": metrics.get("primary_delta"),
                "slope": metrics.get("convergence_slope"),
                "window_gain": metrics.get("convergence_gain"),
                "window_span": metrics.get("convergence_span"),
                "gbt_dc": metrics.get("DC"),
                "gbt_qr": metrics.get("QR"),
                "candidate_kge": metrics.get("candidate_continuous_kge"),
                "candidate_bias": metrics.get("candidate_continuous_bias"),
                "candidate_peak_ratio": metrics.get("candidate_peak_ratio"),
                "candidate_flood_volume_bias_q90": metrics.get("candidate_flood_volume_bias_q90"),
            }
        )
        if status in {"ACCEPT", "CONVERGED", "STRUCTURAL_LIMIT"}:
            stop_status = status

    scheme_dump = []
    for row in schemes:
        cfg = dict(row.config_json or {})
        scheme_dump.append(
            {
                "scheme_id": row.scheme_id,
                "status": row.status,
                "parameters": cfg.get("parameters") or {},
                "provenance": cfg.get("provenance") or {},
            }
        )

    summary = {
        "experiment": "Lowman / long-period calibration / convergence Gate / final flood holdout",
        "model": settings.model,
        "calibration_window": [args.calibration_start, args.calibration_end],
        "gate_development_window": [args.gate_start, args.gate_end],
        "final_holdout_window": [args.final_start, args.final_end],
        "warmup_days": args.warmup_days,
        "round_hard_limit": args.max_rounds,
        "optimization_hard_limit": args.max_opt_cycles,
        "rounds_used": state.agent_rounds_used,
        "optimization_cycles_used": state.optimization_cycles_used,
        "phase": task.phase,
        "current_scheme_id": state.current_scheme_id,
        "needs_follow_up": state.needs_follow_up,
        "terminal": not state.needs_follow_up and error is None,
        "gate_stop_status": stop_status,
        "gate_curve": gate_curve,
        "actions": [row.action for row in evidence],
        "decision_count": len(decisions),
        "schemes": scheme_dump,
        "error": error,
    }
    (args.output / "agent-trace.json").write_text(
        json.dumps(traces, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output / "summary.md").write_text(
        "# Lowman convergence-controlled XAJ experiment\n\n"
        f"- calibration: `{args.calibration_start}..{args.calibration_end}`\n"
        f"- Gate development: `{args.gate_start}..{args.gate_end}`\n"
        f"- final holdout: `{args.final_start}..{args.final_end}`\n"
        f"- Agent rounds: `{state.agent_rounds_used}/{args.max_rounds}` (hard ceiling)\n"
        f"- optimization cycles: `{state.optimization_cycles_used}/{args.max_opt_cycles}` (hard ceiling)\n"
        f"- Gate stop status: `{stop_status}`\n"
        f"- Gate NSE curve: `{gate_curve}`\n"
        f"- final phase: `{task.phase}`\n"
        f"- error: `{error}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
