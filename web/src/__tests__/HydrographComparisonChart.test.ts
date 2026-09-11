import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import HydrographComparisonChart from '../components/HydrographComparisonChart.vue'

const mocks = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), init: vi.fn() }))
vi.mock('echarts', () => ({ init: mocks.init }))

it('renders observed vs frozen series and captions', async () => {
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
    title: 'Observed vs Frozen Scheme · Independent Test (kept baseline)',
    calibrated: false,
    gate_status: 'KEEP',
    warmup_days: 1,
    evaluated_days: 2,
    series: [
      { time: '2020-05-01', observed_m3s: 10, frozen_m3s: 9, window: 'warmup', is_warmup: true },
      { time: '2020-05-02', observed_m3s: 11, frozen_m3s: 10.5, window: 'test', is_warmup: false },
    ],
    frozen_metrics: { nse: 0.4, rmse_m3s: 1.2 },
  }
  const wrapper = mount(HydrographComparisonChart, { props: { comparison: null } })
  await flushPromises()
  expect(mocks.init).not.toHaveBeenCalled()
  await wrapper.setProps({ comparison })
  await flushPromises()
  expect(mocks.init).toHaveBeenCalledTimes(1)
  expect(mocks.setOption).toHaveBeenCalled()
  expect(wrapper.text()).toContain('冻结方案')
  expect(wrapper.text()).toContain('未称作率定成功')
  const option = mocks.setOption.mock.calls[0][0] as { series: Array<{ name: string }> }
  expect(option.series.map((row) => row.name)).toEqual(['观测', '冻结方案'])
  resize()
  wrapper.unmount()
  vi.unstubAllGlobals()
})
