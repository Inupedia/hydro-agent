<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
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
  const categories = props.forecasts.map((f) => f.issue_time.slice(0, 10))
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['lead-1', 'lead-2', 'lead-3'] },
    xAxis: { type: 'category', data: categories },
    yAxis: { type: 'value', name: 'm³/s' },
    series: [1, 2, 3].map((lead) => ({
      name: `lead-${lead}`,
      type: 'line',
      data: props.forecasts.map((f) => f.lead_values[lead] ?? null),
    })),
  })
}

onMounted(render)
watch(() => props.forecasts, render, { deep: true })
</script>

<template>
  <div v-if="!forecasts.length" class="empty" data-test="forecast-chart-empty">暂无预报序列</div>
  <div v-else ref="el" data-test="forecast-chart" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
  height: 320px;
}
.empty {
  padding: 1.5rem 0;
  color: #666;
}
</style>
