import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ExecutionJournal from '../components/ExecutionJournal.vue'

const defaultAgentLog = () => ({
  task_id: 'task-1',
  rounds: [
    {
      round_number: 3,
      occurred_at: '2026-09-13T06:00:02Z',
      action: 'A04_DIAGNOSE',
      action_zh: '结果诊断',
      hypothesis: 'MODEL',
      hypothesis_zh: '模型参数问题',
      strategy_id: null,
      rationale_summary: '根据当前误差决定继续诊断。',
      llm_output: JSON.stringify({
        action: 'A04_DIAGNOSE',
        hypothesis: 'MODEL',
        observation_zh: '当前洪峰持续偏低，过程线与观测仍有明显差距。',
        analysis_zh: '误差更像来自模型参数，而不是资料缺失。应先确认产流和汇流参数是否需要调整。',
        decision_zh: '继续做结果诊断，明确下一轮需要调整的参数范围。',
        rationale_summary: '洪峰低估，需继续诊断。',
      }),
      input_summary_zh: "第 3 轮 · 阶段 B · 证据 ['A03_FORECAST']",
      judgment_zh: "发现：阶段B，证据['A03_FORECAST']；依据：{'metrics': {'nse': 0.42}}；决策：A04_DIAGNOSE/MODEL",
      input_world_state: {},
      tool_status: 'succeeded',
      tool_status_zh: '已完成',
      tool_observations: ['洪峰低估', '退水段偏慢'],
      tool_metrics: { NSE: 0.42 },
      error: null,
    },
  ],
})

const mocks = vi.hoisted(() => ({ getAgentLog: vi.fn() }))
vi.mock('../api/client', () => ({ api: { getAgentLog: mocks.getAgentLog } }))

