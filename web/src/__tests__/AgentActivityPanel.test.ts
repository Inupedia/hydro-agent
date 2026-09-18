import { flushPromises, mount } from '@vue/test-utils'
import { PhCaretDown, PhCaretUp } from '@phosphor-icons/vue'
import { describe, expect, it, vi } from 'vitest'
import AgentActivityPanel from '../components/AgentActivityPanel.vue'

const mocks = vi.hoisted(() => ({ getAgentLog: vi.fn() }))
vi.mock('../api/client', () => ({ api: { getAgentLog: mocks.getAgentLog } }))

describe('AgentActivityPanel', () => {
  it('renders the observation, skills, decision, tools and evidence chain', async () => {
    mocks.getAgentLog.mockResolvedValue({ task_id: 'task-1', rounds: [{
      round_number: 4,
      action: 'A05_OPTIMIZE', action_zh: '参数率定', hypothesis_zh: '模型参数问题',
      strategy_id: 'xaj-bounded-v1', rationale_summary: '执行有限参数搜索。',
      llm_output: JSON.stringify({ observation_zh: '洪峰持续偏低。', analysis_zh: '产流参数可能不足。', decision_zh: '启动有限参数优化。', param_groups: ['runoff', 'routing'], objective: 'nse' }),
      input_summary_zh: '', judgment_zh: '', input_world_state: {},
      activated_skill_ids: ['xaj-calibration-diagnosis'], activated_skills_audit: [],
      experience_skill_version: 4, experience_skill_hash: 'e'.repeat(64),
      experience_refs: ['EXP-XAJ-0018'], experience_mode: 'exploitation',
      experience_influence: ['同流域同模型经验命中', 'routing 实验多次改善洪峰时序'],
      tool_status: 'succeeded', tool_status_zh: '已完成',
      tool_observations: ['optimizer=sce-ua', 'model_evaluations=48'], tool_metrics: { NSE: 0.781 },
      tool_calls: [{ action: 'A05_OPTIMIZE', tool_id: 'calibration.optimize', tool_name_zh: '参数优化工具', category: 'optimization', status: 'completed', input_summary: { optimizer: 'sce-ua' }, metrics: { model_evaluations: 48, NSE: 0.781 } }],
      evidence_summary: { evidence_id: 'ev-1', action: 'A05_OPTIMIZE', status: 'succeeded', observations: ['生成候选方案'], metrics: { NSE: 0.781 } },
    }, {
      round_number: 8,
      action: 'A05_OPTIMIZE', action_zh: '参数率定', tool_calls: [],
    }] })
    const wrapper = mount(AgentActivityPanel, { props: { taskId: 'task-1', eventCount: 1, currentAction: 'A05_OPTIMIZE', currentRoundNumber: 4, running: true } })
    await flushPromises()
    const panel = wrapper.get('[data-test="agent-activity-panel"]')
    const toggle = wrapper.get('[data-test="activity-toggle"]')
    expect(panel.classes()).not.toContain('is-expanded')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.findComponent(PhCaretUp).exists()).toBe(true)
    expect(toggle.findComponent(PhCaretDown).exists()).toBe(false)
    expect(wrapper.get('#agent-activity-content').attributes('aria-hidden')).toBe('true')

    await toggle.trigger('click')
    expect(panel.classes()).toContain('is-expanded')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.findComponent(PhCaretUp).exists()).toBe(false)
    expect(toggle.findComponent(PhCaretDown).exists()).toBe(true)
    expect(wrapper.get('#agent-activity-content').attributes('aria-hidden')).toBe('false')
    expect(wrapper.findAll('.activity-step')).toHaveLength(5)
    expect(wrapper.text()).toContain('洪峰持续偏低')
    expect(wrapper.text()).toContain('新安江率定诊断')
    expect(wrapper.text()).toContain('runoff / routing')
    expect(wrapper.text()).toContain('参数优化工具')
    expect(wrapper.text()).toContain('生成候选方案')
    expect(wrapper.text()).toContain('Experience Skill')
    expect(wrapper.text()).toContain('v4 · 经验利用')
    expect(wrapper.text()).toContain('EXP-XAJ-0018')
    await wrapper.get('[data-test="experience-ref-EXP-XAJ-0018"]').trigger('click')
    expect(wrapper.emitted('open-experience')?.[0]).toEqual(['EXP-XAJ-0018'])
    expect(wrapper.find('[data-test="experiment-stats"]').text()).toContain('48')

    await toggle.trigger('click')
    expect(panel.classes()).not.toContain('is-expanded')
  })

  it('does not reuse an earlier round when the current round has no tool evidence yet', async () => {
    mocks.getAgentLog.mockResolvedValueOnce({ task_id: 'task-1', rounds: [{
      round_number: 4,
      action: 'A05_OPTIMIZE', action_zh: '参数率定', tool_calls: [],
    }] })
    const wrapper = mount(AgentActivityPanel, { props: { taskId: 'task-1', eventCount: 4, currentAction: 'A05_OPTIMIZE', currentRoundNumber: 8 } })
    await flushPromises()
    expect(wrapper.text()).toContain('等待 Agent 开始行动')
    expect(wrapper.text()).not.toContain('48 次模型计算')
    expect(wrapper.text()).not.toContain('参数优化工具')
  })
})
