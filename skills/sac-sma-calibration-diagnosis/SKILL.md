---
name: sac-sma-calibration-diagnosis
description: 基于 NOAA-OWP SAC-SMA 16 参数无冻土过程建立可证伪诊断假设并给出率定参数组方向。
metadata:
  title_zh: "NOAA-OWP SAC-SMA 率定诊断"
  purpose_zh: "把现象转成上层、下层、下渗、基流、蒸散或汇流机制假设，并限定下一项实验的参数组。"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  prompt_references: "references/sac-sma-parameter-semantics.md"
---

# NOAA-OWP SAC-SMA 率定诊断

先引用水文证据审查的现象、窗口和 Evidence ID，再判断上层（upper）、下层（lower）、下渗（percolation）、蒸散（evap）、基流（baseflow）与汇流（routing）哪一种解释更可能成立。每个假设说明支持证据、可能反证、缺失证据、候选参数组和预期可观测变化；forcing 时间错位须先排除。

当前内核移植 NOAA-OWP SAC-SMA `SAC1`/`EXSAC` 的 16 参数无冻土过程，并已与固定版本的 NOAA-OWP Fortran 可执行输出完成逐状态、逐分量 parity：内部增量步长、`ADIMP` 饱和产流、`PFREE` 直接自由水下渗分配、`RIVA` 河岸蒸散、`SIDE` 非河道基流旁路、`RSERV` 下层张力水补给均按上游源码计算。当前产品不接入温度、积雪或冻土过程；出现雪季系统偏差时，应优先标记 forcing/process gap，不能硬归因给 16 个 SAC-SMA 参数。仓库在官方本体之外保留 `routing.HOURS` 三角单位线配置，属固定线路由层，不参与官方 16 参数率定。

参数机制：
- `upper`：UZTWM/UZFWM/UZK/PCTIM/ADIMP，主导上层张力水、自由水、壤中流、不透水面积与附加不透水饱和产流
- `lower`：LZTWM/LZFSM/LZFPM/LZSK/LZPK，主导下层张力水与快/慢基流
- `percolation`：ZPERC/REXP/PFREE/RSERV，主导下渗非线性、直接自由水下渗分配与张力水补给份额
- `evap`：UZTWM/UZFWM/RIVA/RSERV，主导蒸发衰减与河岸蒸散占比
- `baseflow`：LZPK/LZSK/SIDE，主导退水形态与非河道基流旁路
- `routing`：UZK/LZSK/LZPK，主导官方过程内的响应时序（`HOURS` 为固定线路由配置）

只输出合法的 `upper`、`lower`、`percolation`、`routing`、`evap`、`baseflow` 等组和实验方向。预注册搜索边界、16 参数计算与连续参数向量由确定性 Core/优化器负责；触碰搜索边界表示需要审查或扩展实验窗口，不代表物理上已到绝对极限。final-test 不能进入诊断。下层慢库未稳定或 warmup 证据不足时，先延长 warmup 或提供已验证初始状态，不得把冷启动误差交给优化器吸收。
