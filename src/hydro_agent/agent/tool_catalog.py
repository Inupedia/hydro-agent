from __future__ import annotations

from dataclasses import asdict, dataclass

from hydro_agent.agent.contracts import ActionCode


@dataclass(frozen=True)
class ToolDescriptor:
    tool_id: str
    action: ActionCode
    tool_name: str
    tool_name_zh: str
    category: str
    description_zh: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["action"] = self.action.value
        return payload


TOOL_CATALOG: dict[ActionCode, ToolDescriptor] = {
    ActionCode.A01_CHECK_DATA: ToolDescriptor(
        "data.inspect",
        ActionCode.A01_CHECK_DATA,
        "Data Inspector",
        "数据检查工具",
        "data",
        "检查水文数据完整性、时间范围和基础质量。",
    ),
    ActionCode.A02_VALIDATE_SCHEME: ToolDescriptor(
        "scheme.validate",
        ActionCode.A02_VALIDATE_SCHEME,
        "Scheme Validator",
        "方案校验工具",
        "validation",
        "检查当前模型方案是否满足实验执行条件。",
    ),
    ActionCode.A03_FORECAST: ToolDescriptor(
        "hydrology.forecast",
        ActionCode.A03_FORECAST,
        "Hydrology Model Runner",
        "水文模型运行器",
        "model",
        "运行当前水文模型并生成模拟结果。",
    ),
    ActionCode.A04_DIAGNOSE: ToolDescriptor(
        "hydrology.diagnose",
        ActionCode.A04_DIAGNOSE,
        "Model Diagnostician",
        "模型诊断工具",
        "diagnosis",
        "基于模型输出和评价指标识别主要误差特征。",
    ),
    ActionCode.A05_OPTIMIZE: ToolDescriptor(
        "calibration.optimize",
        ActionCode.A05_OPTIMIZE,
        "Parameter Optimizer",
        "参数优化工具",
        "optimization",
        "按照 Agent 设计的实验方案执行参数搜索和模型计算。",
    ),
    ActionCode.A06_GATE: ToolDescriptor(
        "validation.gate",
        ActionCode.A06_GATE,
        "Validation Gate",
        "方案验证 Gate",
        "validation",
        "依据确定性评价条件判断候选方案是否可接受。",
    ),
    ActionCode.A07_RESOLVE: ToolDescriptor(
        "scheme.resolve",
        ActionCode.A07_RESOLVE,
        "Scheme Resolver",
        "方案决策工具",
        "governance",
        "根据验证结果执行接受、保留或回退。",
    ),
    ActionCode.A08_FREEZE: ToolDescriptor(
        "scheme.freeze",
        ActionCode.A08_FREEZE,
        "Scheme Freezer",
        "方案冻结工具",
        "governance",
        "固定最终候选方案及研究快照。",
    ),
    ActionCode.A09_REPLAY: ToolDescriptor(
        "replay.history",
        ActionCode.A09_REPLAY,
        "History Replayer",
        "历史回放工具",
        "replay",
        "使用独立历史数据验证方案表现。",
    ),
    ActionCode.A10_EVALUATE_REPORT: ToolDescriptor(
        "evaluation.report",
        ActionCode.A10_EVALUATE_REPORT,
        "Evaluation Reporter",
        "评价报告工具",
        "report",
        "汇总实验结果、指标、证据和最终结论。",
    ),
}


def tool_for_action(action: str | ActionCode | None) -> ToolDescriptor | None:
    if not action:
        return None
    try:
        return TOOL_CATALOG[ActionCode(str(action))]
    except (KeyError, ValueError):
        return None


def normalize_tool_status(status: str | None) -> str:
    value = str(status or "pending")
    if value in {"succeeded", "success"}:
        return "completed"
    if value in {"KEEP", "ACCEPT", "ROLLBACK"}:
        return "completed"
    if value in {"pending", "running", "completed", "failed", "blocked"}:
        return value
    return "pending"


def synthesize_tool_call(
    *,
    action: str | None,
    status: str | None,
    observations: list[object] | tuple[object, ...] = (),
    metrics: dict[str, object] | None = None,
    strategy_id: str | None = None,
    evidence_id: str | None = None,
    action_run_id: str | None = None,
    artifact_ids: list[str] | tuple[str, ...] = (),
    gates: dict[str, object] | None = None,
    error: str | None = None,
    trace_source: str = "evidence_inferred",
) -> dict[str, object] | None:
    descriptor = tool_for_action(action)
    if descriptor is None:
        return None
    input_summary: dict[str, object] = {}
    if strategy_id:
        input_summary["strategy_id"] = strategy_id
    for key in ("param_groups", "objective", "evaluation_budget"):
        if gates and gates.get(key) not in (None, ""):
            input_summary[key] = gates[key]
    output_summary: dict[str, object] = {}
    parsed_observations: dict[str, str] = {}
    for item in observations:
        text = str(item)
        if "=" in text:
            key, value = text.split("=", 1)
            parsed_observations[key.strip()] = value.strip()
    for key in ("optimizer", "evaluation_budget"):
        if parsed_observations.get(key):
            input_summary[key] = parsed_observations[key]
    for key in (
        "model_evaluations",
        "candidate_scheme_id",
        "adoption_status",
        "qualification_status",
    ):
        if parsed_observations.get(key):
            output_summary[key] = parsed_observations[key]
    if observations:
        output_summary["observations"] = [str(item) for item in observations[:6]]
    if error:
        output_summary["error"] = error
    return {
        "tool_call_id": f"{evidence_id or 'legacy'}:{descriptor.tool_id}",
        **descriptor.to_dict(),
        "trace_source": trace_source,
        "status": normalize_tool_status(status),
        "input_summary": input_summary,
        "output_summary": output_summary,
        "action_run_id": action_run_id,
        "evidence_id": evidence_id,
        "artifact_ids": list(artifact_ids),
        "metrics": {
            **dict(metrics or {}),
            **(
                {"model_evaluations": int(parsed_observations["model_evaluations"])}
                if parsed_observations.get("model_evaluations", "").isdigit()
                else {}
            ),
        },
    }
