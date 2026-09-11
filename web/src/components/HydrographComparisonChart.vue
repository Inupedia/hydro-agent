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
    .filter(Boolean)
  return bits.length ? `${label}：${bits.join(' · ')}` : null
}

const captions = computed(() => {
  const item = props.comparison
  if (!item) return []
  return [
    metricLine('基线方案', item.baseline_metrics),
    metricLine('候选方案', item.candidate_metrics),
    metricLine('冻结方案', item.frozen_metrics),
    item.calibrated
      ? '判定已采用候选方案'
      : item.gate_status === 'KEEP'
        ? '判定维持原方案，未称作率定成功'
        : item.gate_status === 'ROLLBACK'
          ? '判定已回退原方案'
          : null,
  ].filter(Boolean)
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
  const has = (key: 'baseline_m3s' | 'candidate_m3s' | 'frozen_m3s') =>
    rows.some((row) => typeof row[key] === 'number' && Number.isFinite(row[key] as number))
  const series: echarts.LineSeriesOption[] = [
    {
      name: '观测',
      type: 'line',
      showSymbol: false,
      lineStyle: { width: 3, color: '#1d1d1f' },
      itemStyle: { color: '#1d1d1f' },
      data: rows.map((row) => row.observed_m3s ?? null),
      markArea:
        warmup.length > 1
          ? {
              silent: true,
              itemStyle: { color: 'rgba(215,221,227,0.38)' },
              label: { color: '#698197', fontSize: 11 },
              data: [[{ xAxis: warmup[0].time, name: '预热期' }, { xAxis: warmup[warmup.length - 1].time }]],
            }
          : undefined,
    },
  ]
  if (has('baseline_m3s')) {
    series.push({
      name: '基线方案',
      type: 'line',
      showSymbol: false,
      lineStyle: { width: 2, color: CHART_COLORS[0], type: 'dashed' },
      itemStyle: { color: CHART_COLORS[0] },
      data: rows.map((row) => row.baseline_m3s ?? null),
    })
  }
  if (has('candidate_m3s')) {
    series.push({
      name: '候选方案',
      type: 'line',
      showSymbol: false,
      lineStyle: { width: 3, color: CHART_COLORS[1] },
      itemStyle: { color: CHART_COLORS[1] },
      data: rows.map((row) => row.candidate_m3s ?? null),
    })
  }
  if (has('frozen_m3s')) {
    series.push({
      name: '冻结方案',
      type: 'line',
      showSymbol: false,
      lineStyle: { width: 3, color: CHART_COLORS[2] },
      itemStyle: { color: CHART_COLORS[2] },
      data: rows.map((row) => row.frozen_m3s ?? null),
    })
  }
  chart.setOption(
    {
      ...chartBase,
      animationDuration: rows.length > 80 ? 0 : 400,
      tooltip: {
        ...chartBase.tooltip,
        valueFormatter: (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? formatFlow(value) : '—'),
      },
      dataZoom: rows.length > 40 ? [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }] : undefined,
      xAxis: {
        ...axisCategory(),
        data: categories,
        axisLabel: {
          color: '#698197',
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
  <div v-else class="wrap">
    <div ref="el" data-test="hydrograph-chart" class="chart" />
    <p v-for="line in captions" :key="line" class="caption">{{ line }}</p>
  </div>
</template>

<style scoped>
.chart {
  width: 100%;
  height: 320px;
  min-height: 220px;
}
.empty,
.caption {
  color: var(--secondary, #698197);
  font-size: 0.88rem;
}
.caption {
  margin: 0.35rem 0 0;
}
</style>