describe('ExecutionJournal', () => {
  beforeEach(() => {
    mocks.getAgentLog.mockReset()
    mocks.getAgentLog.mockResolvedValue(defaultAgentLog())
  })

  it('renders the LLM audit summary directly without exposing machine-style trace text', async () => {
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
            action: 'A04_DIAGNOSE',
            evidence_id: 'ev-2',
            details: { raw_metric: 0.42 },
          },
          {
            id: 'earlier',
            occurred_at: '2026-09-13T06:00:01Z',
            label: '完成基础预报',
            status: 'succeeded',
            action: 'A03_FORECAST',
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
    expect(cards[1].find('.event-subtitle').text()).toBe('误差更像来自模型参数，而不是资料缺失。应先确认产流和汇流参数是否需要调整。')
    expect(cards[1].text()).toContain('当前洪峰持续偏低')
    expect(cards[1].text()).toContain('继续做结果诊断')
    expect(cards[1].text()).toContain('洪峰低估；退水段偏慢')
    expect(cards[1].text()).not.toContain('阶段B')
    expect(cards[1].text()).not.toContain('A04_DIAGNOSE')
    expect(cards[1].text()).not.toContain("{'metrics'")
    expect(cards[1].find('.technical-details pre').text()).toContain('raw_metric')
    expect(wrapper.find('.event-index').exists()).toBe(false)
    expect(mocks.getAgentLog).toHaveBeenCalledWith('task-1')
  })

  it('uses the actual executed action when a deterministic guardrail overrides the raw LLM proposal', async () => {
    mocks.getAgentLog.mockResolvedValueOnce({
      task_id: 'task-guardrail',
      rounds: [
        {
          ...defaultAgentLog().rounds[0],
          action: 'A06_GATE',
          action_zh: '质量把关',
          rationale_summary: '最新候选需要先完成独立质量检查。',
          llm_output: JSON.stringify({
            action: 'A05_OPTIMIZE',
            observation_zh: '候选方案已经生成。',
            analysis_zh: '当前最重要的是确认这次调整是否真的改善了结果。',
            decision_zh: '继续调整参数。',
          }),
        },
      ],
    })

    const wrapper = mount(ExecutionJournal, {
      props: {
        taskId: 'task-guardrail',
        running: false,
        completed: false,
        failed: false,
        elapsed: '0:12',
        events: [
          {
            id: 'gate',
            occurred_at: '2026-09-13T06:00:02Z',
            label: '质量把关',
            status: 'succeeded',
            action: 'A06_GATE',
            evidence_id: 'ev-gate',
            details: {},
          },
        ],
      },
    })

    await flushPromises()
    expect(wrapper.text()).toContain('当前最重要的是确认这次调整是否真的改善了结果')
    expect(wrapper.text()).toContain('质量把关：最新候选需要先完成独立质量检查')
    expect(wrapper.text()).not.toContain('继续调整参数')
  })

  it('falls back to workflow wording when an old record has no structured LLM audit fields', async () => {
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
            action: 'A03_FORECAST',
            evidence_id: null,
            details: {},
          },
        ],
      },
    })

    await flushPromises()
    expect(wrapper.find('.event-subtitle').text()).toContain('用当前方案计算未来几天的流量')
    expect(wrapper.text()).toContain('工具正在执行')
  })

  it('automatically keeps the newest record in view', async () => {
    mocks.getAgentLog.mockResolvedValue({ task_id: 'task-scroll', rounds: [] })
    const wrapper = mount(ExecutionJournal, {
      props: {
        taskId: 'task-scroll',
        running: true,
        completed: false,
        failed: false,
        elapsed: '0:02',
        events: [
          {
            id: 'one',
            occurred_at: '2026-09-13T06:00:01Z',
            label: '第一步',
            status: 'succeeded',
            action: 'A01_CHECK_DATA',
            evidence_id: null,
            details: {},
          },
        ],
      },
    })
    await flushPromises()

    const list = wrapper.find('[data-test="journal-list"]').element as HTMLElement
    Object.defineProperty(list, 'scrollHeight', { configurable: true, value: 900 })
    list.scrollTop = 0

    await wrapper.setProps({
      events: [
        ...wrapper.props('events'),
        {
          id: 'two',
          occurred_at: '2026-09-13T06:00:02Z',
          label: '第二步',
          status: 'running',
          action: 'A02_VALIDATE_SCHEME',
          evidence_id: null,
          details: {},
        },
      ],
    })
    await flushPromises()

    expect(list.scrollTop).toBe(900)
    expect(wrapper.findAll('.journal-event-card').at(-1)?.classes()).toContain('is-latest')
  })

  it('keeps tool and skill details collapsed until the user opens them', async () => {
    mocks.getAgentLog.mockResolvedValueOnce({
      task_id: 'task-skills',
      rounds: [
        {
          round_number: 1,
          occurred_at: '2026-09-13T06:00:01Z',
          action: 'A04_DIAGNOSE',
          action_zh: '结果诊断',
          hypothesis: 'MODEL',
          hypothesis_zh: '模型参数问题',
          strategy_id: null,
          rationale_summary: '继续诊断。',
          llm_output: '',
          input_summary_zh: '',
          judgment_zh: '',
          input_world_state: {},
          tool_status: 'succeeded',
          tool_status_zh: '已完成',
          tool_observations: [],
          tool_metrics: {},
          activated_skill_ids: ['hydrologic-evidence-review', 'xaj-calibration-diagnosis'],
          activated_skills_audit: [
            {
              skill_id: 'hydrologic-evidence-review',
              source: 'builtin',
              skill_sha256: 'a',
              loaded_references: [],
              output_contract: 'EvidenceInterpretation',
            },
            {
              skill_id: 'xaj-calibration-diagnosis',
              source: 'builtin',
              skill_sha256: 'b',
              loaded_references: [],
              output_contract: 'CalibrationPlan',
            },
          ],
          error: null,
        },
      ],
    })

    const wrapper = mount(ExecutionJournal, {
      props: {
        taskId: 'task-skills',
        running: false,
        completed: true,
        failed: false,
        elapsed: '已结束',
        events: [
          {
            id: 'diag',
            occurred_at: '2026-09-13T06:00:01Z',
            label: '完成诊断',
            status: 'succeeded',
            action: 'A04_DIAGNOSE',
            evidence_id: 'ev-1',
            details: {},
          },
        ],
      },
    })
    await flushPromises()

    const skills = wrapper.find('[data-test="activated-skills"]')
    const tools = wrapper.find('[data-test="tool-calls"]')
    expect(skills.exists()).toBe(true)
    expect(tools.exists()).toBe(true)
    expect(skills.attributes('open')).toBeUndefined()
    expect(tools.attributes('open')).toBeUndefined()
    expect(skills.text()).toContain('专业能力')
    expect(skills.text()).toContain('SKILL')
    expect(tools.text()).toContain('执行工具')
    expect(tools.text()).toContain('模型诊断工具')
    expect(skills.text()).toContain('水文证据审查')
    expect(skills.text()).toContain('新安江率定诊断')
    expect(skills.text()).toContain('证据解读')
    expect(skills.text()).toContain('实验计划')
    expect(skills.findAll('.skill-chip-list li')).toHaveLength(2)

    await tools.find('summary').trigger('click')
    await skills.find('summary').trigger('click')
    expect((tools.element as HTMLDetailsElement).open).toBe(true)
    expect((skills.element as HTMLDetailsElement).open).toBe(true)
  })

  it('renders explicit tool calls while preserving their status and summaries', async () => {
    mocks.getAgentLog.mockResolvedValueOnce({
      task_id: 'task-tools',
      rounds: [{
        ...defaultAgentLog().rounds[0],
        tool_calls: [{
          action: 'A04_DIAGNOSE',
          tool_id: 'hydrology.diagnose',
          tool_name: 'Diagnose',
          tool_name_zh: '模型诊断工具',
          category: 'diagnosis',
          status: 'failed',
          input_summary: { scheme: 'candidate-03' },
          output_summary: { reason: '指标不足' },
        }],
      }],
    })
    const wrapper = mount(ExecutionJournal, { props: {
      taskId: 'task-tools', running: false, completed: false, failed: true, elapsed: '0:08',
      events: [{ id: 'diag', occurred_at: '2026-09-13T06:00:02Z', label: '诊断失败', status: 'failed', action: 'A04_DIAGNOSE', evidence_id: null, details: {} }],
    } })
    await flushPromises()
    const tools = wrapper.find('[data-test="tool-calls"]')
    expect(tools.text()).toContain('模型诊断工具')
    expect(tools.text()).toContain('失败')
    expect(tools.text()).toContain('scheme: candidate-03')
    expect(tools.text()).toContain('reason: 指标不足')
  })
})
