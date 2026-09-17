<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { HydrographComparison } from '../types/api'
import {
  axisCategory,
  axisValue,
  chartMotion,
  currentChartTheme,
  formatFlow,
  hydrographTitleZh,
} from '../chartTheme'

const props = defineProps<{
  comparison: HydrographComparison | null
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

const seriesRows = computed(() => props.comparison?.series || [])
const finalLabel = computed(() =>
  props.comparison?.calibrated ? '最终方案（率定后）' : '最终方案',
)

function metricLine(label: string, metrics?: Record<string, number | string | null> | null) {
  if (!metrics) return null
  const bits = ['nse', 'kge', 'pbias_percent', 'rmse_m3s']
    .map((key) => {
      const value = metrics[key]
      if (typeof value !== 'number' || !Number.isFinite(value)) return null
      if (key === 'pbias_percent') return `相对偏差 ${value.toFixed(1)}%`
      if (key === 'rmse_m3s') return `均方根误差 ${value.toFixed(2)} m³/s`
      if (key === 'nse') return `纳什效率 ${value.toFixed(3)}`
      return `克林-古普塔 ${value.toFixed(3)}`
    })
    .filter((item): item is string => Boolean(item))
  return bits.length ? `${label}：${bits.join(' · ')}` : null
}

const captions = computed(() => {
  const item = props.comparison
  if (!item) return []
  return [
    metricLine('基准方案', item.baseline_metrics),
    metricLine('候选方案', item.candidate_metrics),
    metricLine(finalLabel.value, item.frozen_metrics),
    item.kind === 'calibration'
      ? item.gate_status === 'ROLLBACK'
        ? '候选未过质量把关；本图仍展示智能体提出的率定窗对比。'
        : item.gate_status === 'KEEP'
          ? '质量把关后维持原方案；本图仍展示智能体提出的率定窗对比。'
          : '率定窗口：观测、基准与智能体候选。'
      : item.calibrated
        ? '质量把关通过，候选方案已作为最终方案。'
        : item.gate_status === 'KEEP'
          ? '质量把关后维持原方案，最终方案与基准方案可能重合。'
          : item.gate_status === 'ROLLBACK'
            ? '候选方案已撤销，最终方案回到安全方案。'
            : null,
  ].filter((line): line is string => Boolean(line))
})

const cardTitle = computed(() =>
  props.comparison ? hydrographTitleZh(props.comparison) : '过程线对照',
)

const cardSub = computed(() => {
  const item = props.comparison
  if (!item) return ''
  const parts = [
    item.kind === 'independent_test' ? '独立检验' : '率定窗口',
    '观测为实心点线',
    '基准为发丝虚线',
    '最终方案加浅面积',
    '单位 m³/s',
  ]
  return parts.join(' · ')
})

const sourceLine = computed(() => {
  const item = props.comparison
  if (!item) return ''
  const window = item.kind === 'independent_test' ? '独立检验窗口' : '率定窗口'
  const days = [
    item.evaluated_days ? `${item.evaluated_days} 天评价` : null,
    item.warmup_days ? `${item.warmup_days} 天预热` : null,
  ]
    .filter(Boolean)
    .join(' · ')
  return `流量过程线 · ${window}${days ? ` · ${days}` : ''} · 单位 m³/s`
})

async function render() {
  await nextTick()
  const rows = seriesRows.value
  if (!rows.length) {
    if (chart) {
      chart.dispose()
      chart = null
    }
    return
  }
  if (!el.value) return
  el.value.style.opacity = '1'
  el.value.style.visibility = 'visible'
  if (!chart) chart = echarts.init(el.value)
  const categories = rows.map((row) => row.time)
  const warmup = rows.filter((row) => row.is_warmup)
  const firstWarmup = warmup.at(0)
  const lastWarmup = warmup.at(-1)
  const dense = rows.length > 80
  const motion = chartMotion(1_080, dense)
  const compact = el.value.clientWidth < 440
  const { base: chartBase, colors, ink, symbolBorder } = currentChartTheme()
  const has = (key: 'baseline_m3s' | 'candidate_m3s' | 'frozen_m3s') =>
    rows.some((row) => typeof row[key] === 'number' && Number.isFinite(row[key] as number))

  // F2 Hairline Line: observation = primary ink stroke; baseline = hairline dashed; final = accent stroke.
  const series: echarts.LineSeriesOption[] = [
    {
      name: '观测',
      type: 'line',
      showSymbol: !dense && rows.length <= 48,
      symbol: 'circle',
      symbolSize: 5,
      connectNulls: false,
      z: 5,
      lineStyle: { width: 2.5, color: colors[0], cap: 'round', join: 'round' },
      itemStyle: { color: colors[0], borderColor: symbolBorder, borderWidth: 1.5 },
      data: rows.map((row) => row.observed_m3s ?? null),
      markArea:
        firstWarmup && lastWarmup
          ? {
              silent: true,
              itemStyle: { color: ink.warmup },
              label: {
                color: ink.tertiary,
                fontSize: 10.5,
                fontWeight: 600,
                fontFamily: chartBase.textStyle.fontFamily,
              },
              data: [[{ xAxis: firstWarmup.time, name: '预热期' }, { xAxis: lastWarmup.time }]],
            }
          : undefined,
    },
  ]
  if (has('baseline_m3s')) {
    series.push({
      name: '基准方案',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      z: 2,
      lineStyle: { width: 1.25, color: colors[1], type: 'dashed', cap: 'round' },
      itemStyle: { color: colors[1] },
      data: rows.map((row) => row.baseline_m3s ?? null),
    })
  }
  if (has('candidate_m3s')) {
    series.push({
      name: '候选方案',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      z: 3,
      lineStyle: { width: 1.75, color: colors[2], cap: 'round', join: 'round' },
      itemStyle: { color: colors[2] },
      data: rows.map((row) => row.candidate_m3s ?? null),
    })
  }
  if (has('frozen_m3s')) {
    series.push({
      name: finalLabel.value,
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      z: 4,
      lineStyle: { width: 2.75, color: colors[2], cap: 'round', join: 'round' },
      itemStyle: { color: colors[2] },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: ink.areaAccent },
          { offset: 1, color: 'transparent' },
        ]),
      },
      data: rows.map((row) => row.frozen_m3s ?? null),
    })
  }
  series.forEach((item, index) => {
    item.animationDelay = motion.duration ? index * 110 : 0
  })
  chart.setOption(
    {
      ...chartBase,
      animationDuration: motion.duration,
      animationEasing: motion.easing,
      animationDurationUpdate: motion.duration,
      animationEasingUpdate: motion.easing,
      tooltip: {
        ...chartBase.tooltip,
        valueFormatter: (value: unknown) =>
          typeof value === 'number' && Number.isFinite(value) ? formatFlow(value) : '-',
      },
      legend: {
        ...chartBase.legend,
        data: series.map((row) => String(row.name)),
        itemWidth: compact ? 10 : chartBase.legend.itemWidth,
        itemGap: compact ? 10 : chartBase.legend.itemGap,
        textStyle: {
          ...chartBase.legend.textStyle,
          fontSize: compact ? 10.5 : chartBase.legend.textStyle.fontSize,
        },
      },
      grid: { ...chartBase.grid, bottom: compact ? 58 : chartBase.grid.bottom },
      dataZoom: rows.length > 40 ? [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }] : undefined,
      xAxis: {
        ...axisCategory(ink),
        data: categories,
        boundaryGap: false,
        axisLabel: {
          color: ink.muted,
          fontSize: 11,
          fontWeight: 500,
          hideOverlap: true,
          margin: 14,
          formatter: (value: string) => value.slice(5).replace('-', '/'),
        },
      },
      yAxis: {
        ...axisValue('流量 · m³/s', ink),
        splitLine: {
          lineStyle: {
            color: ink.grid,
            type: 'solid',
            width: 1,
            opacity: 0.55,
          },
        },
      },
      series,
    },
    { notMerge: true },
  )
  requestAnimationFrame(() => chart?.resize())
}

