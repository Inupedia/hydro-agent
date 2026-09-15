# 诊断路由

诊断后按问题类型激活更窄的 Skill：

- 数据语义/整体技能异常 → `hydro-data-readiness`
- 水量偏差、蒸散发或径流总量 → `xaj-water-balance`
- 产流响应、源分配、洪峰形成量级 → `xaj-runoff-generation`
- 峰现、过程形状、退水、滞后 → `xaj-routing-diagnosis`
- 需要把假设变成数值实验 → `hydro-experiment-design`
- 需要协调 XAJ 一轮完整率定 → `xaj-calibration`

多个过程同时可疑时允许并列假设，但每轮实验尽量缩小可变参数组，便于归因。