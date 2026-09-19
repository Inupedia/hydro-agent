import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentCalibrationPanel from '../components/AgentCalibrationPanel.vue'
import { api } from '../api/client'

vi.mock('../components/HydrographComparisonChart.vue', () => ({
  default: { props: ['comparison'], template: '<div data-test="agent-cal-hydrograph" />' },
}))
vi.mock('../api/client', () => ({
  api: { getResearch: vi.fn() },
}))

const comparison = {
  kind: 'calibration' as const,
  title: 'Calibration',
  calibrated: false,
  gate_status: 'ROLLBACK',
  warmup_days: 1,
  evaluated_days: 9,
  series: [
    { time: '1990-03-20', observed_m3s: 10, baseline_m3s: 4, candidate_m3s: 9, window: 'calibration', is_warmup: false },
  ],
  candidate_diagnosis: {
    window: 'calibration',
    overall: { status: 'available', sample_count: 20, metrics: { nse: 0.78 }, notes: [] },
    water_balance: { status: 'available', sample_count: 20, metrics: { volume_relative_error: 0.02 }, notes: [] },
    flow_regimes: {},
    fdc: { status: 'available', sample_count: 20, metrics: {}, notes: [] },
    seasons: {},
    years: {},
    data_quality: {
      total_count: 20,
      valid_count: 20,
      dropped_count: 0,
      coverage: 1,
      dropped_by_reason: {},
    },
    basin_attributes: {},
    flood_events: [
      {
        event_id: 'event-001',
        start: '1990-03-20',
        end: '1990-03-24',
        basis: 'rainfall_runoff',
        status: 'available',
        sample_count: 5,
        notes: [],
        metrics: {
          peak_relative_error: -0.18,
          peak_timing_lag_steps: 1,
          volume_relative_error: 0.03,
          rising_limb_mae: 8.1,
          recession_mae: 4.2,
        },
      },
      {
        event_id: 'event-002',
        start: '1990-04-05',
        end: '1990-04-09',
        basis: 'rainfall_runoff',
        status: 'available',
        sample_count: 5,
        notes: [],
        metrics: {
          peak_relative_error: -0.11,
          peak_timing_lag_steps: 1,
          volume_relative_error: 0.01,
          rising_limb_mae: 6.3,
          recession_mae: 3.8,
        },
      },
    ],
  },
}

const summary = {
  task_id: 'task-1',
  protocol: {},
  latest_experiment_plan: {
    plan_id: 'plan-next',
    experiment_signature: 'sig-next',
    strategy_id: 'xaj-routing-refine-v1',
    optimizer: 'dds',
    objective: 'composite',
    param_groups: ['routing'],
    evaluation_budget: 128,
    model_evaluations: 0,
    reason_codes: [],
    evidence_refs: ['event-001', 'event-002'],
    active_parameters: [],
    sensitivity_method: null,
  },
  trials: [
    {
      trial_id: 'trial-1',
      plan_id: 'plan-1',
      experiment_signature: 'sig',
      strategy_id: 'xaj-water-balance-v1',
      model_evaluations: 384,
      development_gate: 'ROLLBACK',
      adoption_status: 'REJECT',
      qualification_status: 'UNQUALIFIED',
      metric_deltas: { primary_delta: -2.55 },
      parameter_delta: { K: -0.25, SM: 10, UM: 0 },
      baseline_nse: -6.315,
      candidate_nse: 0.782,
      base_primary: -1.317,
      candidate_primary: -3.87,
      gate_reasons: ['lead_1_guardrail', 'insufficient_absolute_skill'],
      evidence_refs: [],
      hypothesis_outcome: 'refuted',
      reason_codes: ['development_gate_recorded'],
    },
  ],
  final_test_evidence: null,
  final_test_audit: { consumed: true, read_only: true, single_use: true },
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

describe('AgentCalibrationPanel', () => {
  it('shows the calibration hydrograph, each parameter delta, and rollback reasons', async () => {
    const wrapper = mount(AgentCalibrationPanel, {
      props: {
        taskId: 'task-1',
        comparison,
        diagnosis: {
          phenomenon: '多场次洪洪峰偏低且峰现偏晚，当前诊断聚焦汇流响应。',
          recommended_param_groups: ['routing'],
          recommended_strategy_id: 'xaj-routing-refine-v1',
        },
      },
    })
    await flushPromises()

    expect(api.getResearch).toHaveBeenCalledWith('task-1')
    expect(wrapper.text()).toContain('智能体调参')
    expect(wrapper.text()).toContain('率定窗里，观测与候选差在哪里')
    expect(wrapper.find('[data-test="agent-cal-hydrograph"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('xaj-water-balance-v1')
    expect(wrapper.text()).toContain('回退')
    expect(wrapper.text()).toContain('-6.315 → 0.782')
    expect(wrapper.text()).toContain('第 1 日预见期 NSE 下降超过允许值')
    expect(wrapper.text()).toContain('lead_1_guardrail')
    expect(wrapper.text()).toContain('候选方案绝对技巧未达标')
    expect(wrapper.text()).toContain('K')
    expect(wrapper.text()).toContain('-0.250')
    expect(wrapper.text()).toContain('SM')
    expect(wrapper.text()).not.toContain('UM')
    expect(wrapper.text()).toContain('Agent 观察')
    expect(wrapper.text()).toContain('洪量基本正确')
    expect(wrapper.text()).toContain('洪峰偏低')
    expect(wrapper.text()).toContain('峰现偏晚')
    expect(wrapper.text()).toContain('多场洪水出现同类问题')
    expect(wrapper.text()).toContain('水文诊断')
    expect(wrapper.text()).toContain('多场次洪洪峰偏低且峰现偏晚')
    expect(wrapper.text()).toContain('下一步实验')
    expect(wrapper.text()).toContain('xaj-routing-refine-v1')
    expect(wrapper.text()).toContain('event-001')
    expect(wrapper.text()).toContain('event-002')
    expect(wrapper.find('[data-test="flood-event-matrix"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('AI 综合评分')
  })

  it('stays hidden when there is no search process to report', async () => {
    vi.mocked(api.getResearch).mockResolvedValueOnce({ ...summary, trials: [] } as never)
    const wrapper = mount(AgentCalibrationPanel, { props: { taskId: 'task-1', comparison: null } })
    await flushPromises()
    expect(wrapper.find('[data-test="agent-calibration-panel"]').exists()).toBe(false)
  })
})
