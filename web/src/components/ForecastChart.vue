<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { gsap, motionDuration, prefersReducedMotion } from '../motion/gsap'

const props = defineProps<{
  forecasts: Array<{ issue_time: string; lead_values: Record<number, number> }>
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

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
  if (!chart) chart = echarts.init(el.value)
  const categories = props.forecasts.map((f) => String(f.issue_time).slice(0, 10))
  const colors = ['#1889ee', '#47b8b0', '#8e8bd4']
  const reduced = prefersReducedMotion()
  chart.setOption(
    {
      animationDuration: reduced ? 0 : 900,
      animationEasing: 'cubicOut',
      animation: !reduced,
      textStyle: { fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif' },
      color: colors,
      tooltip: {
        trigger: 'axis',
        confine: true,
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#e3ecf4',
        padding: [12, 16],
        textStyle: { color: '#36516a', fontSize: 12 },
        extraCssText: 'border-radius:14px;box-shadow:0 12px 32px rgba(50,85,120,.12);',
        axisPointer: { type: 'line', lineStyle: { color: '#9dbedc', type: 'dashed' } },
        valueFormatter: (value: unknown) =>
          typeof value === 'number' && Number.isFinite(value)
            ? `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} m³/s`
            : '暂无数据',
      },
      legend: {
        bottom: 0,
        itemWidth: 16,
        itemHeight: 7,
        itemGap: 18,
        icon: 'roundRect',
        data: ['提前 1 天', '提前 2 天', '提前 3 天'],
        textStyle: { color: '#698197', fontSize: 11 },
      },
      grid: { left: 12, right: 18, top: 34, bottom: 48, containLabel: true },
      xAxis: {
        type: 'category',
        data: categories,
        boundaryGap: true,
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: {
          color: '#8498aa',
          fontSize: 10,
          margin: 14,
          hideOverlap: true,
          formatter: (value: string) => value.slice(5).replace('-', '/'),
        },
      },
      yAxis: {
        type: 'value',
        name: '流量 · m³/s',
        splitNumber: 4,
        nameTextStyle: { color: '#8498aa', fontSize: 10, align: 'left' },
        splitLine: { lineStyle: { color: '#e7eef5', type: 'dashed' } },
        axisLabel: { color: '#8498aa', fontSize: 10 },
      },
      series: [1, 2, 3].map((lead, index) => ({
        name: `提前 ${lead} 天`,
        type: 'line',
        smooth: false,
        connectNulls: false,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: props.forecasts.length < 8,
        itemStyle: { color: colors[index], borderColor: '#fff', borderWidth: 2 },
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
        animationDelay: reduced ? 0 : index * 120,
        data: props.forecasts.map((f) => {
          const value = f.lead_values[lead]
          return typeof value === 'number' && Number.isFinite(value) ? value : null
        }),
      })),
    },
    { notMerge: true },
  )
  if (el.value && !reduced) {
    gsap.fromTo(
      el.value,
      { autoAlpha: 0.35, y: 16 },
      { autoAlpha: 1, y: 0, duration: motionDuration(0.55), ease: 'power2.out' },
    )
  }
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
