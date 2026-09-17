<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  axisCategory,
  axisValue,
  chartMotion,
  currentChartTheme,
  formatFlow,
} from '../chartTheme'

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
  const raw =
    (leads as Record<string | number, number>)[lead] ??
    (leads as Record<string, number>)[String(lead)]
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
  const motion = chartMotion(900, dense)
  const compact = el.value.clientWidth < 440
  const { base: chartBase, colors, ink, symbolBorder } = currentChartTheme()
  const names = ['提前 1 天', '提前 2 天', '提前 3 天']
  chart.setOption(
    {
      ...chartBase,
      animationDuration: motion.duration,
      animationEasing: motion.easing,
      animationDurationUpdate: motion.duration,
      animationEasingUpdate: motion.easing,
      tooltip: {
        ...chartBase.tooltip,
        valueFormatter: formatFlow,
      },
      legend: {
        ...chartBase.legend,
        data: names,
        itemWidth: compact ? 10 : chartBase.legend.itemWidth,
        itemGap: compact ? 10 : chartBase.legend.itemGap,
        textStyle: {
          ...chartBase.legend.textStyle,
          fontSize: compact ? 10.5 : chartBase.legend.textStyle.fontSize,
        },
      },
      grid: { ...chartBase.grid, bottom: compact ? 58 : chartBase.grid.bottom },
      dataZoom: dense ? [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }] : undefined,
      xAxis: {
        ...axisCategory(ink),
        data: categories,
        boundaryGap: false,
        axisLabel: {
          color: ink.muted,
          fontSize: 11,
          fontWeight: 500,
          margin: 14,
          hideOverlap: true,
          formatter: (value: string) => value.slice(5).replace('-', '/'),
        },
      },
      yAxis: axisValue('流量 · m³/s', ink),
      series: [1, 2, 3].map((lead, index) => ({
        name: names[index],
        type: 'line' as const,
        smooth: false,
        connectNulls: false,
        symbol: 'circle',
        symbolSize: dense ? 3 : 5.5,
        showSymbol: props.forecasts.length < 8,
        z: 3 - index,
        itemStyle: {
          color: colors[index],
          borderColor: symbolBorder,
          borderWidth: dense ? 0 : 1.5,
        },
        lineStyle: {
          width: index === 0 ? 3 : 2,
          type: index === 2 ? ('dashed' as const) : ('solid' as const),
          cap: 'round' as const,
          join: 'round' as const,
        },
        areaStyle:
          index === 0
            ? {
                color: {
                  type: 'linear' as const,
                  x: 0,
                  y: 0,
                  x2: 0,
                  y2: 1,
                  colorStops: [
                    { offset: 0, color: ink.areaPrimary },
                    { offset: 1, color: 'transparent' },
                  ],
                },
              }
            : undefined,
        emphasis: { focus: 'series' as const, scale: 1.35 },
        animationDelay: motion.duration ? index * 90 : 0,
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
  color: var(--text-secondary, #62626a);
  font-size: 0.875rem;
}
</style>
