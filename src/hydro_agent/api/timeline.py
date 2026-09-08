from __future__ import annotations

from hydro_agent.agent.contracts import ActionCode


def timeline_label(action: str | None, status: str) -> str:
    if status == "blocked" or status == "BLOCK":
        return "当前任务受阻，需要人工处理"
    mapping = {
        (ActionCode.A01_CHECK_DATA.value, "succeeded"): "资料检查完成",
        (ActionCode.A01_CHECK_DATA.value, "failed"): "资料检查失败",
        (ActionCode.A01_CHECK_DATA.value, "running"): "正在检查资料",
        (ActionCode.A03_VALIDATE_SCHEME.value, "succeeded"): "方案校验完成",
        (ActionCode.A03_VALIDATE_SCHEME.value, "failed"): "方案校验失败",
        (ActionCode.A05_FORECAST.value, "succeeded"): "预报完成",
        (ActionCode.A05_FORECAST.value, "failed"): "预报失败",
        (ActionCode.A05_FORECAST.value, "running"): "正在运行水文模型",
        (ActionCode.A06_DIAGNOSE.value, "succeeded"): "预报诊断完成",
        (ActionCode.A06_DIAGNOSE.value, "failed"): "预报诊断失败",
        (ActionCode.A07_OPTIMIZE.value, "succeeded"): "有限参数优化完成",
        (ActionCode.A07_OPTIMIZE.value, "running"): "正在进行有限参数优化",
        (ActionCode.A08_GATE.value, "ACCEPT"): "候选方案通过 Gate",
        (ActionCode.A08_GATE.value, "KEEP"): "当前证据不足以支持更改，维持原方案",
        (ActionCode.A08_GATE.value, "ROLLBACK"): "候选方案因 Gate 未通过而撤销",
        (ActionCode.A09_RESOLVE.value, "ACCEPT"): "已接受候选方案",
        (ActionCode.A09_RESOLVE.value, "KEEP"): "当前证据不足以支持更改，维持原方案",
        (ActionCode.A09_RESOLVE.value, "ROLLBACK"): "已回退到原方案",
        (ActionCode.A10_FREEZE.value, "succeeded"): "方案已冻结",
        (ActionCode.A11_REPLAY.value, "succeeded"): "历史起报回放完成",
        (ActionCode.A11_REPLAY.value, "running"): "正在执行历史起报回放",
        (ActionCode.A12_EVALUATE_REPORT.value, "succeeded"): "只读评价与报告已生成",
        (ActionCode.A12_EVALUATE_REPORT.value, "running"): "正在生成只读评价与报告",
    }
    if action == ActionCode.A05_FORECAST.value and status not in ("succeeded", "failed"):
        return "正在运行水文模型"
    if action == ActionCode.A07_OPTIMIZE.value and status != "succeeded":
        return "正在进行有限参数优化"
    return mapping.get((action or "", status), "执行记录")
