# 简化 SAC-SMA 参数语义（诊断用）

| 组 | 参数 | 主要现象 |
| --- | --- | --- |
| upper | UZTWM, UZFWM, UZK, PCTIM | 初损、表层产流、壤中流、不透水面积 |
| lower | LZTWM, LZFSM, LZFPM, LZSK, LZPK | 基流组成、退水形态 |
| percolation | ZPERC, REXP | 干旱期补给不足、下层补水过快/过慢 |
| routing | UHK | 洪峰相位、过程线展宽 |

不要输出连续参数向量；只建议参数组与策略方向。
