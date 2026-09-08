<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  forecasts: Array<{ issue_time: string; lead_values: Record<number, number> }>
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!props.forecasts.length) {
    if (chart) {
      chart.dispose()
      chart = null
    }
    return
  }
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  const categories = props.forecasts.map((f) => String(f.issue_time).slice(0, 10))
  chart.setOption({
    color: ['#007AFF', '#5AC8FA', '#5856D6'],
    tooltip: { trigger: 'axis' },
    legend: {
      data: ['提前 1 天', '提前 2 天', '提前 3 天'],
      textStyle: { color: '#62626A' },
    },
    grid: { left: 48, right: 24, top: 48, bottom: 36 },
    xAxis: {
      type: 'category',
      name: '日期',
      data: categories,
      axisLine: { lineStyle: { color: '#E5E5EA' } },
      axisLabel: { color: '#62626A' },
    },
    yAxis: {
      type: 'value',
      name: '流量 m³/s',
      splitLine: { lineStyle: { color: '#E5E5EA' } },
      axisLabel: { color: '#62626A' },
      nameTextStyle: { color: '#62626A' },
    },
    series: [1, 2, 3].map((lead, index) => ({
      name: `提前 ${lead} 天`,
      type: 'line',
      smooth: true,
      showSymbol: props.forecasts.length < 8,
      lineStyle: { width: index === 0 ? 3 : 2 },
      data: props.forecasts.map((f) => f.lead_values[lead] ?? f.lead_values[String(lead) as never] ?? null),
    })),
  })
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
})
watch(() => props.forecasts, render, { deep: true })
</script>

<template>
  <div v-if="!forecasts.length" class="empty" data-test="forecast-chart-empty">暂无预报序列</div>
  <div v-else ref="el" data-test="forecast-chart" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
  height: 360px;
}
.empty {
  padding: 2rem 0;
  color: var(--secondary);
}
</style>
