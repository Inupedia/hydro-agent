from __future__ import annotations

import os
from pathlib import Path

from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.api.deps import AppDependencies


def build_product_calibration_runtime(deps: AppDependencies, task_id: str) -> AgentRuntime:
    """Build the task-scoped hydrologist calibration runtime used by the product API.

    Real product tasks with a reviewed model plan must come through this factory.
    It deliberately bypasses the legacy generic RealWorkbenchKernel runtime so the
    web product and the protocol/E2E experiments execute the same phase-aware method.
    """

    from hydro_agent.agent.providers.siliconflow import SiliconFlowDecisionProvider
    from hydro_agent.llm.settings import LLMSettings
    from hydro_agent.workbench.calibration import (
        CalibrationWorkbenchKernel,
        HydrologistProtocolDecisionProvider,
    )

    state = deps.repository.ensure_task_state(task_id)
    if not state.current_scheme_id:
        raise RuntimeError("当前任务没有可运行方案")
    scheme_row = deps.repository.get_scheme(state.current_scheme_id)
    config = dict(scheme_row.config_json or {})
    plan_id = str(config.get("model_plan_id") or "")
    if not plan_id:
        raise RuntimeError("真实率定任务缺少已复核模型方案")
    if deps.model_plans is None:
        raise RuntimeError("模型方案服务不可用")

    plan = deps.model_plans.require_ready(plan_id)
    if plan.get("content_hash") != config.get("model_plan_hash"):
        raise RuntimeError("模型方案版本已经变化，请重新创建率定任务")
    if str(plan.get("model_mode") or "lumped") != str(config.get("model_mode") or "lumped"):
        raise RuntimeError("任务模型模式与已复核方案不一致")

    directory = deps.model_plans.directory(plan_id)
    source_dir = directory / "normalized"
    scheme_path = directory / "scheme.json"
    if not source_dir.is_dir() or not scheme_path.is_file():
        raise RuntimeError("模型方案缺少标准化率定输入")

    warmup_days = int(config.get("warmup_days") or 30)
    task_config = {
        **dict(config.get("workbench") or {}),
        "model_plan_id": plan_id,
        "model_mode": str(config.get("model_mode") or plan.get("model_mode") or "lumped"),
        "warmup_days": warmup_days,
    }
    deps.task_configs[task_id] = task_config

    report_root = Path(deps.report_root or "artifacts/workbench/reports")
    work_root = report_root.parent / "runtime" / task_id
    kernel = CalibrationWorkbenchKernel(
        repository=deps.repository,
        work_root=work_root,
        source_dir=source_dir,
        scheme_path=scheme_path,
        report_root=report_root,
        warmup_days=warmup_days,
    )
    tools = kernel.build_tools(task_configs=deps.task_configs)

    env_file = Path(os.getenv("HYDRO_AGENT_ENV_FILE", ".env"))
    settings = LLMSettings.from_env(env_file if env_file.exists() else None)
    llm = SiliconFlowDecisionProvider(settings=settings, skills=kernel.skills)

    class StreamingScientificDelegate:
        """The protocol calls this only when a scientific experiment choice is needed."""

        def decide(self, view):
            return llm.decide(
                view,
                on_delta=lambda token: deps.append_llm_trace(view.task.task_id, token),
            )

    protocol = HydrologistProtocolDecisionProvider(StreamingScientificDelegate())

    class TracingProtocolProvider:
        """Trace both deterministic protocol moves and LLM-owned scientific choices."""

        def decide(self, view):
            current_task_id = view.task.task_id
            round_state = deps.repository.ensure_task_state(current_task_id)
            round_number = round_state.agent_rounds_used + 1
            deps.begin_llm_trace(current_task_id, round_number=round_number)
            input_world = view.model_dump(mode="json")
            input_summary = (
                f"第 {round_number} 轮 · 协议阶段 {view.hydro.calibration_phase or '-'} · "
                f"任务阶段 {view.task.phase} · 方案 {view.scheme.scheme_id} · "
                f"安全动作 {[a.value for a in view.permissions.safe_actions]}"
            )
            try:
                decision = protocol.decide(view)
                deps.finish_llm_trace(current_task_id, action=decision.action.value)
                trace = deps.get_llm_trace(current_task_id)
                judgment = (
                    f"阶段={view.hydro.calibration_phase or view.task.phase}；"
                    f"决策={decision.action.value}/{decision.hypothesis.value}；"
                    f"策略={decision.strategy_id or '-'}；"
                    f"参数组={list(decision.param_groups or ())}；"
                    f"目标={decision.objective or '-'}；"
                    f"理由={decision.rationale_summary}"
                )
                deps.append_agent_round_log(
                    current_task_id,
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
                deps.finish_llm_trace(current_task_id, error=str(exc))
                deps.append_agent_round_log(
                    current_task_id,
                    {
                        "round_number": round_number,
                        "action": None,
                        "hypothesis": None,
                        "strategy_id": None,
                        "rationale_summary": "",
                        "llm_output": deps.get_llm_trace(current_task_id).text,
                        "input_summary_zh": input_summary,
                        "input_world_state": input_world,
                        "tool_status": "failed",
                        "tool_observations": [],
                        "tool_metrics": {},
                        "error": str(exc),
                    },
                )
                raise

    class LoggedCalibrationRuntime(AgentRuntime):
        def run_round(self, current_task_id: str):
            packet = super().run_round(current_task_id)
            deps.update_last_agent_round_log(
                current_task_id,
                tool_status=packet.status,
                tool_observations=list(packet.observations),
                tool_metrics=dict(packet.metrics),
            )
            return packet

    return LoggedCalibrationRuntime(
        deps.repository,
        provider=TracingProtocolProvider(),
        tools=tools,
        world_state=WorldStateBuilder(
            deps.repository,
            skills=kernel.skills,
            strategies=kernel.strategies,
        ),
        provider_name="hydrologist-protocol",
        provider_model=settings.model,
    )
