<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { axisCategory, axisValue, chartBase, CHART_COLORS, formatFlow } from '../chartTheme'

const props = defineProps<{
  forecasts: Array<{ issue_time: string; lead_values: Record<number, number> }>
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function leadValue(
  leads: Record<number, number> | Record<string, number> | undefined,
  lead: number,
): number | null {
  if (!leads) return null
  const raw = (leads as Record<string | number, number>)[lead] ?? (leads as Record<string, number>)[String(lead)]
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null
}

async function render() {
  await nextTick()
  if (!props.forecasts.length) {
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
  const categories = props.forecasts.map((f) => String(f.issue_time).slice(0, 10))
  const dense = props.forecasts.length > 40
  const names = ['提前 1 天', '提前 2 天', '提前 3 天']
  chart.setOption(
    {
      ...chartBase,
      animationDuration: dense ? 0 : 400,
      animation: !dense,
      tooltip: {
        ...chartBase.tooltip,
        valueFormatter: formatFlow,
      },
      legend: {
        ...chartBase.legend,
        data: names,
      },
      dataZoom: dense ? [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }] : undefined,
      xAxis: {
        ...axisCategory(),
        data: categories,
        boundaryGap: true,
        axisLabel: {
          color: '#698197',
          fontSize: 12,
          margin: 14,
          hideOverlap: true,
          formatter: (value: string) => value.slice(5).replace('-', '/'),
        },
      },
      yAxis: axisValue(),
      series: [1, 2, 3].map((lead, index) => ({
        name: names[index],
        type: 'line',
        smooth: false,
        connectNulls: false,
        symbol: 'circle',
        symbolSize: dense ? 3 : 6,
        showSymbol: props.forecasts.length < 8,
        itemStyle: { color: CHART_COLORS[index], borderColor: '#fff', borderWidth: dense ? 0 : 2 },
        lineStyle: { width: index === 0 ? 3 : 2, type: index === 2 ? 'dashed' : 'solid' },
        areaStyle:
          index === 0
            ? {
                color: {
                  type: 'linear',
                  x: 0,
                  y: 0,
                  x2: 0,
                  y2: 1,
                  colorStops: [
                    { offset: 0, color: 'rgba(24,137,238,0.18)' },
                    { offset: 1, color: 'rgba(24,137,238,0)' },
                  ],
                },
              }
            : undefined,
        emphasis: { focus: 'series', scale: 1.5 },
        animationDelay: dense ? 0 : index * 80,
        data: props.forecasts.map((f) => leadValue(f.lead_values, lead)),
      })),
    },
    { notMerge: true },
  )
  requestAnimationFrame(() => {
    chart?.resize()
    requestAnimationFrame(() => chart?.resize())
  })
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
watch(() => props.forecasts, render, { deep: true })
</script>

<template>
  <div v-if="!forecasts.length" class="empty" data-test="forecast-chart-empty">暂无预报序列</div>
  <div v-show="forecasts.length" ref="el" data-test="forecast-chart" class="chart" />
</template>

<style scoped>
.chart {
  width: 100%;
  height: 280px;
  max-height: 36vh;
  min-height: 200px;
}
.empty {
  padding: 2rem 0;
  color: var(--secondary);
}
</style>
