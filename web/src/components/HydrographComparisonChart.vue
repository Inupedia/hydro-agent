<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { HydrographComparison } from '../types/api'
import { axisCategory, axisValue, chartBase, CHART_COLORS, formatFlow } from '../chartTheme'

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

function metricLine(label: string, metrics?: Record<string, number | null> | null) {
  if (!metrics) return null
  const bits = ['nse', 'kge', 'pbias_percent', 'rmse_m3s']
    .map((key) => {
      const value = metrics[key]
      if (typeof value !== 'number' || !Number.isFinite(value)) return null
      if (key === 'pbias_percent') return `相对偏差 ${value.toFixed(1)}%`
      if (key === 'rmse_m3s') return `均方根误差 ${value.toFixed(2)}`
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
    item.calibrated
      ? '质量把关通过，候选方案已作为最终方案。'
      : item.gate_status === 'KEEP'
        ? '质量把关后维持原方案，最终方案与基准方案可能重合。'
        : item.gate_status === 'ROLLBACK'
          ? '候选方案已撤销，最终方案回到安全方案。'
          : null,
  ].filter((line): line is string => Boolean(line))
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
  const has = (key: 'baseline_m3s' | 'candidate_m3s' | 'frozen_m3s') =>
    rows.some((row) => typeof row[key] === 'number' && Number.isFinite(row[key] as number))
  const series: echarts.LineSeriesOption[] = [
    {
      name: '观测',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 3, color: CHART_COLORS[0] },
      itemStyle: { color: CHART_COLORS[0] },
      data: rows.map((row) => row.observed_m3s ?? null),
      markArea:
        firstWarmup && lastWarmup
          ? {
              silent: true,
              itemStyle: { color: 'rgba(231,235,241,0.48)' },
              label: { color: '#62626A', fontSize: 11 },
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
      lineStyle: { width: 2, color: CHART_COLORS[1], type: 'dashed' },
      itemStyle: { color: CHART_COLORS[1] },
      data: rows.map((row) => row.baseline_m3s ?? null),
    })
  }
  if (has('candidate_m3s')) {
    series.push({
      name: '候选方案',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 2, color: CHART_COLORS[2] },
      itemStyle: { color: CHART_COLORS[2] },
      data: rows.map((row) => row.candidate_m3s ?? null),
    })
  }
  if (has('frozen_m3s')) {
    series.push({
      name: finalLabel.value,
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 3, color: CHART_COLORS[2] },
      itemStyle: { color: CHART_COLORS[2] },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(142,139,212,0.18)' },
          { offset: 1, color: 'rgba(142,139,212,0)' },
        ]),
      },
      data: rows.map((row) => row.frozen_m3s ?? null),
    })
  }
  chart.setOption(
    {
      ...chartBase,
      animationDuration: rows.length > 80 ? 0 : 280,
      animationEasing: 'cubicOut',
      tooltip: {
        ...chartBase.tooltip,
        valueFormatter: (value: unknown) =>
          typeof value === 'number' && Number.isFinite(value) ? formatFlow(value) : '—',
      },
      dataZoom: rows.length > 40 ? [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }] : undefined,
      xAxis: {
        ...axisCategory(),
        data: categories,
        axisLabel: {
          color: '#62626A',
          fontSize: 12,
          hideOverlap: true,
          formatter: (value: string) => value.slice(5).replace('-', '/'),
        },
      },
      yAxis: axisValue(),
      series,
    },
    { notMerge: true },
  )
  requestAnimationFrame(() => chart?.resize())
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', onResize)
  observer = new ResizeObserver(onResize)
  if (el.value) observer.observe(el.value)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  observer?.disconnect()
  chart?.dispose()
})
watch(() => props.comparison, render, { deep: true })
</script>

<template>
  <div v-if="!seriesRows.length" class="empty" data-test="hydrograph-empty">暂无过程线</div>
  <div v-else class="wrap" data-test="final-comparison-chart-wrap">
    <div ref="el" data-test="hydrograph-chart" class="chart" />
    <div v-if="captions.length" class="caption-stack">
      <p v-for="line in captions" :key="line" class="caption">{{ line }}</p>
    </div>
  </div>
</template>

<style scoped>
.wrap {
  overflow: hidden;
  margin-top: 16px;
  padding: 14px 14px 12px;
  border: 1px solid var(--separator, #e8e9ee);
  border-radius: 20px;
  background: var(--surface-secondary, #f8f9fb);
  box-shadow: 0 2px 8px rgba(25, 40, 65, 0.04);
}
.chart {
  width: 100%;
  height: 400px;
  min-height: 280px;
}
.caption-stack {
  display: grid;
  gap: 4px;
  margin: 8px 4px 0;
  padding-top: 10px;
  border-top: 1px solid var(--separator, #e8e9ee);
}
.empty,
.caption {
  color: var(--text-secondary, #62626a);
  font-size: 0.8125rem;
  line-height: 1.5;
}
.caption {
  margin: 0;
}

@media (max-width: 720px) {
  .wrap {
    padding: 10px 8px 10px;
    border-radius: 16px;
  }
  .chart {
    height: 340px;
  }
}
</style>