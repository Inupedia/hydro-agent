import type { EChartsOption } from 'echarts'

/** macOS Liquid Glass series palette - keep as product chart colors. */
export const CHART_COLORS = ['#1889EE', '#47B8B0', '#8E8BD4', '#DCA45A', '#D67C96'] as const

/** Editorial ink ladder on the macOS surface (lieflat hierarchy, not mono paper). */
export const CHART_INK = {
  text: '#1D1D1F',
  secondary: '#62626A',
  tertiary: '#85858E',
  muted: '#698197',
  grid: '#E7EEF5',
  gridSoft: 'rgba(231, 238, 245, 0.72)',
  separator: '#E8E9EE',
  tooltipBorder: '#E8E9EE',
  warmup: 'rgba(231, 235, 241, 0.52)',
  areaPrimary: 'rgba(24, 137, 238, 0.16)',
  areaAccent: 'rgba(142, 139, 212, 0.16)',
} as const

export const CHART_FONT =
  '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", sans-serif'

export function prefersChartReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function chartMotion(ms = 480, dense = false): { duration: number; easing: string } {
  if (dense || prefersChartReducedMotion()) return { duration: 0, easing: 'cubicOut' }
  return { duration: ms, easing: 'cubicOut' }
}

export const chartBase = {
  textStyle: { fontFamily: CHART_FONT, color: CHART_INK.text, fontWeight: 500 },
  color: [...CHART_COLORS],
  animationEasing: 'cubicOut' as const,
  tooltip: {
    trigger: 'axis' as const,
    confine: true,
    backgroundColor: 'rgba(255,255,255,0.96)',
    borderColor: CHART_INK.tooltipBorder,
    borderWidth: 1,
    padding: [12, 16],
    textStyle: { color: CHART_INK.text, fontSize: 12, fontFamily: CHART_FONT, fontWeight: 500 },
    extraCssText:
      'border-radius:14px;box-shadow:0 8px 28px rgba(25,40,65,0.08);backdrop-filter:saturate(140%) blur(8px);',
    axisPointer: {
      type: 'line' as const,
      lineStyle: { color: '#9DBEDC', width: 1, type: 'dashed' as const },
    },
  },
  legend: {
    bottom: 0,
    itemWidth: 14,
    itemHeight: 3,
    itemGap: 20,
    icon: 'roundRect',
    textStyle: {
      color: CHART_INK.muted,
      fontSize: 11.5,
      fontFamily: CHART_FONT,
      fontWeight: 500,
    },
  },
  grid: { left: 10, right: 16, top: 36, bottom: 52, containLabel: true },
}

export function formatFlow(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} m³/s`
    : '暂无数据'
}

export function formatMetric(value: unknown, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '-'
}

/** Conclusion-style titles (lieflat) while staying product Chinese. */
export function hydrographTitleZh(item: {
  kind?: string
  title?: string
  calibrated?: boolean
  gate_status?: string | null
}): string {
  if (item.kind === 'calibration') return '率定窗里，观测、基准与候选差在哪里'
  if (item.calibrated) return '独立检验：最终方案是否贴住观测'
  if (item.gate_status === 'KEEP') return '维持原方案后，过程线仍与观测对照'
  if (item.gate_status === 'ROLLBACK') return '回退后的安全方案，是否还跟得上观测'
  if (item.title?.includes('Calibration')) return '率定窗里，观测、基准与候选差在哪里'
  return '独立检验：最终方案是否贴住观测'
}

export function axisCategory(): EChartsOption['xAxis'] {
  return {
    type: 'category',
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: {
      color: CHART_INK.muted,
      fontSize: 11,
      fontWeight: 500,
      fontFamily: CHART_FONT,
      hideOverlap: true,
      margin: 12,
    },
  }
}

export function axisValue(name = '流量 · m³/s'): EChartsOption['yAxis'] {
  return {
    type: 'value',
    name,
    nameGap: 10,
    nameTextStyle: {
      color: CHART_INK.tertiary,
      fontSize: 11,
      fontWeight: 600,
      fontFamily: CHART_FONT,
      align: 'left',
      padding: [0, 0, 0, 0],
    },
    splitNumber: 4,
    splitLine: {
      lineStyle: {
        color: CHART_INK.grid,
        type: 'dashed',
        width: 1,
        opacity: 0.9,
      },
    },
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: CHART_INK.muted,
      fontSize: 11,
      fontWeight: 500,
      fontFamily: CHART_FONT,
    },
  }
}

/** Capsule bar ends - lieflat SHAPE.barRadius, kept on macOS surfaces. */
export const BAR_CAPSULE = [999, 999, 4, 4] as const
