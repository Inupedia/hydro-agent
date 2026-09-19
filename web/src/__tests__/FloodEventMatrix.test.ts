import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FloodEventMatrix from '../components/FloodEventMatrix.vue'

describe('FloodEventMatrix', () => {
  it('renders multiple flood events and hydrologic diagnosis evidence', () => {
    const wrapper = mount(FloodEventMatrix, {
      props: {
        events: [
          {
            event_id: 'event-001',
            start: '2020-07-01',
            end: '2020-07-05',
            basis: 'rainfall_runoff',
            status: 'available',
            metrics: {
              peak_relative_error: -0.18,
              peak_timing_lag_steps: 1,
              volume_relative_error: 0.03,
              rising_limb_mae: 8.1,
              recession_mae: 4.2,
            },
          },
          {
            event_id: 'event-002',
            start: '2020-07-16',
            end: '2020-07-20',
            basis: 'rainfall_runoff',
            status: 'available',
            metrics: {
              peak_relative_error: -0.11,
              peak_timing_lag_steps: 1,
              volume_relative_error: 0.01,
              rising_limb_mae: 6.3,
              recession_mae: 3.8,
            },
          },
        ],
      },
    })

    expect(wrapper.text()).toContain('event-001')
    expect(wrapper.text()).toContain('event-002')
    expect(wrapper.text()).toContain('洪峰误差')
    expect(wrapper.text()).toContain('峰现偏差')
    expect(wrapper.text()).toContain('洪量误差')
    expect(wrapper.text()).toContain('涨水段')
    expect(wrapper.text()).toContain('退水段')
    expect(wrapper.text()).toContain('证据状态')
    expect(wrapper.text()).not.toContain('AI 综合评分')
  })
})
