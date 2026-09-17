---
name: sac-sma-calibration-diagnosis
description: 根据 Hydro-Agent reduced SAC-SMA-inspired 实验实现建立可证伪诊断假设；不得把该变体等同 NOAA SAC-SMA。
metadata:
  title_zh: "Reduced SAC-SMA-inspired 率定诊断"
  purpose_zh: "把现象转成上层、下层、下渗或汇流机制假设，并限定下一项实验的参数组。"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  prompt_references: "references/sac-sma-parameter-semantics.md"
---

# Reduced SAC-SMA-inspired 率定诊断

先引用水文证据审查的现象、窗口和 Evidence ID，再判断上层（upper）、下层（lower）、下渗（percolation）与汇流（routing）哪一种解释更可能成立。每个假设说明支持证据、可能反证、缺失证据、候选参数组和预期可观测变化；forcing 时间错位须先排除。

当前 Core 省略 `ADIMP`、`PFREE`、`RIVA`、`SIDE`、`RSERV` 等标准过程，并额外使用三角单位线 `UHK`。`ZPERC/REXP` 的当前实现也尚未与 NOAA-OWP SAC-SMA 完成逐步 parity；因此只能解释这个 reduced variant，不能声称得到标准 SAC-SMA 参数。

参数机制：
- `upper`：UZTWM/UZFWM/UZK/PCTIM，主导上层张力水、自由水、壤中流与不透水面积
- `lower`：LZTWM/LZFSM/LZFPM/LZSK/LZPK，主导下层张力水与快/慢基流
- `percolation`：ZPERC/REXP，主导向下层补给与干旱期下渗非线性
- `routing`：UHK，主导单位线时间基与洪峰相位

只输出合法的 `upper`、`lower`、`percolation`、`routing` 等组和实验方向。绝对参数边界、当前 reduced variant 计算与连续参数向量由确定性 Core/优化器负责；final-test 不能进入诊断。
