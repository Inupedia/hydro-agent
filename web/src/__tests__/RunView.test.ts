import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BusinessTimeline from '../components/BusinessTimeline.vue'
import type { TimelineItem } from '../types/api'

function mountRunViewWithTimeline(items: TimelineItem[]) {
  return mount(BusinessTimeline, { props: { items } })
}

describe('Run timeline', () => {
  it('shows business timeline first and technical ids only when expanded', async () => {
    const wrapper = mountRunViewWithTimeline([
      {
        id: 't1',
        occurred_at: '2020-05-01T00:00:00Z',
        label: '正在运行水文模型',
        status: 'running',
        action: 'A05_FORECAST',
        evidence_id: 'ev-1',
        details: { action_run_id: 'run-1' },
      },
    ])
    expect(wrapper.text()).toContain('正在运行水文模型')
    expect(wrapper.text()).not.toContain('run-1')
    await wrapper.get('[data-test="timeline-expand-t1"]').trigger('click')
    expect(wrapper.text()).toContain('run-1')
  })
})
