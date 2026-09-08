#!/usr/bin/env python3
"""Start the Hydro-Agent workbench API with a scripted local runtime."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, ProblemHypothesis
from hydro_agent.agent.providers.scripted import ScriptedDecisionProvider
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.tools import ToolRouter
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.api.app import create_app
from hydro_agent.api.deps import AppDependencies
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


class StubHandler:
    def __init__(self, action: ActionCode, status: str = "succeeded", **extra):
        self.action = action
        self.status = status
        self.extra = extra
        self.calls = 0

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        self.calls += 1
        return EvidencePacket(
            evidence_id=f"ev-{self.action.value}-{self.calls}",
            task_id=task_id,
            action=self.action,
            status=self.status,  # type: ignore[arg-type]
            observations=self.extra.get("observations", (f"{self.action.value}_ok",)),
            metrics=self.extra.get("metrics", {}),
            gates=self.extra.get("gates", {}),
            artifact_ids=self.extra.get("artifact_ids", ()),
            new_information_hash=f"hash-{self.action.value}-{self.calls}",
        )


def build_app(db_path: Path, report_root: Path):
    db = Database(f"sqlite+pysqlite:///{db_path}")
    db.create_schema()
    repository = HydroRepository(db)
    provider = ScriptedDecisionProvider(
        [
            AgentDecision(
                action=ActionCode.A05_FORECAST,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="forecast",
            ),
            AgentDecision(
                action=ActionCode.A09_RESOLVE,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="resolve",
            ),
        ]
    )
    tools = ToolRouter()
    tools.register(ActionCode.A05_FORECAST, StubHandler(ActionCode.A05_FORECAST))
    tools.register(ActionCode.A09_RESOLVE, StubHandler(ActionCode.A09_RESOLVE, status="KEEP"))

    def runtime_factory():
        return AgentRuntime(
            repository,
            provider=provider,
            tools=tools,
            world_state=WorldStateBuilder(repository),
            provider_name="scripted-api",
        )

    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "report.json").write_text('{"ok": true}\n', encoding="utf-8")
    (report_root / "report.md").write_text("# ok\n", encoding="utf-8")
    deps = AppDependencies(
        repository=repository,
        runtime_factory=runtime_factory,
        report_root=str(report_root),
    )
    return create_app(deps)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=Path("artifacts/workbench/hydro.db"))
    parser.add_argument("--reports", type=Path, default=Path("artifacts/workbench/reports"))
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    app = build_app(args.db, args.reports)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
