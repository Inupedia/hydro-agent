#!/usr/bin/env python3
"""Start the Hydro-Agent workbench (API + Archify UI).

Default: real SiliconFlow LLM + real XAJ when SILICONFLOW_API_KEY and source data exist.
Set HYDRO_AGENT_MODE=demo to force the stub path.
"""

from __future__ import annotations

import argparse
import logging
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
from hydro_agent.replay.freeze import FreezeService

logger = logging.getLogger("hydro_agent.workbench")


# --- demo fallback (only when HYDRO_AGENT_MODE=demo or real prerequisites missing) ---


class StubHandler:
    def __init__(
        self,
        repository,
        deps: AppDependencies,
        action: ActionCode,
        status: str = "succeeded",
        **extra,
    ):
        self.repository = repository
        self.deps = deps
        self.action = action
        self.status = status
        self.extra = extra
        self.calls = 0
        self._freeze = FreezeService(repository)

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        self.calls += 1
        observations = list(self.extra.get("observations", (f"{self.action.value}_ok",)))
        metrics = dict(self.extra.get("metrics", {}))
        gates = dict(self.extra.get("gates", {}))
        artifact_ids = tuple(self.extra.get("artifact_ids", ()))
        if self.action == ActionCode.A10_FREEZE:
            state = self.repository.ensure_task_state(task_id)
            frozen_id = self._freeze.freeze(
                task_id=task_id, source_scheme_id=state.current_scheme_id
            )
            task = self.repository.get_task(task_id)
            if task.phase == "B":
                self.repository.set_task_phase(task_id, "F")
            observations = (f"frozen_scheme_id={frozen_id}",)
        elif self.action == ActionCode.A11_REPLAY:
            task = self.repository.get_task(task_id)
            if task.phase == "F":
                self.repository.set_task_phase(task_id, "E")
        elif self.action == ActionCode.A12_EVALUATE_REPORT:
            self.deps.report_artifacts[task_id] = ("report.json", "report.md")
            self.deps.metrics_by_task[task_id] = {
                "NSE": 0.52,
                "KGE": 0.41,
                "MAE": 1.15,
                "Bias": -0.03,
            }
            metrics = dict(self.deps.metrics_by_task[task_id])
            artifact_ids = ("report.json", "report.md")
        return EvidencePacket(
            evidence_id=f"ev-{self.action.value}-{task_id}-{self.calls}",
            task_id=task_id,
            action=self.action,
            status=self.status,  # type: ignore[arg-type]
            observations=tuple(observations),
            metrics=metrics,
            gates=gates,
            artifact_ids=artifact_ids,
            new_information_hash=f"hash-{self.action.value}-{task_id}-{self.calls}",
        )


class DemoDecisionProvider:
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


def _build_demo(deps: AppDependencies, repository) -> None:
    tools = ToolRouter()
    tools.register(
        ActionCode.A05_FORECAST, StubHandler(repository, deps, ActionCode.A05_FORECAST)
    )
    tools.register(
        ActionCode.A07_OPTIMIZE, StubHandler(repository, deps, ActionCode.A07_OPTIMIZE)
    )
    tools.register(
        ActionCode.A08_GATE,
        StubHandler(
            repository,
            deps,
            ActionCode.A08_GATE,
            status="KEEP",
            observations=("保持原方案", "改进幅度未达到设定门槛"),
            gates={"status": "KEEP", "reason_code": "insufficient_primary_delta"},
        ),
    )
    tools.register(
        ActionCode.A09_RESOLVE,
        StubHandler(repository, deps, ActionCode.A09_RESOLVE, status="KEEP"),
    )
    tools.register(ActionCode.A10_FREEZE, StubHandler(repository, deps, ActionCode.A10_FREEZE))
    tools.register(ActionCode.A11_REPLAY, StubHandler(repository, deps, ActionCode.A11_REPLAY))
    tools.register(
        ActionCode.A12_EVALUATE_REPORT,
        StubHandler(
            repository,
            deps,
            ActionCode.A12_EVALUATE_REPORT,
            metrics={"NSE": 0.52, "KGE": 0.41, "MAE": 1.15, "Bias": -0.03},
            artifact_ids=("report.json", "report.md"),
        ),
    )
    provider = DemoDecisionProvider()

    def runtime_factory():
        return AgentRuntime(
            repository,
            provider=provider,
            tools=tools,
            world_state=WorldStateBuilder(repository),
            provider_name="workbench-demo",
        )

    deps.runtime_factory = runtime_factory
    deps.mode = "demo"
    deps.provider_model = None


def _can_run_real(source: Path, scheme: Path) -> tuple[bool, str]:
    if os.getenv("HYDRO_AGENT_MODE", "").lower() == "demo":
        return False, "HYDRO_AGENT_MODE=demo"
    if not source.exists():
        return False, f"missing source dir: {source}"
    if not scheme.exists():
        return False, f"missing scheme: {scheme}"
    try:
        from hydro_agent.llm.settings import LLMSettings

        settings = LLMSettings.from_env(
            env_file=Path(os.getenv("HYDRO_AGENT_ENV_FILE", ".env"))
        )
    except Exception as exc:  # noqa: BLE001 - surface config errors as demo fallback reason
        return False, f"LLM settings unavailable: {exc}"
    if not settings.api_key.get_secret_value().strip():
        return False, "SILICONFLOW_API_KEY empty"
    return True, settings.model


