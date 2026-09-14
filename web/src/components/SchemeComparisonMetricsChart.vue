<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { HydrographComparison } from '../types/api'
import { axisCategory, axisValue, chartBase, CHART_COLORS } from '../chartTheme'

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
}

function finite(metrics: Record<string, number | null> | null | undefined, key: string) {
  const value = metrics?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const dataset = computed<MetricDataset | null>(() => {
  const item = props.comparison
  if (item) {
    const compared = item.kind === 'independent_test'
      ? item.frozen_metrics
      : item.candidate_metrics
    const baseline = item.baseline_metrics
    const categories: string[] = []
    const baselineValues: Array<number | null> = []
    const comparedValues: Array<number | null> = []
    for (const [key, label] of [['nse', 'NSE'], ['kge', 'KGE']] as const) {
      const before = finite(baseline, key)
      const after = finite(compared, key)
      if (before == null && after == null) continue
      categories.push(label)
      baselineValues.push(before)
      comparedValues.push(after)
    }
    if (categories.length) {
      return {
        categories,
        baseline: baselineValues,
        compared: comparedValues,
        comparedLabel: item.kind === 'independent_test' ? '最终方案' : '候选方案',
        subtitle: item.kind === 'independent_test' ? '独立检验指标对比' : '率定窗口指标对比',
      }
    }
  }

  const gateMetrics = props.gate?.metrics
  if (gateMetrics && typeof gateMetrics === 'object') {
    const raw = gateMetrics as Record<string, unknown>
    const before = raw.base_primary
    const after = raw.candidate_primary
    if (typeof before === 'number' && Number.isFinite(before) && typeof after === 'number' && Number.isFinite(after)) {
      return {
        categories: ['开发 Gate 主指标'],
        baseline: [before],
        compared: [after],
        comparedLabel: '候选方案',
        subtitle: '过程线尚未就绪，先展示 Gate 可比指标',
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
  if (!chart) chart = echarts.init(el.value)
  chart.setOption({
    ...chartBase,
    animationDuration: 350,
    tooltip: {
      ...chartBase.tooltip,
      valueFormatter: (value: unknown) =>
        typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : '—',
    },
    xAxis: { ...axisCategory(), data: data.categories },
    yAxis: axisValue('指标值'),
    series: [
      {
        name: '基准方案',
        type: 'bar',
        barMaxWidth: 44,
        itemStyle: { color: CHART_COLORS[0], borderRadius: [8, 8, 0, 0] },
        data: data.baseline,
      },
      {
        name: data.comparedLabel,
        type: 'bar',
        barMaxWidth: 44,
        itemStyle: { color: CHART_COLORS[1], borderRadius: [8, 8, 0, 0] },
        data: data.compared,
      },
    ],
  }, { notMerge: true })
  requestAnimationFrame(() => chart?.resize())
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  void render()
  window.addEventListener('resize', onResize)
  observer = new ResizeObserver(onResize)
  if (el.value) observer.observe(el.value)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  observer?.disconnect()
  chart?.dispose()
})
watch(dataset, render, { deep: true })
</script>

<template>
  <section v-if="dataset" class="metric-comparison" data-test="scheme-metric-comparison">
    <div class="metric-heading">
      <strong>方案指标对比</strong>
      <span>{{ dataset.subtitle }}</span>
    </div>
    <div ref="el" class="metric-chart" data-test="scheme-metric-chart" />
  </section>
</template>

<style scoped>
.metric-comparison {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid rgba(104, 129, 151, 0.14);
}
.metric-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 4px;
}
.metric-heading strong {
  color: var(--primary, #1d1d1f);
  font-size: 0.95rem;
}
.metric-heading span {
  color: var(--secondary, #698197);
  font-size: 0.8rem;
}
.metric-chart {
  width: 100%;
  height: 260px;
  min-height: 220px;
}

@media (max-width: 720px) {
  .metric-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
  .metric-chart {
    height: 240px;
  }
}
</style>
