import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LiveWorkflow from '../components/LiveWorkflow.vue'
import { displayNodeFor } from '../generated/workflow'

describe('live workflow map', () => {
  it('renders the workflow natively without an iframe', () => {
    const wrapper = mount(LiveWorkflow, {
      props: {
        action: 'A05_FORECAST',
        status: 'running',
        completedActions: ['A01_CHECK_DATA', 'A03_VALIDATE_SCHEME'],
        workflowVersion: '1.0.0',
      },
    })

    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.find('[data-node-id="forecast"]').classes()).toContain('is-current')
    expect(wrapper.find('[data-node-id="check_data"]').classes()).toContain('is-done')
    expect(wrapper.find('[data-node-id="validate_scheme"]').classes()).toContain('is-done')
    expect(wrapper.find('[data-node-id="diagnose"]').classes()).toContain('is-pending')
    expect(wrapper.text()).toContain('v1.0.0')
  })

  it('maps Gate decisions to the visible branch and preserves completion state', async () => {
    const wrapper = mount(LiveWorkflow, {
      props: {
        action: 'A08_GATE',
        status: 'running',
        completedActions: ['A05_FORECAST', 'A06_DIAGNOSE', 'A07_OPTIMIZE'],
        gateStatus: 'KEEP',
      },
    })

    expect(wrapper.find('[data-node-id="gate"]').classes()).toContain('is-current')
    expect(wrapper.find('[data-node-id="keep"]').classes()).toContain('is-done')

    await wrapper.setProps({ action: 'A09_RESOLVE', status: 'running', gateStatus: 'ACCEPT' })
    expect(wrapper.find('[data-node-id="accept"]').classes()).toContain('is-current')
    expect(wrapper.find('[data-node-id="accept"]').attributes('aria-current')).toBe('step')

    await wrapper.setProps({ action: 'A09_RESOLVE', status: 'failed', gateStatus: 'ROLLBACK' })
    expect(wrapper.find('[data-node-id="rollback"]').classes()).toContain('is-blocked')
  })

  it('uses workflow metadata for runtime node mapping', () => {
    expect(displayNodeFor('A06_DIAGNOSE')).toBe('diagnose')
    expect(displayNodeFor('A09_RESOLVE', 'ACCEPT')).toBe('accept')
    expect(displayNodeFor('A09_RESOLVE', 'KEEP')).toBe('keep')
    expect(displayNodeFor('A09_RESOLVE', 'ROLLBACK')).toBe('rollback')
    expect(displayNodeFor('A09_RESOLVE', 'failed')).toBe('blocked')
  })
})
