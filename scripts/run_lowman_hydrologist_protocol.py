#!/usr/bin/env python3
"""Run the Lowman XAJ hydrologist-calibration protocol end to end.

Data roles are disjoint:
- 2011-2017 calibration: numerical parameter search;
- 2018-2019 development: phase Gate feedback and rework attribution;
- 2020 spring/summer final holdout: read only after Freeze.

Agent/optimization limits are safety ceilings. Normal progression and stopping are
controlled by hydrologic phase Gates and unique-experiment convergence evidence.
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
from hydro_agent.workbench.calibration import (
    CalibrationWorkbenchKernel,
    HydrologistProtocolDecisionProvider,
)

TASK_ID = "lowman-hydrologist-protocol"
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
                "task_phase": view.task.phase,
                "calibration_phase": view.hydro.calibration_phase,
                "scheme_id": view.scheme.scheme_id,
                "safe_actions": [a.value for a in view.permissions.safe_actions],
                "budget": view.budget.model_dump(mode="json"),
                "diagnosis": view.hydro.diagnosis,
                "phase_history": list(view.hydro.phase_history),
                "decision": decision.model_dump(mode="json"),
            }
        )
        return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/source/camels_13235000"))
    parser.add_argument("--scheme", type=Path, default=Path("tests/fixtures/xaj/lowman_scheme.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/lowman-hydrologist-protocol"))
    parser.add_argument("--calibration-start", default="2011-01-01")
    parser.add_argument("--calibration-end", default="2017-12-31")
    parser.add_argument("--development-start", default="2018-01-01")
    parser.add_argument("--development-end", default="2019-12-31")
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
        "gate_start_date": args.development_start,
        "gate_end_date": args.development_end,
        "start_date": args.final_start,
        "end_date": args.final_end,
        "experiment": "lowman-hydrologist-calibration-protocol",
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
            "gate_start_date": args.development_start,
            "gate_end_date": args.development_end,
            "start_date": args.final_start,
            "end_date": args.final_end,
            "model_id": "xaj",
        }
    }
    kernel = CalibrationWorkbenchKernel(
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
    provider = TracingProvider(HydrologistProtocolDecisionProvider(live), traces)
    world = WorldStateBuilder(repo, skills=kernel.skills, strategies=kernel.strategies)
    runtime = AgentRuntime(
        repo,
        provider=provider,
        tools=tools,
        world_state=world,
        provider_name="siliconflow-hydrologist-protocol",
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
                "task_phase": repo.get_task(TASK_ID).phase,
                "calibration_phase": kernel.protocol.phase_from_evidence(
                    repo.list_evidence(TASK_ID)
                ).value,
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

    gate_trace = []
    unique_experiments: set[str] = set()
    for row in evidence:
        if row.action != "A08_GATE":
            continue
        gates = dict(row.gates_json or {})
        metrics = dict(row.metrics_json or {})
        experiment_id = str(gates.get("experiment_id") or "")
        if experiment_id:
            unique_experiments.add(experiment_id)
        gate_trace.append(
            {
                "phase": gates.get("calibration_phase"),
                "status": gates.get("status") or row.status,
                "experiment_id": experiment_id,
                "return_phase": gates.get("return_phase") or None,
                "progress_metric": gates.get("progress_metric"),
                "progress_value": metrics.get("phase_progress_value"),
                "unique_points": metrics.get("convergence_unique_points"),
                "convergence_gain": metrics.get("convergence_gain"),
                "convergence_slope": metrics.get("convergence_slope"),
                "scheme_grade": gates.get("scheme_grade"),
                "candidate_nse": metrics.get("candidate_nse"),
                "candidate_kge": metrics.get("candidate_kge"),
                "candidate_volume_rel_error": metrics.get("candidate_volume_rel_error"),
                "candidate_event_peak_rel_error_median": metrics.get(
                    "candidate_event_peak_rel_error_median"
                ),
                "candidate_event_peak_timing_steps_median": metrics.get(
                    "candidate_event_peak_timing_steps_median"
                ),
            }
        )

    final_metrics = {}
    for row in reversed(evidence):
        if row.action == "A12_EVALUATE_REPORT":
            final_metrics = dict(row.metrics_json or {})
            break

    summary = {
        "experiment": "Lowman XAJ / hydrologist calibration protocol",
        "model": settings.model,
        "data_roles": {
            "calibration": [args.calibration_start, args.calibration_end],
            "development": [args.development_start, args.development_end],
            "final_holdout": [args.final_start, args.final_end],
        },
        "hard_ceilings": {
            "agent_rounds": args.max_rounds,
            "optimization_cycles": args.max_opt_cycles,
        },
        "rounds_used": state.agent_rounds_used,
        "optimization_cycles_used": state.optimization_cycles_used,
        "unique_calibration_experiments": len(
            [e for e in unique_experiments if not e.startswith("development-validation:")]
        ),
        "task_phase": task.phase,
        "calibration_phase": kernel.protocol.phase_from_evidence(evidence).value,
        "phase_history": list(kernel.protocol.phase_history(evidence)),
        "current_scheme_id": state.current_scheme_id,
        "terminal": not state.needs_follow_up and error is None,
        "gate_trace": gate_trace,
        "actions": [row.action for row in evidence],
        "decision_count": len(decisions),
        "scheme_count": len(schemes),
        "final_holdout_metrics": final_metrics,
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
        "# Lowman hydrologist calibration protocol\n\n"
        f"- calibration: `{args.calibration_start}..{args.calibration_end}`\n"
        f"- development: `{args.development_start}..{args.development_end}`\n"
        f"- final holdout: `{args.final_start}..{args.final_end}`\n"
        f"- Agent rounds: `{state.agent_rounds_used}/{args.max_rounds}` (hard ceiling)\n"
        f"- optimization experiments: `{state.optimization_cycles_used}/{args.max_opt_cycles}` (hard ceiling)\n"
        f"- unique Gate experiments: `{summary['unique_calibration_experiments']}`\n"
        f"- calibration phase: `{summary['calibration_phase']}`\n"
        f"- phase history: `{summary['phase_history']}`\n"
        f"- final holdout metrics: `{final_metrics}`\n"
        f"- error: `{error}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
