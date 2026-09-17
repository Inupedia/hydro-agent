<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { HydrographComparison } from '../types/api'
import {
  axisCategory,
  axisValue,
  BAR_CAPSULE,
  chartMotion,
  currentChartTheme,
  formatMetric,
} from '../chartTheme'

const props = defineProps<{
  comparison: HydrographComparison | null
  gate?: Record<string, unknown> | null
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

type MetricDataset = {
  categories: string[]
  baseline: Array<number | null>
  compared: Array<number | null>
  comparedLabel: string
  subtitle: string
  conclusion: string
}

function finite(metrics: Record<string, number | string | null> | null | undefined, key: string) {
  const value = metrics?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function conclude(baseline: Array<number | null>, compared: Array<number | null>, label: string) {
  const pairs = baseline
    .map((before, index) => {
      const after = compared[index]
      if (before == null || after == null) return null
      return after - before
    })
    .filter((delta): delta is number => delta != null)
  if (!pairs.length) return '基准与结果对照'
  const improved = pairs.filter((delta) => delta > 0.01).length
  const worsened = pairs.filter((delta) => delta < -0.01).length
  if (improved && !worsened) return `${label}在可比指标上抬升`
  if (worsened && !improved) return `${label}尚未全面超过基准`
  if (improved && worsened) return `${label}有得有失，需看主指标`
  return `${label}与基准几乎持平`
}

const dataset = computed<MetricDataset | null>(() => {
  const item = props.comparison
  if (item) {
    const compared = item.kind === 'independent_test' ? item.frozen_metrics : item.candidate_metrics
    const baseline = item.baseline_metrics
    const categories: string[] = []
    const baselineValues: Array<number | null> = []
    const comparedValues: Array<number | null> = []
    for (const [key, label] of [
      ['nse', 'NSE'],
      ['kge', 'KGE'],
    ] as const) {
      const before = finite(baseline, key)
      const after = finite(compared, key)
      if (before == null && after == null) continue
      categories.push(label)
      baselineValues.push(before)
      comparedValues.push(after)
    }
    if (categories.length) {
      const comparedLabel = item.kind === 'independent_test' ? '最终方案' : '候选方案'
      return {
        categories,
        baseline: baselineValues,
        compared: comparedValues,
        comparedLabel,
        subtitle:
          item.kind === 'independent_test'
            ? '独立检验 · NSE / KGE · 越高越好'
            : '率定窗口 · NSE / KGE · 越高越好',
        conclusion: conclude(baselineValues, comparedValues, comparedLabel),
      }
    }
  }

  const gateMetrics = props.gate?.metrics
  if (gateMetrics && typeof gateMetrics === 'object') {
    const raw = gateMetrics as Record<string, unknown>
    const before = raw.base_primary
    const after = raw.candidate_primary
    if (
      typeof before === 'number' &&
      Number.isFinite(before) &&
      typeof after === 'number' &&
      Number.isFinite(after)
    ) {
      return {
        categories: ['开发门控主指标'],
        baseline: [before],
        compared: [after],
        comparedLabel: '候选方案',
        subtitle: '过程线尚未就绪，先展示 Gate 可比指标',
        conclusion: conclude([before], [after], '候选方案'),
      }
    }
  }
  return null
})

async function render() {
  await nextTick()
  const data = dataset.value
  if (!data || !el.value) {
    chart?.dispose()
    chart = null
    return
  }
  if (typeof ResizeObserver === 'undefined') return
  if (!chart) chart = echarts.init(el.value)
  const motion = chartMotion(420)
  const { base: chartBase, colors, ink } = currentChartTheme()
  chart.setOption(
    {
      ...chartBase,
      animationDuration: motion.duration,
      animationEasing: motion.easing,
      tooltip: {
        ...chartBase.tooltip,
        valueFormatter: (value: unknown) => formatMetric(value),
      },
      legend: {
        ...chartBase.legend,
        data: ['基准方案', data.comparedLabel],
      },
      grid: { left: 8, right: 12, top: 28, bottom: 48, containLabel: true },
      xAxis: {
        ...axisCategory(ink),
        data: data.categories,
        axisLabel: {
          color: ink.secondary,
          fontSize: 12,
          fontWeight: 600,
          fontFamily: chartBase.textStyle.fontFamily,
        },
      },
      yAxis: {
        ...axisValue('指标值', ink),
        min: (extent: { min: number; max: number }) => {
          const floor = Math.min(0, extent.min)
          return Number.isFinite(floor) ? Math.floor(floor * 10) / 10 : 0
        },
      },
      series: [
        {
          name: '基准方案',
          type: 'bar',
          barMaxWidth: 36,
          barGap: '28%',
          itemStyle: {
            color: colors[1],
            borderRadius: [...BAR_CAPSULE],
          },
          label: {
            show: data.categories.length <= 3,
            position: 'top',
            color: ink.secondary,
            fontSize: 11,
            fontWeight: 700,
            fontFamily: chartBase.textStyle.fontFamily,
            formatter: (params: { value?: number | null }) => formatMetric(params.value),
          },
          emphasis: { focus: 'series' },
          animationDelay: motion.duration ? 0 : 0,
          data: data.baseline,
        },
        {
          name: data.comparedLabel,
          type: 'bar',
          barMaxWidth: 36,
          itemStyle: {
            color: colors[2],
            borderRadius: [...BAR_CAPSULE],
          },
          label: {
            show: data.categories.length <= 3,
            position: 'top',
            color: ink.text,
            fontSize: 11,
            fontWeight: 700,
            fontFamily: chartBase.textStyle.fontFamily,
            formatter: (params: { value?: number | null }) => formatMetric(params.value),
          },
          emphasis: { focus: 'series' },
          animationDelay: motion.duration ? 100 : 0,
          data: data.compared,
        },
      ],
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
  void render()
  window.addEventListener('resize', onResize)
  window.addEventListener('hydro-theme-change', onThemeChange)
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(onResize)
    if (el.value) observer.observe(el.value)
  }
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('hydro-theme-change', onThemeChange)
  observer?.disconnect()
  chart?.dispose()
})
watch(dataset, render, { deep: true })
</script>

<template>
  <section v-if="dataset" class="metric-comparison" data-test="scheme-metric-comparison">
    <div class="metric-heading">
      <div>
        <span class="metric-overline">方案指标</span>
        <strong>{{ dataset.conclusion }}</strong>
      </div>
      <span class="metric-subtitle">{{ dataset.subtitle }}</span>
    </div>
    <div ref="el" class="metric-chart" data-test="scheme-metric-chart" />
    <p class="metric-src">配对柱 · 越高越好 · 不断轴</p>
  </section>
</template>

<style scoped>
.metric-comparison {
  margin-top: 16px;
  padding: 18px 18px 14px;
  border: 1px solid var(--separator, #e8e9ee);
  border-radius: 20px;
  background: var(--surface, #ffffff);
  box-shadow: 0 2px 8px rgba(25, 40, 65, 0.04);
}
.metric-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 0 4px 2px;
}
.metric-heading > div {
  display: grid;
  gap: 2px;
}
.metric-overline {
  color: var(--text-tertiary, #85858e);
  font-size: 0.6875rem;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.metric-heading strong {
  color: var(--text-primary, #1d1d1f);
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.4;
}
.metric-subtitle {
  max-width: 48%;
  color: var(--text-secondary, #62626a);
  font-size: 0.75rem;
  line-height: 1.5;
  text-align: right;
}
.metric-chart {
  width: 100%;
  height: 260px;
  min-height: 220px;
}
.metric-src {
  margin: 2px 4px 0;
  color: var(--text-tertiary, #85858e);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

@media (max-width: 720px) {
  .metric-comparison {
    padding: 16px 10px 10px;
    border-radius: 16px;
  }
  .metric-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
    padding-inline: 6px;
  }
  .metric-subtitle {
    max-width: none;
    text-align: left;
  }
  .metric-chart {
    height: 240px;
  }
}
</style>
