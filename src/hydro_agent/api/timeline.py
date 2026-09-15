from __future__ import annotations

from hydro_agent.agent.contracts import ActionCode

_LEGACY_TO_CURRENT = {
    "A03_VALIDATE_SCHEME": ActionCode.A02_VALIDATE_SCHEME.value,
    "A05_FORECAST": ActionCode.A03_FORECAST.value,
    "A06_DIAGNOSE": ActionCode.A04_DIAGNOSE.value,
    "A07_OPTIMIZE": ActionCode.A05_OPTIMIZE.value,
    "A08_GATE": ActionCode.A06_GATE.value,
    "A09_RESOLVE": ActionCode.A07_RESOLVE.value,
    "A10_FREEZE": ActionCode.A08_FREEZE.value,
    "A11_REPLAY": ActionCode.A09_REPLAY.value,
    "A12_EVALUATE_REPORT": ActionCode.A10_EVALUATE_REPORT.value,
}


def timeline_label(action: str | None, status: str) -> str:
    action = _LEGACY_TO_CURRENT.get(action or "", action)
    if status == "blocked" or status == "BLOCK":
        if action == ActionCode.A08_FREEZE.value:
            return "收口条件未满足，继续自动循环"
        if action == ActionCode.A05_OPTIMIZE.value:
            return "优化步骤被阻断，等待下一轮决策"
        return "当前任务受阻，需要人工处理"
    mapping = {
        (ActionCode.A01_CHECK_DATA.value, "succeeded"): "资料检查完成",
        (ActionCode.A01_CHECK_DATA.value, "failed"): "资料检查失败",
        (ActionCode.A01_CHECK_DATA.value, "running"): "正在检查资料",
        (ActionCode.A02_VALIDATE_SCHEME.value, "succeeded"): "方案校验完成",
        (ActionCode.A02_VALIDATE_SCHEME.value, "failed"): "方案校验失败",
        (ActionCode.A03_FORECAST.value, "succeeded"): "预报完成",
        (ActionCode.A03_FORECAST.value, "failed"): "预报失败",
        (ActionCode.A03_FORECAST.value, "running"): "正在运行水文模型",
        (ActionCode.A04_DIAGNOSE.value, "succeeded"): "预报诊断完成",
        (ActionCode.A04_DIAGNOSE.value, "failed"): "预报诊断失败",
        (ActionCode.A05_OPTIMIZE.value, "succeeded"): "有限参数优化完成",
        (ActionCode.A05_OPTIMIZE.value, "running"): "正在进行有限参数优化",
        (ActionCode.A06_GATE.value, "ACCEPT"): "候选方案通过 Gate",
        (ActionCode.A06_GATE.value, "KEEP"): "候选有变化，但未达到采用条件",
        (ActionCode.A06_GATE.value, "ROLLBACK"): "候选方案因 Gate 未通过而撤销",
        (ActionCode.A07_RESOLVE.value, "ACCEPT"): "已接受候选方案",
        (ActionCode.A07_RESOLVE.value, "KEEP"): "候选未采纳，保留当前方案",
        (ActionCode.A07_RESOLVE.value, "ROLLBACK"): "已回退到原方案",
        (ActionCode.A08_FREEZE.value, "succeeded"): "方案已冻结",
        (ActionCode.A09_REPLAY.value, "succeeded"): "历史起报回放完成",
        (ActionCode.A09_REPLAY.value, "running"): "正在执行历史起报回放",
        (ActionCode.A10_EVALUATE_REPORT.value, "succeeded"): "只读评价与报告已生成",
        (ActionCode.A10_EVALUATE_REPORT.value, "running"): "正在生成只读评价与报告",
    }
    if action == ActionCode.A03_FORECAST.value and status not in ("succeeded", "failed"):
        return "正在运行水文模型"
    if action == ActionCode.A05_OPTIMIZE.value and status != "succeeded":
        return "正在进行有限参数优化"
    return mapping.get((action or "", status), "执行记录")
