# HBV-light 参数语义（诊断用）

本表描述 Seibert & Vis HBV-light lumped Core（与 hydromad 对齐）。`K0` 仅在上层蓄量超过 `UZL` 时产生快流；`SFCF` 修正阈值温度以下的降雪量；`MAXBAS` 为连续三角权重长度。

| 组 | 参数 | 主要现象 |
| --- | --- | --- |
| snow | TT, CFMAX, SFCF, CFR, CWH | 融雪偏早/偏晚、降雪量偏差、春季洪峰形态 |
| soil | FC, BETA, LP | 长期水量偏差、蒸散发调节不足 |
| groundwater | K0, K1, K2, PERC, UZL | 快流阈值、基流偏高/偏低、消退过快/过慢 |
| routing | MAXBAS | 洪峰相位、过程线展宽 |

不要输出连续参数向量；只建议参数组与策略方向。
