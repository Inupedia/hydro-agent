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

type ChartInk = typeof CHART_INK

function cssToken(name: string, fallback: string): string {
  if (typeof window === 'undefined' || typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

/** Canvas charts cannot inherit CSS variables, so resolve the app theme at render time. */
export function currentChartTheme(): {
  colors: readonly string[]
  ink: ChartInk
  symbolBorder: string
  base: typeof chartBase
} {
  const dark = typeof document !== 'undefined' && document.documentElement.dataset.theme === 'dark'
  const colors = dark
    ? ['#4ea8ff', '#5bc9bb', '#aea9f0', '#e7b86e', '#e99bb3']
    : [...CHART_COLORS]
  const ink: ChartInk = {
    text: cssToken('--text-primary', CHART_INK.text),
    secondary: cssToken('--text-secondary', CHART_INK.secondary),
    tertiary: cssToken('--text-tertiary', CHART_INK.tertiary),
    muted: cssToken('--chart-axis', CHART_INK.muted),
    grid: cssToken('--chart-grid', CHART_INK.grid),
    gridSoft: dark ? 'rgba(57, 66, 80, 0.72)' : CHART_INK.gridSoft,
    separator: cssToken('--separator', CHART_INK.separator),
    tooltipBorder: cssToken('--border', CHART_INK.tooltipBorder),
    warmup: dark ? 'rgba(81, 96, 116, 0.3)' : CHART_INK.warmup,
    areaPrimary: dark ? 'rgba(78, 168, 255, 0.2)' : CHART_INK.areaPrimary,
    areaAccent: dark ? 'rgba(174, 169, 240, 0.22)' : CHART_INK.areaAccent,
  }
  const base = {
    ...chartBase,
    color: [...colors],
    textStyle: { ...chartBase.textStyle, color: ink.text },
    tooltip: {
      ...chartBase.tooltip,
      backgroundColor: dark ? 'rgba(32,35,41,0.98)' : 'rgba(255,255,255,0.96)',
      borderColor: ink.tooltipBorder,
      textStyle: { ...chartBase.tooltip.textStyle, color: ink.text },
      extraCssText: `border-radius:14px;box-shadow:${dark ? '0 12px 32px rgba(0,0,0,0.28)' : '0 8px 28px rgba(25,40,65,0.08)'};backdrop-filter:saturate(140%) blur(8px);`,
      axisPointer: {
        ...chartBase.tooltip.axisPointer,
        lineStyle: { color: dark ? '#70839b' : '#9DBEDC', width: 1, type: 'dashed' as const },
      },
    },
    legend: { ...chartBase.legend, textStyle: { ...chartBase.legend.textStyle, color: ink.muted } },
  }
  return { colors, ink, symbolBorder: cssToken('--surface', '#ffffff'), base }
}

export function prefersChartReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Preserve one deliberate first-paint trace even for long hydrographs. Dense data
 * used to disable motion entirely, which made the result screen feel abruptly
 * assembled rather than calculated. Updates stay short so filters/theme changes
 * never become a slideshow.
 */
export function chartMotion(ms = 480, dense = false): { duration: number; easing: string } {
  if (prefersChartReducedMotion()) return { duration: 0, easing: 'cubicOut' }
  return { duration: dense ? Math.min(ms, 760) : ms, easing: 'cubicOut' }
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

export function axisCategory(ink = CHART_INK): EChartsOption['xAxis'] {
  return {
    type: 'category',
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: {
      color: ink.muted,
      fontSize: 11,
      fontWeight: 500,
      fontFamily: CHART_FONT,
      hideOverlap: true,
      margin: 12,
    },
  }
}

export function axisValue(name = '流量 · m³/s', ink = CHART_INK): EChartsOption['yAxis'] {
  return {
    type: 'value',
    name,
    nameGap: 10,
    nameTextStyle: {
      color: ink.tertiary,
      fontSize: 11,
      fontWeight: 600,
      fontFamily: CHART_FONT,
      align: 'left',
      padding: [0, 0, 0, 0],
    },
    splitNumber: 4,
    splitLine: {
      lineStyle: {
        color: ink.grid,
        type: 'dashed',
        width: 1,
        opacity: 0.9,
      },
    },
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: ink.muted,
      fontSize: 11,
      fontWeight: 500,
      fontFamily: CHART_FONT,
    },
  }
}

/** Capsule bar ends - lieflat SHAPE.barRadius, kept on macOS surfaces. */
export const BAR_CAPSULE = [999, 999, 4, 4] as const
