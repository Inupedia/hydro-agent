#!/usr/bin/env python3
"""Start the Hydro-Agent workbench (API + optional bundled Vue UI)."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    EvidencePacket,
    ProblemHypothesis,
    WorldStateView,
)
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.tools import ToolRouter
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.api.app import create_app
from hydro_agent.api.deps import AppDependencies
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


class StubHandler:
    def __init__(self, repository, action: ActionCode, status: str = "succeeded", **extra):
        self.repository = repository
        self.action = action
        self.status = status
        self.extra = extra
        self.calls = 0

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        self.calls += 1
        if self.action == ActionCode.A10_FREEZE:
            task = self.repository.get_task(task_id)
            if task.phase == "B":
                self.repository.set_task_phase(task_id, "F")
        if self.action == ActionCode.A11_REPLAY:
            task = self.repository.get_task(task_id)
            if task.phase == "F":
                self.repository.set_task_phase(task_id, "E")
        if self.action == ActionCode.A12_EVALUATE_REPORT:
            self.repository.report_artifacts = getattr(self.repository, "report_artifacts", {})
        return EvidencePacket(
            evidence_id=f"ev-{self.action.value}-{task_id}-{self.calls}",
            task_id=task_id,
            action=self.action,
            status=self.status,  # type: ignore[arg-type]
            observations=self.extra.get("observations", (f"{self.action.value}_ok",)),
            metrics=self.extra.get("metrics", {}),
            gates=self.extra.get("gates", {}),
            artifact_ids=self.extra.get("artifact_ids", ()),
            new_information_hash=f"hash-{self.action.value}-{task_id}-{self.calls}",
        )


class DemoDecisionProvider:
    """Deterministic workbench demo path (no A01-A12 UI checkboxes)."""

    SEQUENCE = (
        AgentDecision(
            action=ActionCode.A05_FORECAST,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Run the base forecast.",
        ),
        AgentDecision(
            action=ActionCode.A07_OPTIMIZE,
            hypothesis=ProblemHypothesis.MODEL,
            strategy_id="xaj-bounded-v1",
            rationale_summary="Bounded calibration produces one candidate.",
        ),
        AgentDecision(
            action=ActionCode.A08_GATE,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Evaluate the candidate against Gate guardrails.",
        ),
        AgentDecision(
            action=ActionCode.A10_FREEZE,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Freeze the operational scheme.",
        ),
        AgentDecision(
            action=ActionCode.A11_REPLAY,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Replay historical issue times.",
        ),
        AgentDecision(
            action=ActionCode.A12_EVALUATE_REPORT,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="Generate read-only evaluation and report.",
        ),
    )

    def decide(self, view: WorldStateView) -> AgentDecision:
        used = view.budget.max_agent_rounds - view.budget.agent_rounds_remaining
        if used >= len(self.SEQUENCE):
            raise RuntimeError("demo decision sequence exhausted")
        return self.SEQUENCE[used]


def build_demo_tools(repository) -> ToolRouter:
    tools = ToolRouter()
    tools.register(ActionCode.A05_FORECAST, StubHandler(repository, ActionCode.A05_FORECAST))
    tools.register(ActionCode.A07_OPTIMIZE, StubHandler(repository, ActionCode.A07_OPTIMIZE))
    tools.register(
        ActionCode.A08_GATE,
        StubHandler(
            repository,
            ActionCode.A08_GATE,
            status="KEEP",
            observations=("gate_status=KEEP", "insufficient_primary_delta"),
            gates={"status": "KEEP"},
        ),
    )
    tools.register(
        ActionCode.A09_RESOLVE, StubHandler(repository, ActionCode.A09_RESOLVE, status="KEEP")
    )
    tools.register(ActionCode.A10_FREEZE, StubHandler(repository, ActionCode.A10_FREEZE))
    tools.register(ActionCode.A11_REPLAY, StubHandler(repository, ActionCode.A11_REPLAY))
    tools.register(
        ActionCode.A12_EVALUATE_REPORT,
        StubHandler(
            repository,
            ActionCode.A12_EVALUATE_REPORT,
            metrics={"NSE": 0.52, "KGE": 0.41, "MAE": 1.15, "Bias": -0.03},
            artifact_ids=("report.json", "report.md"),
        ),
    )
    return tools


def build_app(db_path: Path, report_root: Path, *, static_dir: Path | None = None):
    db = Database(f"sqlite+pysqlite:///{db_path}")
    db.create_schema()
    repository = HydroRepository(db)
    tools = build_demo_tools(repository)
    provider = DemoDecisionProvider()

    def runtime_factory():
        return AgentRuntime(
            repository,
            provider=provider,
            tools=tools,
            world_state=WorldStateBuilder(repository),
            provider_name="workbench-demo",
        )

    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "report.json").write_text(
        '{"NSE": 0.52, "KGE": 0.41, "MAE": 1.15, "Bias": -0.03}\n',
        encoding="utf-8",
    )
    (report_root / "report.md").write_text(
        "# Hydro-Agent Demo Report\n\nNSE / KGE / MAE / Bias are demo placeholders.\n",
        encoding="utf-8",
    )
    deps = AppDependencies(
        repository=repository,
        runtime_factory=runtime_factory,
        report_root=str(report_root),
    )
    return create_app(deps, static_dir=static_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("HYDRO_AGENT_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HYDRO_AGENT_PORT", "8000")))
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.getenv("HYDRO_AGENT_DB", "artifacts/workbench/hydro.db")),
    )
    parser.add_argument(
        "--reports",
        type=Path,
        default=Path(os.getenv("HYDRO_AGENT_REPORTS", "artifacts/workbench/reports")),
    )
    parser.add_argument(
        "--static",
        type=Path,
        default=Path(os.getenv("HYDRO_AGENT_STATIC", "web/dist")),
    )
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    static_dir = args.static if args.static.exists() else None
    app = build_app(args.db, args.reports, static_dir=static_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
