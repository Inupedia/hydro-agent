import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import HydrographComparisonChart from '../components/HydrographComparisonChart.vue'

const mocks = vi.hoisted(() => ({
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
  init: vi.fn(),
  linearGradient: vi.fn((...args: unknown[]) => ({ type: 'linear', args })),
}))
vi.mock('echarts', () => ({
  init: mocks.init,
  graphic: { LinearGradient: mocks.linearGradient },
}))

it('renders observed, baseline and final scheme in one comparison chart', async () => {
  let resize: () => void = () => {}
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(cb: () => void) {
        resize = cb
      }
      observe() {}
      disconnect() {}
    },
  )
  mocks.init.mockReturnValue(mocks)
  const comparison = {
    kind: 'independent_test' as const,
    title: 'Independent test',
    calibrated: false,
    gate_status: 'KEEP',
    warmup_days: 1,
    evaluated_days: 2,
    series: [
      { time: '2020-05-01', observed_m3s: 10, baseline_m3s: 9, frozen_m3s: 9, window: 'warmup', is_warmup: true },
      { time: '2020-05-02', observed_m3s: 11, baseline_m3s: 10.5, frozen_m3s: 10.5, window: 'test', is_warmup: false },
    ],
    baseline_metrics: { nse: 0.4, rmse_m3s: 1.2, start_date: '2020-05-02' },
    frozen_metrics: { nse: 0.4, rmse_m3s: 1.2 },
  }
  const wrapper = mount(HydrographComparisonChart, { props: { comparison: null } })
  await flushPromises()
  expect(mocks.init).not.toHaveBeenCalled()
  await wrapper.setProps({ comparison })
  await flushPromises()
  expect(mocks.init).toHaveBeenCalledTimes(1)
  expect(mocks.setOption).toHaveBeenCalled()
  expect(wrapper.text()).toContain('基准方案')
  expect(wrapper.text()).toContain('最终方案')
  expect(wrapper.text()).toContain('维持原方案')
  const option = mocks.setOption.mock.calls[0][0] as { series: Array<{ name: string; lineStyle?: { width?: number } }> }
  expect(option.series.map((row) => row.name)).toEqual(['观测', '基准方案', '最终方案'])
  expect(option.series.map((row) => row.lineStyle?.width)).toEqual([2.5, 1.25, 2.75])
  expect(wrapper.text()).toContain('维持原方案后，过程线仍与观测对照')
  expect(mocks.linearGradient).toHaveBeenCalledTimes(1)
  resize()
  wrapper.unmount()
  vi.unstubAllGlobals()
})
