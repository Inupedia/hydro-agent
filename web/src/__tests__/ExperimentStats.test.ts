import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ExperimentStats from '../components/ExperimentStats.vue'
import type { AgentRoundLogItem } from '../types/api'

describe('ExperimentStats', () => {
  it('does not count decision-only legacy rounds as tool calls', () => {
    const rounds = [
      {
        round_number: 1,
        action: 'A04_DIAGNOSE',
        tool_calls: [{ action: 'A04_DIAGNOSE', tool_id: 'hydrology.diagnose', category: 'diagnosis', status: 'completed' }],
      },
      {
        round_number: 2,
        action: 'A05_OPTIMIZE',
        tool_calls: [{ action: 'A05_OPTIMIZE', tool_id: 'calibration.optimize', category: 'optimization', status: 'pending', trace_source: 'legacy_inferred' }],
      },
    ] as AgentRoundLogItem[]
    const wrapper = mount(ExperimentStats, { props: { rounds } })
    expect(wrapper.findAll('dd')[2].text()).toBe('1')
  })
})
