import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LiveWorkflow from '../components/LiveWorkflow.vue'
import { diagramHtmlFor, displayNodeFor } from '../generated/workflow'

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
      '<svg><g data-node-id="task"><rect /></g><g data-node-id="check_data"><rect /></g><g data-node-id="forecast"><rect /></g><g data-node-id="diagnose"><rect /></g><g data-node-id="optimize"><rect /></g><g data-node-id="gate"><rect /></g><g data-node-id="keep"><rect /></g><g data-node-id="accept"><rect /></g><g data-node-id="rollback"><rect /></g><g data-node-id="report"><rect /></g></svg>'
    await iframe.trigger('load')
    expect(doc.querySelector('.live-current')?.getAttribute('data-node-id')).toBe('forecast')
    expect(doc.querySelector('.live-done')?.getAttribute('data-node-id')).toBe('check_data')
    expect(doc.querySelector('[data-node-id="optimize"]')?.classList.contains('live-pending')).toBe(true)
    const src = iframe.attributes('src')
    expect(src).toContain('embed=1')
    expect(src).toContain('motion=still')
    expect(src).not.toContain('play=1')
    expect(src).toContain('hydro-agent.v1.workflow.html')
    await wrapper.setProps({ action: 'A06_DIAGNOSE', status: 'running', completedActions: ['A05_FORECAST'] })
    expect(doc.querySelector('.live-current')?.getAttribute('data-node-id')).toBe('diagnose')
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
    await wrapper.setProps({ action: 'A09_RESOLVE', status: 'running', gateStatus: 'ACCEPT' })
    expect(doc.querySelector('.live-current')?.getAttribute('data-node-id')).toBe('accept')
    await wrapper.setProps({ action: 'A12_EVALUATE_REPORT', status: 'running', gateStatus: 'KEEP' })
    expect(doc.querySelector('.live-current')?.getAttribute('data-node-id')).toBe('report')
    wrapper.unmount()
  })

  it('maps diagnose and resolve branches from the workflow definition', () => {
    expect(displayNodeFor('A06_DIAGNOSE')).toBe('diagnose')
    expect(displayNodeFor('A09_RESOLVE', 'ACCEPT')).toBe('accept')
    expect(displayNodeFor('A09_RESOLVE', 'KEEP')).toBe('keep')
    expect(displayNodeFor('A09_RESOLVE', 'ROLLBACK')).toBe('rollback')
    expect(diagramHtmlFor('1.0.0')).toBe('hydro-agent.v1.workflow.html')
    expect(diagramHtmlFor('9.9.9')).toBe('hydro-agent.v1.workflow.html')
  })

  it('reveals the current node through Archify without stretching the svg', async () => {
    const reveal = vi.fn()
    const wrapper = mount(LiveWorkflow, {
      attachTo: document.body,
      props: { action: 'A05_FORECAST', status: 'running', completedActions: ['A01_CHECK_DATA'] },
    })
    const iframe = wrapper.find('iframe')
    const el = iframe.element as HTMLIFrameElement
    const doc = el.contentDocument!
    doc.appendChild(doc.createElement('html'))
    doc.documentElement.appendChild(doc.createElement('head'))
    doc.documentElement.appendChild(doc.createElement('body'))
    doc.body.innerHTML = '<svg><g data-node-id="forecast"><rect /></g><g data-node-id="diagnose"><rect /></g></svg>'
    const win = (doc.defaultView || el.contentWindow) as Window & { Archify?: { view: { reveal: typeof reveal } } }
    if (win) win.Archify = { view: { reveal } }
    await iframe.trigger('load')
    expect(wrapper.attributes('data-camera-node')).toBe('forecast')
    const injected = doc.getElementById('hydro-live-style')?.textContent || ''
    expect(injected).toContain('.diagram-container > svg { width:100%!important; height:auto!important;')
    if (reveal.mock.calls.length) {
      expect(reveal.mock.calls[0][0]).toEqual(['forecast'])
    }
    await wrapper.setProps({ action: 'A06_DIAGNOSE', status: 'running', completedActions: ['A05_FORECAST'] })
    expect(wrapper.attributes('data-camera-node')).toBe('diagnose')
    wrapper.unmount()
  })
})
