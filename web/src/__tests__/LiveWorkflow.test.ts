import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LiveWorkflow from '../components/LiveWorkflow.vue'

describe('live Archify state', () => {
  it('tracks action changes without reloading the diagram and preserves blocked state', async () => {
    const wrapper = mount(LiveWorkflow, {
      attachTo: document.body,
      props: { action: 'A05_FORECAST', status: 'running', completedActions: ['A01_CHECK_DATA'] },
    })
    const iframe = wrapper.find('iframe')
    const doc = (iframe.element as HTMLIFrameElement).contentDocument!
    doc.appendChild(doc.createElement('html'))
    doc.documentElement.appendChild(doc.createElement('head'))
    doc.documentElement.appendChild(doc.createElement('body'))
    doc.body.innerHTML =
      '<svg><g data-node-id="task"><rect /></g><g data-node-id="forecast"><rect /></g><g data-node-id="optimize"><rect /></g><g data-node-id="gate"><rect /></g><g data-node-id="keep"><rect /></g><g data-node-id="results"><rect /></g></svg>'
    await iframe.trigger('load')
    expect(doc.querySelector('.live-current')?.getAttribute('data-node-id')).toBe('forecast')
    expect(doc.querySelector('.live-done')?.getAttribute('data-node-id')).toBe('task')
    expect(doc.querySelector('[data-node-id="optimize"]')?.classList.contains('live-pending')).toBe(true)
    const src = iframe.attributes('src')
    expect(src).toContain('embed=1')
    expect(src).toContain('motion=still')
    expect(src).not.toContain('play=1')
    await wrapper.setProps({ action: 'A07_OPTIMIZE', status: 'failed', completedActions: ['A05_FORECAST'] })
    expect(doc.querySelectorAll('.live-current')).toHaveLength(1)
    expect(doc.querySelector('.live-current')?.getAttribute('data-node-id')).toBe('optimize')
    expect(doc.querySelector('.live-blocked')?.getAttribute('aria-current')).toBe('step')
    expect(iframe.attributes('src')).toBe(src)
    await wrapper.setProps({
      action: 'A08_GATE',
      status: 'running',
      completedActions: ['A05_FORECAST', 'A07_OPTIMIZE', 'A08_GATE'],
      gateStatus: 'KEEP',
    })
    expect(doc.querySelector('.live-current')?.getAttribute('data-node-id')).toBe('gate')
    expect(doc.querySelector('[data-node-id="keep"]')?.classList.contains('live-done')).toBe(true)
    await wrapper.setProps({ action: 'A12_EVALUATE_REPORT', status: 'running', gateStatus: 'KEEP' })
    expect(doc.querySelector('.live-current')?.getAttribute('data-node-id')).toBe('results')
    wrapper.unmount()
  })
})
