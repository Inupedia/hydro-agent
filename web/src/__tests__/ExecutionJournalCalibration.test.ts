import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ExecutionJournal from '../components/ExecutionJournal.vue'

const mocks = vi.hoisted(() => ({ getAgentLog: vi.fn() }))
vi.mock('../api/client', () => ({ api: { getAgentLog: mocks.getAgentLog } }))

function round(action: string, observations: string[], at: string) {
  return {
    round_number: action === 'A05_OPTIMIZE' ? 7 : 9,
    occurred_at: at,
    action,
    action_zh: action === 'A05_OPTIMIZE' ? '参数率定' : '落实候选',
    hypothesis: 'MODEL',
    hypothesis_zh: '模型参数问题',
    strategy_id: 'xaj-bounded-v1',
    rationale_summary: '根据独立证据推进率定实验。',
    llm_output: '',
    input_summary_zh: '',
    judgment_zh: '',
    input_world_state: {},
    tool_status: 'succeeded',
    tool_status_zh: '已完成',
    tool_observations: observations,
    tool_metrics: {},
    error: null,
  }
}

describe('ExecutionJournal calibration scientist state', () => {
  it('shows DDS budget and adopted-but-unqualified candidate without calling calibration complete', async () => {
    mocks.getAgentLog.mockResolvedValue({
      task_id: 'task-cal',
      rounds: [
        round(
          'A05_OPTIMIZE',
          ['optimizer=dds', 'evaluation_budget=512', 'model_evaluations=487'],
          '2026-09-13T06:00:07Z',
        ),
        round(
          'A07_RESOLVE',
          [
            'resolve_status=KEEP',
            'adoption_status=ADOPT',
            'qualification_status=UNQUALIFIED',
            'candidate_adopted=true',
          ],
          '2026-09-13T06:00:09Z',
        ),
      ],
    })

    const wrapper = mount(ExecutionJournal, {
      props: {
        taskId: 'task-cal',
        running: false,
        completed: false,
        failed: false,
        elapsed: '0:20',
        events: [
          {
            id: 'opt',
            occurred_at: '2026-09-13T06:00:07Z',
            label: '参数率定',
            status: 'succeeded',
            action: 'A05_OPTIMIZE',
            evidence_id: 'ev-opt',
            details: {},
          },
          {
            id: 'resolve',
            occurred_at: '2026-09-13T06:00:09Z',
            label: '落实候选',
            status: 'KEEP',
            action: 'A07_RESOLVE',
            evidence_id: 'ev-resolve',
            details: {},
          },
        ],
      },
    })

    await flushPromises()
    const cards = wrapper.findAll('.journal-event-card')
    expect(cards[0].text()).toContain('DDS')
    expect(cards[0].text()).toContain('预算 512')
    expect(cards[0].text()).toContain('模型运行 487')
    expect(cards[1].text()).toContain('采用候选，继续率定')
    expect(cards[1].text()).toContain('已采用')
    expect(cards[1].text()).toContain('未达标')
    expect(cards[1].text()).toContain('新的当前方案')
    expect(cards[1].text()).not.toContain('保留原方案')
  })
  it('keeps hydrologic diagnosis event evidence traceable in the journal', async () => {
    mocks.getAgentLog.mockResolvedValue({
      task_id: 'task-cal',
      rounds: [
        round(
          'A04_DIAGNOSE',
          [
            '洪峰偏低：event-001、event-002',
            '峰现偏晚：event-001、event-002',
          ],
          '2026-09-13T06:00:04Z',
        ),
      ],
    })

    const wrapper = mount(ExecutionJournal, {
      props: {
        taskId: 'task-cal',
        running: false,
        completed: false,
        failed: false,
        elapsed: '0:10',
        events: [
          {
            id: 'diagnose',
            occurred_at: '2026-09-13T06:00:04Z',
            label: '水文诊断',
            status: 'succeeded',
            action: 'A04_DIAGNOSE',
            evidence_id: 'ev-diagnose',
            details: {},
          },
        ],
      },
    })

    await flushPromises()
    const card = wrapper.find('.journal-event-card')
    expect(card.text()).toContain('洪峰偏低')
    expect(card.text()).toContain('峰现偏晚')
    expect(card.text()).toContain('event-001')
    expect(card.text()).toContain('event-002')
  })
})