function onResize() {
  chart?.resize()
}
function onThemeChange() {
  void render()
}

onMounted(() => {
  render()
  window.addEventListener('resize', onResize)
  window.addEventListener('hydro-theme-change', onThemeChange)
  observer = new ResizeObserver(onResize)
  if (el.value) observer.observe(el.value)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('hydro-theme-change', onThemeChange)
  observer?.disconnect()
  chart?.dispose()
})
watch(() => props.comparison, render, { deep: true })
</script>

<template>
  <div v-if="!seriesRows.length" class="empty" data-test="hydrograph-empty">暂无过程线</div>
  <div v-else class="wrap" data-test="final-comparison-chart-wrap">
    <header class="card-head">
      <h3>{{ cardTitle }}</h3>
      <p>{{ cardSub }}</p>
    </header>
    <div ref="el" data-test="hydrograph-chart" class="chart" />
    <div class="meta-foot">
      <p v-if="sourceLine" class="src">{{ sourceLine }}</p>
      <div v-if="captions.length" class="caption-stack">
        <p v-for="line in captions" :key="line" class="caption">{{ line }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wrap {
  --ledger-line: color-mix(in srgb, var(--chart-grid) 32%, transparent);
  position: relative;
  overflow: hidden;
  margin-top: 16px;
  padding: 20px 20px 16px;
  border: 1px solid var(--separator, #e8e9ee);
  border-radius: 24px;
  background:
    repeating-linear-gradient(
      to bottom,
      transparent 0,
      transparent 27px,
      var(--ledger-line) 27px,
      var(--ledger-line) 28px
    ),
    var(--surface);
  background-color: var(--surface, #ffffff);
  box-shadow: var(--shadow);
}
.wrap::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: linear-gradient(180deg, #1889ee 0%, #8e8bd4 100%);
  border-radius: 24px 0 0 24px;
}
.card-head {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 4px;
  margin: 0 0 12px;
  padding: 0 4px 12px;
  border-bottom: 1px solid var(--separator, #e8e9ee);
}
.card-head h3 {
  margin: 0;
  color: var(--text-primary, #1d1d1f);
  font-size: 1.0625rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.35;
}
.card-head p {
  margin: 0;
  color: var(--text-secondary, #62626a);
  font-size: 0.75rem;
  line-height: 1.5;
}
.chart {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 400px;
  min-height: 300px;
}
.meta-foot {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 8px;
  margin: 12px 4px 0;
  padding-top: 12px;
  border-top: 1px solid var(--separator, #e8e9ee);
}
.src {
  margin: 0;
  color: var(--text-tertiary, #85858e);
  font-size: 0.6875rem;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  line-height: 1.45;
}
.caption-stack {
  display: grid;
  gap: 6px;
}
.empty,
.caption {
  color: var(--text-secondary, #62626a);
  font-size: 0.8125rem;
  line-height: 1.5;
}
.caption {
  margin: 0;
  padding: 8px 10px;
  border-radius: 12px;
  background: var(--surface-secondary);
  border: 1px solid var(--separator, #e8e9ee);
}

@media (max-width: 720px) {
  .wrap {
    padding: 14px 12px 12px;
    border-radius: 18px;
  }
  .chart {
    height: 320px;
    min-height: 260px;
  }
  .card-head h3 {
    font-size: 1rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wrap {
    transition: none;
  }
}
</style>
