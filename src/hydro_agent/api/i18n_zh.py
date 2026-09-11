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
