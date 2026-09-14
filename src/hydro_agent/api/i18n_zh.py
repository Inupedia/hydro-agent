from __future__ import annotations

from hydro_agent.workflow.definition import load_definition

STATUS_ZH = {
    "succeeded": "成功",
    "failed": "失败",
    "blocked": "阻断",
    "KEEP": "维持原方案",
    "ACCEPT": "接受候选方案",
    "ROLLBACK": "回退原方案",
    "running": "进行中",
    "completed": "已完成",
    "idle": "空闲",
    "created": "已创建",
    "paused": "已暂停",
}

PHASE_ZH = {"B": "基准构建", "F": "冻结回放", "E": "只读评估"}

SCHEME_STATUS_ZH = {
    "base": "基准方案",
    "candidate": "候选方案",
    "accepted": "已接受方案",
    "frozen": "冻结方案",
}

GATE_REASON_ZH = {
    "lead_1_guardrail": "第 1 日预见期 NSE 下降超过允许值",
    "lead_2_guardrail": "第 2 日预见期 NSE 下降超过允许值",
    "lead_3_guardrail": "第 3 日预见期 NSE 下降超过允许值",
    "lead_guardrail": "某预见期 NSE 下降超过允许值",
    "lead_1_high_flow_guardrail": "第 1 日预见期高峰误差恶化超过允许值",
    "lead_2_high_flow_guardrail": "第 2 日预见期高峰误差恶化超过允许值",
    "lead_3_high_flow_guardrail": "第 3 日预见期高峰误差恶化超过允许值",
    "high_flow_guardrail": "高峰流量误差恶化超过允许值",
    "insufficient_absolute_skill": "候选方案绝对技巧未达标",
    "insufficient_primary_skill": "候选方案主指标未达采用下限",
    "insufficient_primary_improvement": "主指标提升不足，维持原方案",
    "insufficient_gbt_scheme_grade": "GB/T 22482 方案等级未达最低要求",
    "missing_standard_evaluation": "缺少标准评价，资格未判定",
    "gbt_scheme_grade_ok": "GB/T 方案等级达标",
    "meaningful_primary_improvement": "主指标有实质提升",
    "primary_floor_ok": "主指标达到采用下限",
}


HYPOTHESIS_ZH = {
    "DATA": "资料",
    "TIMING": "时滞",
    "STATE": "状态",
    "FORCING": "强迫",
    "MODEL": "模型",
    "RESOURCE": "资源",
    "UNKNOWN": "未知",
}


def action_zh(code: str | None) -> str:
    if not code:
        return "未知动作"
    action = load_definition().action(code)
    if action is not None:
        return action.label_zh
    return code


def status_zh(value: str | None) -> str:
    if not value:
        return "未知"
    return STATUS_ZH.get(value, value)


def phase_zh(value: str | None) -> str:
    if not value:
        return "未知阶段"
    return PHASE_ZH.get(value, value)


def scheme_status_zh(value: str | None) -> str:
    if not value:
        return "未知"
    return SCHEME_STATUS_ZH.get(value, value)


def hypothesis_zh(value: str | None) -> str:
    if not value:
        return "未知"
    return HYPOTHESIS_ZH.get(value, value)


def gate_reason_zh(value: str | None) -> str:
    if not value:
        return "未知原因"
    code = str(value)
    if code in GATE_REASON_ZH:
        return GATE_REASON_ZH[code]
    if code.startswith("scheme_grade="):
        return f"方案等级为{code.split('=', 1)[1]}"
    if code.startswith("min_scheme_grade="):
        return f"要求最低等级{code.split('=', 1)[1]}"
    return code
