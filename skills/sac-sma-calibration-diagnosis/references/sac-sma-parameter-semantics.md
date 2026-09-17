# NOAA-OWP SAC-SMA 参数语义（诊断用）

内核移植 NOAA-OWP `SAC1`/`EXSAC` 的 16 参数无冻土过程：增量步长、`ADIMP` 饱和产流、`PFREE` 分配、`RIVA` 河岸蒸散、`SIDE` 非河道基流、`RSERV` 下层张力水补给均按上游源码逐步计算，并已与固定 revision 的 NOAA-OWP Fortran 可执行输出完成 parity。`HOURS` 是仓库追加的日尺度三角单位线配置，不属于 NOAA SAC-SMA 本体，也不参与官方 16 参数率定；当 `HOURS<=24` 时，日尺度聚合后等价于同日响应，不能用它解释亚日尺度洪峰时移。当前模型没有温度、积雪和冻土输入，雪季偏差不得直接解释为 SAC-SMA 土壤参数问题。

| 组 | 参数 | 主要现象 |
| --- | --- | --- |
| upper | UZTWM, UZFWM, UZK, PCTIM, ADIMP | 初损、表层产流、壤中流、不透水与饱和面积 |
| lower | LZTWM, LZFSM, LZFPM, LZSK, LZPK | 基流组成、退水形态 |
| percolation | ZPERC, REXP, PFREE, RSERV | 下渗非线性、直接自由水下渗分配、张力水补给 |
| evap | UZTWM, UZFWM, RIVA, RSERV | 蒸发衰减、河岸蒸散占比 |
| baseflow | LZPK, LZSK, SIDE | 退水形态、非河道基流旁路 |
| routing | UZK, LZSK, LZPK | 官方过程内的洪峰相位与响应时序（`HOURS` 为固定线路由） |

不要输出连续参数向量；只建议参数组与策略方向。
