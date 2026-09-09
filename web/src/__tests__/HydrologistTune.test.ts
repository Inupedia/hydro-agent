import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import HydrologistTune from '../components/HydrologistTune.vue'

vi.mock('../api/client', () => ({
  api: {
    createHydrologistSession: vi.fn(async () => ({
      session_id: 'tune-demo',
      plan_id: 'plan-1',
      stage: 'created',
      status: 'ready',
      editable: ['K', 'CS'],
      baseline_params: { K: 0.9, CS: 0.65 },
      current_params: { K: 0.9, CS: 0.65 },
    })),
    hydrologistStep: vi.fn(),
  },
}))

describe('HydrologistTune', () => {
  it('renders notebook-style actions', async () => {
    const wrapper = mount(HydrologistTune, {
      props: { planId: 'plan-1', taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('手工改参')
    await wrapper.get('button').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('tune-demo')
  })
})
