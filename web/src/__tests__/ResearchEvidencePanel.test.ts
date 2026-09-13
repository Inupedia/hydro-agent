import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ResearchEvidencePanel from '../components/ResearchEvidencePanel.vue'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    getResearch: vi.fn(),
  },
}))

const summary = {
  task_id: 'task-1',
  protocol: {
    protocol_mode: 'research',
    calibration_start_date: '1990-01-01',
    calibration_end_date: '1990-12-31',
    development_start_date: '1991-01-01',
    development_end_date: '1991-01-30',
    final_test_start_date: '1991-01-31',
    final_test_end_date: '1991-03-01',
  },
  latest_experiment_plan: {
    plan_id: 'plan-1234567890abcdef',
    experiment_signature: 'sig-123',
    strategy_id: 'xaj-water-balance-v1',
    optimizer: 'dds',
    objective: 'kge',
    param_groups: ['evap', 'runoff'],
    evaluation_budget: 384,
    model_evaluations: 384,
    reason_codes: ['diagnosis_recommendation'],
    evidence_refs: ['ev-06'],
    active_parameters: ['K', 'B', 'SM'],
    sensitivity_method: 'morris',
  },
  trials: [
    {
      trial_id: 'trial-1',
      plan_id: 'plan-1234567890abcdef',
      experiment_signature: 'sig-123',
      strategy_id: 'xaj-water-balance-v1',
      model_evaluations: 384,
      development_gate: 'ROLLBACK',
      adoption_status: 'REJECT',
      qualification_status: 'UNQUALIFIED',
      metric_deltas: { primary_delta: -0.12 },
      evidence_refs: ['ev-06', 'ev-07', 'ev-08', 'ev-09'],
      hypothesis_outcome: 'refuted',
      reason_codes: ['development_gate_recorded'],
    },
  ],
  final_test_evidence: {
    window: 'final_test',
    quality: { total_count: 3, valid_count: 3, dropped_count: 0, coverage: 1, dropped_by_reason: {} },
    overall: {
      name: 'overall',
      status: 'available',
      sample_count: 3,
      start: '1991-01-31',
      end: '1991-02-02',
      metrics: { nse: -0.35, kge: -0.002, rmse: 54.7, pbias_percent: 64.1 },
      notes: [],
    },
    flow_regimes: {},
    seasons: {},
    years: {
      '1991': { name: '1991', status: 'insufficient_data', sample_count: 3, metrics: {}, notes: ['requires_at_least=30'] },
    },
    fdc: { name: 'fdc', status: 'insufficient_data', sample_count: 3, metrics: {}, notes: ['requires_at_least=20'] },
    flood_events: [],
  },
  final_test_audit: {
    consumed: true,
    read_only: true,
    single_use: true,
    window: '1991-01-31..1991-03-01',
  },
  contracts: {
    rolling_continuous_separated: true,
    final_test_used_for_selection: false,
    trial_ledger_source: 'persisted_evidence',
    objective_alias: 'composite->kge',
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getResearch).mockResolvedValue(summary as never)
})

describe('ResearchEvidencePanel', () => {
  it('renders the four-stage audit boundary, experiment plan and trial ledger', async () => {
    const wrapper = mount(ResearchEvidencePanel, { props: { taskId: 'task-1' } })
    await flushPromises()

    expect(api.getResearch).toHaveBeenCalledWith('task-1')
    expect(wrapper.text()).toContain('研究证据')
    expect(wrapper.text()).toContain('率定 Calibration')
    expect(wrapper.text()).toContain('开发验证 Development')
    expect(wrapper.text()).toContain('最终独立检验 Final Test')
    expect(wrapper.text()).toContain('只读 · 单次消费完成')
    expect(wrapper.text()).toContain('xaj-water-balance-v1')
    expect(wrapper.text()).toContain('KGE')
    expect(wrapper.text()).toContain('384')
    expect(wrapper.text()).toContain('假设被证伪')
    expect(wrapper.find('.ledger-scroll').attributes('tabindex')).toBe('0')
  })

  it('does not turn short final-test data into fake annual or FDC evidence', async () => {
    const wrapper = mount(ResearchEvidencePanel, { props: { taskId: 'task-1' } })
    await flushPromises()

    expect(wrapper.text()).toContain('年度稳定性')
    expect(wrapper.text()).toContain('FDC')
    expect(wrapper.text()).toContain('样本不足')
    expect(wrapper.text()).toContain('不会用短样本伪造稳定性证据')
    expect(wrapper.text()).toContain('Rolling forecast skill 与 continuous simulation skill 分开报告，不做混合平均')
  })

  it('keeps research fetch errors visible in the owning panel', async () => {
    vi.mocked(api.getResearch).mockRejectedValueOnce(new Error('research unavailable'))
    const wrapper = mount(ResearchEvidencePanel, { props: { taskId: 'task-1' } })
    await flushPromises()

    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('研究证据暂时无法读取')
    expect(wrapper.text()).toContain('research unavailable')
    expect(wrapper.find('.retry-button').exists()).toBe(true)
  })
})
