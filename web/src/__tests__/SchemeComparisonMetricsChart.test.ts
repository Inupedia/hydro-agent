import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import SchemeComparisonMetricsChart from '../components/SchemeComparisonMetricsChart.vue'

const mocks = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), init: vi.fn() }))
vi.mock('echarts', () => ({ init: mocks.init }))

it('compares baseline and final NSE/KGE when hydrograph metrics exist', async () => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  mocks.init.mockReturnValue(mocks)
  const comparison = {
    kind: 'independent_test' as const,
    title: 'Independent test',
    calibrated: true,
    gate_status: 'ACCEPT',
    warmup_days: 1,
    evaluated_days: 10,
    series: [],
    baseline_metrics: { nse: 0.31, kge: 0.42 },
    frozen_metrics: { nse: 0.67, kge: 0.71 },
  }
  const wrapper = mount(SchemeComparisonMetricsChart, { props: { comparison } })
  await flushPromises()
  expect(wrapper.find('[data-test="scheme-metric-comparison"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('独立检验 · NSE / KGE · 越高越好')
  expect(wrapper.text()).toContain('最终方案在可比指标上抬升')
  expect(mocks.setOption).toHaveBeenCalledTimes(1)
  const option = mocks.setOption.mock.calls[0][0] as {
    xAxis: { data: string[] }
    series: Array<{ name: string; data: Array<number | null> }>
  }
  expect(option.xAxis.data).toEqual(['NSE', 'KGE'])
  expect(option.series.map((item) => item.name)).toEqual(['基准方案', '最终方案'])
  expect(option.series[0].data).toEqual([0.31, 0.42])
  expect(option.series[1].data).toEqual([0.67, 0.71])
  wrapper.unmount()
  vi.unstubAllGlobals()
})

it('falls back to Gate comparison before the process-line artifact arrives', async () => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  mocks.init.mockReturnValue(mocks)
  const wrapper = mount(SchemeComparisonMetricsChart, {
    props: {
      comparison: null,
      gate: { metrics: { base_primary: 0.12, candidate_primary: 0.48 } },
    },
  })
  await flushPromises()
  expect(wrapper.find('[data-test="scheme-metric-comparison"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('过程线尚未就绪')
  const option = mocks.setOption.mock.calls.at(-1)?.[0] as {
    series: Array<{ name: string; data: Array<number | null> }>
  }
  expect(option.series.map((item) => item.name)).toEqual(['基准方案', '候选方案'])
  expect(option.series[0].data).toEqual([0.12])
  expect(option.series[1].data).toEqual([0.48])
  wrapper.unmount()
  vi.unstubAllGlobals()
})
