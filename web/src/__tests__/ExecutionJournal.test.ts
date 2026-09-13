import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ExecutionJournal from '../components/ExecutionJournal.vue'

const mocks = vi.hoisted(() => ({
  getAgentLog: vi.fn(async () => ({
    task_id: 'task-1',
    rounds: [
      {
        round_number: 3,
        occurred_at: '2026-09-13T06:00:02Z',
        action: 'A06_DIAGNOSE',
        action_zh: '预报诊断',
        hypothesis: 'MODEL',
        hypothesis_zh: '更像是模型参数导致洪峰低估',
        strategy_id: null,
        rationale_summary: '当前 NSE 仍低于门槛，因此需要判断是否进入有限调参。',
        llm_output: 'internal text should not be rendered',
        input_summary_zh: '比较观测与预报',
        judgment_zh: '洪峰持续偏低，优先检查模型参数而不是直接接受当前方案。',
        input_world_state: {},
        tool_status: 'succeeded',
        tool_status_zh: '已完成',
        tool_observations: ['洪峰低估', '退水段偏慢'],
        tool_metrics: { NSE: 0.42 },
        error: null,
      },
    ],
  })),
}))

vi.mock('../api/client', () => ({ api: { getAgentLog: mocks.getAgentLog } }))

describe('ExecutionJournal', () => {
  it('shows the complete record chronologically with explainable agent summaries', async () => {
    const wrapper = mount(ExecutionJournal, {
      props: {
        taskId: 'task-1',
        running: false,
        completed: true,
        failed: false,
        elapsed: '已结束',
        events: [
          {
            id: 'later',
            occurred_at: '2026-09-13T06:00:02Z',
            label: '完成诊断',
            status: 'succeeded',
            action: 'A06_DIAGNOSE',
            evidence_id: 'ev-2',
            details: { raw_metric: 0.42 },
          },
          {
            id: 'earlier',
            occurred_at: '2026-09-13T06:00:01Z',
            label: '完成基础预报',
            status: 'succeeded',
            action: 'A05_FORECAST',
            evidence_id: 'ev-1',
            details: { forecast_id: 'fc-1' },
          },
        ],
      },
    })

    await flushPromises()

    const cards = wrapper.findAll('.journal-event-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('完成基础预报')
    expect(cards[1].text()).toContain('洪峰持续偏低')
    expect(cards[1].text()).toContain('预报诊断')
    expect(cards[1].text()).toContain('当前 NSE 仍低于门槛')
    expect(cards[1].text()).toContain('洪峰低估；退水段偏慢')
    expect(cards[1].text()).not.toContain('internal text should not be rendered')
    expect(cards[1].find('.technical-details pre').text()).toContain('raw_metric')
    expect(mocks.getAgentLog).toHaveBeenCalledWith('task-1')
  })

  it('falls back to workflow descriptions when no agent decision exists', async () => {
    mocks.getAgentLog.mockResolvedValueOnce({ task_id: 'task-2', rounds: [] })
    const wrapper = mount(ExecutionJournal, {
      props: {
        taskId: 'task-2',
        running: true,
        completed: false,
        failed: false,
        elapsed: '0:03',
        events: [
          {
            id: 'forecast',
            occurred_at: '2026-09-13T06:00:01Z',
            label: '正在计算',
            status: 'running',
            action: 'A05_FORECAST',
            evidence_id: null,
            details: {},
          },
        ],
      },
    })

    await flushPromises()
    expect(wrapper.text()).toContain('用当前方案计算未来几天的流量')
    expect(wrapper.text()).toContain('当前步骤仍在执行')
  })
})
