# 规范评定调用链

`StandardRepository → GbtAccuracyConfig → deterministic evaluator → GbtAccuracyReport → Gate policy`

标准定义“怎么算、如何分级”；科研 policy 定义“本课题何时允许进入下一状态”。二者都不能由 Skill 内容覆盖。

如果缺少标准评定报告，应按项目 policy 处理（当前研究策略为 KEEP），不能退化成 Skill 内的 NSE fallback。