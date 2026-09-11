import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ResultView from '../views/ResultView.vue'
import { useResultsStore } from '../stores/results'

const completedResultFixture = {
  task_id: 'task-1',
  phase: 'E' as const,
  scheme: {
    scheme_id: 'scheme-frozen-1',
    status: 'frozen',
    content_hash: 'abcdef1234567890',
    model_id: 'xaj',
    provenance: { source_scheme_id: 'scheme-base' },
  },
  forecasts: [
    {
      forecast_id: 'fc-1',
      scheme_id: 'scheme-frozen-1',
      issue_time: '2020-05-01T00:00:00Z',
      lead_values: { 1: 10, 2: 11, 3: 12 },
      unit: 'm3/s',
    },
  ],
  metrics: { NSE: 0.5, KGE: 0.4, MAE: 1.2, Bias: -0.1 },
  gate: { status: 'KEEP', reasons: ['insufficient_primary_delta'] },
  report_artifacts: ['report.json', 'report.md'],
  costs: {},
}

vi.mock('../components/HydrographComparisonChart.vue', () => ({
  default: {
    name: 'HydrographComparisonChart',
    template: '<div data-test="hydrograph-chart" />',
  },
}))

vi.mock('../components/ForecastChart.vue', () => ({
  default: {
    name: 'ForecastChart',
    template: '<div data-test="forecast-chart" />',
  },
}))

vi.mock('../api/client', () => ({
  api: {
    getResults: vi.fn(async () => completedResultFixture),
    getTimeline: vi.fn(async () => [
      {
        id: '1',
        occurred_at: '2020-05-01T00:00:00Z',
        label: '预报完成',
        status: 'succeeded',
        action: 'A05_FORECAST',
        evidence_id: 'ev-1',
        details: {},
      },
    ]),
  },
}))

describe('ResultView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows plain-language process story, metrics and lead series', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/tasks/:taskId/results', component: ResultView }],
    })
    await router.push('/tasks/task-1/results')
    await router.isReady()
    const store = useResultsStore()
    store.result = completedResultFixture
    const wrapper = mount(ResultView, {
      global: { plugins: [router] },
    })
    expect(wrapper.text()).toContain('系统决定：先不换方案')
    expect(wrapper.text()).toContain('整体吻合度')
    expect(wrapper.text()).toContain('NSE')
    expect(wrapper.find('[data-test="forecast-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="report-json"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('展开技术细节')
  })
})
