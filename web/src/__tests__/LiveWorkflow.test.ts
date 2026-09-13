import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LiveWorkflow from '../components/LiveWorkflow.vue'
import { displayNodeFor } from '../generated/workflow'

describe('live workflow map', () => {
  it('shows six equal presentation stages while focusing only the current stage', () => {
    const wrapper = mount(LiveWorkflow, {
      props: {
        action: 'A05_FORECAST',
        status: 'running',
        completedActions: ['A01_CHECK_DATA', 'A03_VALIDATE_SCHEME'],
        workflowVersion: '1.0.0',
      },
    })

    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.findAll('.stage-summary-item')).toHaveLength(6)
    expect(wrapper.find('[data-stage="forecast"]').classes()).toContain('is-current')
    expect(wrapper.find('[data-stage="prepare"]').classes()).toContain('is-visited')
    expect(wrapper.find('[data-focus-stage="forecast"]').exists()).toBe(true)
    expect(wrapper.find('[data-node-id="forecast"]').classes()).toContain('is-current')
    expect(wrapper.find('[data-node-id="check_data"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('v1.0.0')
  })

  it('shows diagnosis as a conditional split instead of a false linear completion chain', () => {
    const wrapper = mount(LiveWorkflow, {
      props: {
        action: 'A06_DIAGNOSE',
        status: 'running',
        completedActions: ['A01_CHECK_DATA', 'A03_VALIDATE_SCHEME', 'A05_FORECAST'],
      },
    })

    expect(wrapper.find('[data-focus-stage="diagnose"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('需要率定')
    expect(wrapper.text()).toContain('04 参数调整')
    expect(wrapper.text()).toContain('已经够用')
    expect(wrapper.text()).toContain('06 结果确认')
  })

  it('renders Gate decisions and the explicit retry loop back to calibration', async () => {
    const wrapper = mount(LiveWorkflow, {
      props: {
        action: 'A08_GATE',
        status: 'running',
        completedActions: ['A05_FORECAST', 'A06_DIAGNOSE', 'A07_OPTIMIZE'],
      },
    })

    expect(wrapper.find('[data-focus-stage="gate"]').exists()).toBe(true)
    expect(wrapper.find('[data-node-id="gate"]').classes()).toContain('is-current')
    expect(wrapper.text()).toContain('KEEP / ROLLBACK 且预算允许 → 回到 04 参数调整')

    await wrapper.setProps({ action: 'A09_RESOLVE', status: 'running', gateStatus: 'KEEP' })
    expect(wrapper.find('[data-node-id="keep"]').classes()).toContain('is-current')
    expect(wrapper.find('[data-node-id="accept"]').classes()).toContain('is-pending')

    await wrapper.setProps({ action: 'A09_RESOLVE', status: 'failed', gateStatus: 'ROLLBACK' })
    expect(wrapper.find('[data-node-id="rollback"]').classes()).toContain('is-blocked')
  })

  it('uses visited rather than completed semantics for previously executed nodes', () => {
    const wrapper = mount(LiveWorkflow, {
      props: {
        action: 'A12_EVALUATE_REPORT',
        status: 'running',
        completedActions: ['A10_FREEZE', 'A11_REPLAY'],
      },
    })

    expect(wrapper.find('[data-node-id="freeze"]').classes()).toContain('is-visited')
    expect(wrapper.find('[data-node-id="replay"]').classes()).toContain('is-visited')
    expect(wrapper.find('[data-node-id="report"]').classes()).toContain('is-current')
    expect(wrapper.text()).toContain('已经过，不代表不会再次进入')
  })

  it('keeps workflow metadata mapping unchanged', () => {
    expect(displayNodeFor('A06_DIAGNOSE')).toBe('diagnose')
    expect(displayNodeFor('A09_RESOLVE', 'ACCEPT')).toBe('accept')
    expect(displayNodeFor('A09_RESOLVE', 'KEEP')).toBe('keep')
    expect(displayNodeFor('A09_RESOLVE', 'ROLLBACK')).toBe('rollback')
    expect(displayNodeFor('A09_RESOLVE', 'failed')).toBe('blocked')
  })
})
