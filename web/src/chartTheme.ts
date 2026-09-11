import type { EChartsOption } from 'echarts'

export const CHART_COLORS = ['#1889EE', '#47B8B0', '#8E8BD4', '#DCA45A', '#D67C96'] as const
export const CHART_FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", sans-serif'

export const chartBase = {
  textStyle: { fontFamily: CHART_FONT, color: '#1d1d1f' },
  color: [...CHART_COLORS],
  tooltip: {
    trigger: 'axis' as const,
    confine: true,
    backgroundColor: 'rgba(255,255,255,0.96)',
    borderColor: '#e8e9ee',
    padding: [12, 16],
    textStyle: { color: '#1d1d1f', fontSize: 12, fontFamily: CHART_FONT },
    extraCssText: 'border-radius:14px;box-shadow:0 8px 28px rgba(25,40,65,0.08);',
    axisPointer: { type: 'line' as const, lineStyle: { color: '#9dbedc', type: 'dashed' as const } },
  },
  legend: {
    bottom: 0,
    itemWidth: 16,
    itemHeight: 7,
    itemGap: 18,
    icon: 'roundRect',
    textStyle: { color: '#698197', fontSize: 12, fontFamily: CHART_FONT },
  },
  grid: { left: 12, right: 18, top: 34, bottom: 48, containLabel: true },
}

export function formatFlow(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} m³/s`
    : '暂无数据'
}

export function hydrographTitleZh(item: {
  kind?: string
  title?: string
  calibrated?: boolean
  gate_status?: string | null
}): string {
  if (item.kind === 'calibration') return '观测与基线 / 候选 · 率定窗口'
  if (item.calibrated) return '观测与冻结方案 · 独立检验'
  if (item.gate_status === 'KEEP') return '观测与冻结方案 · 独立检验（维持原方案）'
  if (item.gate_status === 'ROLLBACK') return '观测与冻结方案 · 独立检验（已回退）'
  if (item.title?.includes('Calibration')) return '观测与基线 / 候选 · 率定窗口'
  return '观测与冻结方案 · 独立检验'
}

export function axisCategory(): EChartsOption['xAxis'] {
  return {
    type: 'category',
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { color: '#698197', fontSize: 12, hideOverlap: true },
  }
}

export function axisValue(name = '流量 · m³/s'): EChartsOption['yAxis'] {
  return {
    type: 'value',
    name,
    nameTextStyle: { color: '#698197', fontSize: 12, align: 'left' },
    splitLine: { lineStyle: { color: '#e7eef5', type: 'dashed' } },
    axisLabel: { color: '#698197', fontSize: 12 },
  }
}
