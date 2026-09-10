#!/usr/bin/env python3
"""Run a real Lowman lumped-XAJ + SiliconFlow agent experiment.

The experiment is intentionally observation-only with respect to calibration policy:
it uses the repository's current skills/strategies unchanged, records every agent round,
and reports whether the current implementation can close the full flow within 20 rounds.
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
from hydro_agent.workbench.real import RealWorkbenchKernel

TASK_ID = "lowman-agent-e2e"
BASIN_ID = "camels_13235000"


def stable_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TracingProvider:
    def __init__(self, provider: SiliconFlowDecisionProvider, traces: list[dict]):
        self.provider = provider
        self.traces = traces

    def decide(self, view):
        deltas: list[str] = []
        decision = self.provider.decide(view, on_delta=deltas.append)
        self.traces.append(
            {
                "round": view.budget.max_agent_rounds - view.budget.agent_rounds_remaining + 1,
                "phase": view.task.phase,
                "scheme_id": view.scheme.scheme_id,
                "safe_actions": [a.value for a in view.permissions.safe_actions],
                "budget": view.budget.model_dump(mode="json"),
                "hydro": view.hydro.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "raw_llm_output": "".join(deltas),
            }
        )
        return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/source/camels_13235000"))
    parser.add_argument("--scheme", type=Path, default=Path("tests/fixtures/xaj/lowman_scheme.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/lowman-agent-e2e"))
    parser.add_argument("--start-date", default="2020-04-15")
    parser.add_argument("--end-date", default="2020-05-01")
    parser.add_argument("--warmup-days", type=int, default=90)
    parser.add_argument("--max-rounds", type=int, default=20)
    parser.add_argument("--max-opt-cycles", type=int, default=4)
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
        "start_date": args.start_date,
        "end_date": args.end_date,
        "experiment": "lowman-lumped-xaj-baseline",
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
            "start_date": args.start_date,
            "end_date": args.end_date,
            "model_id": "xaj",
        }
    }
    kernel = RealWorkbenchKernel(
        repository=repo,
        work_root=args.output / "runtime",
        source_dir=args.source,
        scheme_path=args.scheme,
        report_root=args.output / "reports",
        warmup_days=args.warmup_days,
    )
    tools = kernel.build_tools(task_configs=task_configs)
    traces: list[dict] = []
    settings = LLMSettings.from_env(None)
    provider = TracingProvider(
        SiliconFlowDecisionProvider(settings=settings, skills=kernel.skills), traces
    )
    world = WorldStateBuilder(repo, skills=kernel.skills, strategies=kernel.strategies)
    runtime = AgentRuntime(
        repo,
        provider=provider,
        tools=tools,
        world_state=world,
        provider_name="siliconflow",
        provider_model=settings.model,
    )

    error: str | None = None
    for _ in range(args.max_rounds):
        state = repo.get_task_state(TASK_ID)
        if not state.needs_follow_up:
            break
        try:
            packet = runtime.run_round(TASK_ID)
        except Exception as exc:  # keep all evidence for diagnosis
            error = f"{type(exc).__name__}: {exc}"
            break
        if traces:
            traces[-1]["evidence"] = packet.model_dump(mode="json")
            traces[-1]["state_after"] = {
                "phase": repo.get_task(TASK_ID).phase,
                "current_scheme_id": repo.get_task_state(TASK_ID).current_scheme_id,
                "agent_rounds_used": repo.get_task_state(TASK_ID).agent_rounds_used,
                "optimization_cycles_used": repo.get_task_state(TASK_ID).optimization_cycles_used,
                "needs_follow_up": repo.get_task_state(TASK_ID).needs_follow_up,
            }

    state = repo.get_task_state(TASK_ID)
    task = repo.get_task(TASK_ID)
    schemes = repo.list_schemes(TASK_ID)
    evidence = repo.list_evidence(TASK_ID)
    decisions = repo.list_agent_decisions(TASK_ID)

    diagnosis_nse = []
    gate_nse = []
    for row in evidence:
        if row.action == "A06_DIAGNOSE":
            metrics = dict(row.metrics_json or {})
            if "nse" in metrics:
                diagnosis_nse.append(float(metrics["nse"]))
        if row.action == "A08_GATE":
            metrics = dict(row.metrics_json or {})
            gate_nse.append(
                {
                    "status": row.status,
                    "base_primary": metrics.get("base_primary"),
                    "candidate_primary": metrics.get("candidate_primary"),
                    "primary_delta": metrics.get("primary_delta"),
                    "DC": metrics.get("DC"),
                    "QR": metrics.get("QR"),
                }
            )

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
        "experiment": "Lowman / CAMELS 13235000 / lumped XAJ / real SiliconFlow",
        "model": settings.model,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "warmup_days": args.warmup_days,
        "round_limit": args.max_rounds,
        "optimization_cycle_limit": args.max_opt_cycles,
        "rounds_used": state.agent_rounds_used,
        "optimization_cycles_used": state.optimization_cycles_used,
        "phase": task.phase,
        "current_scheme_id": state.current_scheme_id,
        "needs_follow_up": state.needs_follow_up,
        "terminal_within_round_limit": not state.needs_follow_up and error is None,
        "error": error,
        "diagnosis_nse_trajectory": diagnosis_nse,
        "gate_trajectory": gate_nse,
        "actions": [row.action for row in evidence],
        "decision_count": len(decisions),
        "schemes": scheme_dump,
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
        "# Lowman lumped-XAJ agent baseline\n\n"
        f"- model: `{settings.model}`\n"
        f"- rounds: `{state.agent_rounds_used}/{args.max_rounds}`\n"
        f"- optimization cycles: `{state.optimization_cycles_used}/{args.max_opt_cycles}`\n"
        f"- final phase: `{task.phase}`\n"
        f"- terminal within limit: `{summary['terminal_within_round_limit']}`\n"
        f"- diagnosis NSE trajectory: `{diagnosis_nse}`\n"
        f"- gate trajectory: `{gate_nse}`\n"
        f"- error: `{error}`\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