def _build_real(
    deps: AppDependencies,
    repository,
    *,
    work_root: Path,
    source: Path,
    scheme: Path,
    report_root: Path,
) -> str:
    from hydro_agent.agent.providers.siliconflow import SiliconFlowDecisionProvider
    from hydro_agent.llm.settings import LLMSettings
    from hydro_agent.workbench.real import RealWorkbenchKernel

    env_file = Path(os.getenv("HYDRO_AGENT_ENV_FILE", ".env"))
    settings = LLMSettings.from_env(env_file if env_file.exists() else None)
    base_provider = SiliconFlowDecisionProvider(settings=settings)

    class TracingProvider:
        def decide(self, view):
            task_id = view.task.task_id
            state = repository.ensure_task_state(task_id)
            round_number = state.agent_rounds_used + 1
            deps.begin_llm_trace(task_id, round_number=round_number)
            input_world = view.model_dump(mode="json")
            input_summary = (
                f"第 {round_number} 轮 · 阶段 {view.task.phase} · "
                f"方案 {view.scheme.scheme_id} · "
                f"可选动作 {[a.value for a in view.permissions.safe_actions]} · "
                f"已有证据 {[e.action.value for e in view.evidence_summary]}"
            )
            try:
                decision = base_provider.decide(
                    view, on_delta=lambda token: deps.append_llm_trace(task_id, token)
                )
                deps.finish_llm_trace(task_id, action=decision.action.value)
                trace = deps.get_llm_trace(task_id)
                judgment = (
                    f"发现：阶段{view.task.phase}，证据{[e.action.value for e in view.evidence_summary]}；"
                    f"依据：{view.hydro.diagnosis or view.hydro.experiment_history[-2:]}；"
                    f"决策：{decision.action.value}/{decision.hypothesis.value}"
                    f"{(' / '+decision.strategy_id) if decision.strategy_id else ''}；"
                    f"理由：{decision.rationale_summary}"
                )
                deps.append_agent_round_log(
                    task_id,
                    {
                        "round_number": round_number,
                        "action": decision.action.value,
                        "hypothesis": decision.hypothesis.value,
                        "strategy_id": decision.strategy_id,
                        "rationale_summary": decision.rationale_summary,
                        "llm_output": trace.text,
                        "input_summary_zh": input_summary,
                        "input_world_state": input_world,
                        "judgment_zh": judgment,
                        "tool_status": None,
                        "tool_observations": [],
                        "tool_metrics": {},
                        "error": None,
                    },
                )
                return decision
            except Exception as exc:
                deps.finish_llm_trace(task_id, error=str(exc))
                deps.append_agent_round_log(
                    task_id,
                    {
                        "round_number": round_number,
                        "action": None,
                        "hypothesis": None,
                        "strategy_id": None,
                        "rationale_summary": "",
                        "llm_output": deps.get_llm_trace(task_id).text,
                        "input_summary_zh": input_summary,
                        "input_world_state": input_world,
                        "tool_status": "failed",
                        "tool_observations": [],
                        "tool_metrics": {},
                        "error": str(exc),
                    },
                )
                raise

    provider = TracingProvider()
    kernel = RealWorkbenchKernel(
        repository=repository,
        work_root=work_root,
        source_dir=source,
        scheme_path=scheme,
        report_root=report_root,
        warmup_days=int(os.getenv("HYDRO_AGENT_WARMUP_DAYS", "30")),
    )
    tools = kernel.build_tools(task_configs=deps.task_configs)
    deps.base_scheme_config = kernel.scheme_config
    deps.mode = "real"
    deps.provider_model = settings.model

    class LoggedRuntime(AgentRuntime):
        def run_round(self, task_id: str):
            packet = super().run_round(task_id)
            deps.update_last_agent_round_log(
                task_id,
                tool_status=packet.status,
                tool_observations=list(packet.observations),
                tool_metrics=dict(packet.metrics),
            )
            return packet

    def runtime_factory():
        return LoggedRuntime(
            repository,
            provider=provider,
            tools=tools,
            world_state=WorldStateBuilder(
                repository,
                skills=kernel.skills,
                strategies=kernel.strategies,
            ),
            provider_name="siliconflow",
            provider_model=settings.model,
        )

    deps.runtime_factory = runtime_factory
    return settings.model


def build_app(
    db_path: Path,
    report_root: Path,
    *,
    static_dir: Path | None = None,
    work_root: Path | None = None,
    source_dir: Path | None = None,
    scheme_path: Path | None = None,
):
    db = Database(f"sqlite+pysqlite:///{db_path}")
    db.create_schema()
    repository = HydroRepository(db)
    deps = AppDependencies(
        repository=repository,
        runtime_factory=lambda: None,  # type: ignore[arg-type,return-value]
        report_root=str(report_root),
    )
    report_root.mkdir(parents=True, exist_ok=True)
    work_root = work_root or Path(os.getenv("HYDRO_AGENT_WORK_ROOT", "artifacts/workbench/runtime"))
    source = source_dir or Path(
        os.getenv("HYDRO_AGENT_SOURCE", "data/source/camels_13235000")
    )
    scheme = scheme_path or Path(
        os.getenv("HYDRO_AGENT_SCHEME", "tests/fixtures/xaj/lowman_scheme.json")
    )

    ok, detail = _can_run_real(source, scheme)
    if ok:
        model = _build_real(
            deps,
            repository,
            work_root=work_root,
            source=source,
            scheme=scheme,
            report_root=report_root,
        )
        logger.info("workbench mode=real provider=siliconflow model=%s", model)
    else:
        logger.warning("workbench falling back to demo (%s)", detail)
        _build_demo(deps, repository)
        (report_root / "report.json").write_text(
            '{"NSE": 0.52, "KGE": 0.41, "MAE": 1.15, "Bias": -0.03}\n',
            encoding="utf-8",
        )
        (report_root / "report.md").write_text(
            "# Demo report (not real XAJ / LLM)\n",
            encoding="utf-8",
        )

    return create_app(deps, static_dir=static_dir)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
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
