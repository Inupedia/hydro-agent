import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ObservatoryView from '../views/ObservatoryView.vue'
import { useDemoStore } from '../stores/demo'
import { api } from '../api/client'

vi.mock('../components/HydrographComparisonChart.vue', () => ({ default: { template: '<div data-test="hydrograph" />' } }))
vi.mock('../components/ResearchEvidencePanel.vue', () => ({ default: { props: ['taskId'], template: '<div data-test="research-evidence-panel">research</div>' } }))
vi.mock('../api/client', () => ({
  api: {
    health: vi.fn(async () => ({ status: 'ok', mode: 'demo', basin_catalog: true })),
    listBasins: vi.fn(async () => [
      { basin_id: 'yaogu', label: '腰古', ready_for_build: true },
      { basin_id: 'usgs_02472000', label: 'Leaf River near Collins (MS)', ready_for_build: true },
    ]),
    listTasks: vi.fn(async () => []),
    createTask: vi.fn(async () => ({ task_id: 'test-task' })),
    deleteTask: vi.fn(async () => undefined),
    startRun: vi.fn(async () => ({ status: 'running', worker_active: true })),
    getRun: vi.fn(async () => ({ status: 'running', worker_active: true })),
    getTimeline: vi.fn(async () => []),
    getAgentLog: vi.fn(async () => ({ task_id: 'test-task', rounds: [] })),
    getTask: vi.fn(async () => ({ basin_id: 'basin-restored', start_date: '2021-01-01', end_date: '2021-01-03', forcing_mode: 'R' })),
  },
}))

async function setup(path = '/') {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: ObservatoryView }] })
  await router.push(path)
  const wrapper = mount(ObservatoryView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router, store: useDemoStore() }
}

beforeEach(() => {
  sessionStorage.clear()
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('single page observatory', () => {
  it('starts only on submit and stays on the same page', async () => {
    const { wrapper, router } = await setup()
    expect(api.startRun).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('模拟演示')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(api.createTask).toHaveBeenCalledTimes(1)
    expect(api.startRun).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.path).toBe('/')
    expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(true)
    expect(wrapper.find('.water-scene').exists()).toBe(false)
    expect(wrapper.find('fieldset').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('places data preparation left of the task pane and leaves workflow sections unnumbered', async () => {
    const { wrapper } = await setup()
    const children = [...wrapper.find('.observatory-grid').element.children]
    expect(children[0].className).toContain('main-stage')
    expect(children[1].className).toContain('task-pane')
    expect(children[2].className).toContain('journal-pane')
    expect(wrapper.find('.task-pane .overline').text()).toBe('流域与任务')
    expect(wrapper.find('.journal-pane .overline').text()).toBe('执行记录')
    expect(wrapper.find('.record-count').exists()).toBe(false)
    expect(wrapper.find('.water-scene').exists()).toBe(false)
    expect(wrapper.find('.stage-track').exists()).toBe(false)
    expect(wrapper.find('.hero-copy').exists()).toBe(false)
    wrapper.unmount()
  })

  it('lists Leaf River and keeps the selected basin', async () => {
    const { wrapper, store } = await setup()
    const selector = wrapper.find('[data-test="basin-selector"]')
    expect(selector.text()).toContain('Leaf River near Collins')
    await selector.setValue('usgs_02472000')
    expect(store.draft.basin_id).toBe('usgs_02472000')
    expect(wrapper.text()).toContain('使用 Leaf River near Collins (MS) 本地日资料')
    wrapper.unmount()
  })

  it('submits development and final-test windows with backend budget limits', async () => {
    const { wrapper } = await setup()
    await wrapper.find('.text-button').trigger('click')
    const development = wrapper.find('[data-test="development-days"]')
    const finalTest = wrapper.find('[data-test="final-test-days"]')
    expect(development.exists()).toBe(true)
    expect(finalTest.exists()).toBe(true)
    expect(development.attributes('min')).toBe('3')
    expect(development.attributes('max')).toBe('90')
    expect(finalTest.attributes('min')).toBe('3')
    expect(finalTest.attributes('max')).toBe('90')
    expect(wrapper.find('input[v-model="demo.draft.max_agent_decision_rounds"]').exists()).toBe(false)
    await development.setValue(21)
    await finalTest.setValue(14)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(api.createTask).toHaveBeenCalledWith(
      expect.objectContaining({ validation_days: 21, final_test_days: 14, max_agent_decision_rounds: 20, max_optimization_cycles: 4 }),
    )
    wrapper.unmount()
  })

  it('shows one final comparison chart, research audit, and removes the redundant forecast-record chart', async () => {
    const { wrapper, store, router } = await setup()
    store.taskId = 'test-task'
    store.run = { status: 'completed', worker_active: false, phase: 'E', needs_follow_up: false } as typeof store.run
    store.results = {
      task_id: 'test-task',
      phase: 'E',
      scheme: {
        scheme_id: 's',
        status: 'frozen',
        content_hash: 'h',
        model_id: 'xaj',
        provenance: {},
        parameters: { K: 0.75, SM: 20 },
        base_parameters: { K: 0.75, SM: 20 },
        parameter_delta: {},
        adopted_parameter_delta: {},
        candidate_scheme_id: 'candidate-1',
        candidate_parameters: { K: 0.5, SM: 30 },
        candidate_parameter_delta: { K: -0.25, SM: 10 },
      },
      forecasts: [{ forecast_id: 'f', scheme_id: 's', issue_time: '2020-01-01', lead_values: { 1: 10 }, unit: 'm3/s' }],
      metrics: {},
      gate: { status: 'KEEP', reason_codes: ['insufficient_absolute_skill'], metrics: { base_primary: -300, candidate_primary: -220 } },
      diagnosis: { hypothesis: 'MODEL', phenomenon: '洪峰低估', hypotheses_json: JSON.stringify([{ id: 'MODEL', strength: 0.8, phenomenon: '洪峰低估' }]) },
      optimize: { strategy_id: 'xaj-peak-bias-v1', param_groups: 'runoff,routing', objective: 'composite', metrics: { objective_value: 0.12 } },
      test_hydrograph: {
        kind: 'independent_test',
        title: '独立检验',
        calibrated: false,
        gate_status: 'KEEP',
        warmup_days: 0,
        evaluated_days: 2,
        series: [
          { time: '2020-01-01', observed_m3s: 10, baseline_m3s: 9, frozen_m3s: 9, window: 'test', is_warmup: false },
          { time: '2020-01-02', observed_m3s: 12, baseline_m3s: 11, frozen_m3s: 11, window: 'test', is_warmup: false },
        ],
        baseline_metrics: { nse: 0.4 },
        frozen_metrics: { nse: 0.4 },
      },
      report_artifacts: ['report.md'],
      costs: {},
    }
    await flushPromises()
    expect(wrapper.findAll('[data-test="hydrograph"]')).toHaveLength(1)
    expect(wrapper.find('[data-test="research-evidence-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('最终方案对比')
    expect(wrapper.text()).toContain('观测 / 基准 / 最终方案')
    expect(wrapper.text()).not.toContain('预报记录')
    expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="forecast-surface"]').exists()).toBe(true)
    expect(wrapper.find('.observatory').classes()).toContain('is-results')
    expect(wrapper.find('[data-test="header-new-task"]').text()).toBe('新建任务')
    expect(wrapper.find('[data-test="header-case-picker"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="header-delete-case"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="param-tuning"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('新安江参数如何被调整')
    expect(wrapper.text()).toContain('优化器提出的候选参数（变化 2 项，未必采用）')
    expect(wrapper.text()).toContain('最终采用参数（正式变化 0 项）')
    expect(wrapper.text()).toContain('并非优化器没有工作')
    expect(wrapper.find('a[href*="/report/"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('结果与报告')
    expect(router.currentRoute.value.path).toBe('/')
    wrapper.unmount()
  })

  it('supports selecting and deleting multiple historical cases in one operation', async () => {
    const { wrapper, store } = await setup()
    store.caseLibrary = [
      { task_id: 'case-1', basin_id: 'yaogu', model_id: 'xaj', phase: 'E', status: 'completed', paused: false, current_scheme_id: 's1', agent_rounds_used: 4, optimization_cycles_used: 1, start_date: '2020-01-01' },
      { task_id: 'case-2', basin_id: 'yaogu', model_id: 'xaj', phase: 'E', status: 'completed', paused: false, current_scheme_id: 's2', agent_rounds_used: 5, optimization_cycles_used: 2, start_date: '2020-02-01' },
    ]
    await flushPromises()

    await wrapper.find('[data-test="delete-case"]').trigger('click')
    expect(wrapper.find('.case-manager-panel').exists()).toBe(true)
    const checkboxes = wrapper.findAll('.case-manager-item input[type="checkbox"]')
    expect(checkboxes).toHaveLength(2)
    await checkboxes[0].setValue(true)
    await checkboxes[1].setValue(true)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    await wrapper.find('[data-test="delete-selected-cases"]').trigger('click')
    await flushPromises()
    expect(api.deleteTask).toHaveBeenCalledWith('case-1')
    expect(api.deleteTask).toHaveBeenCalledWith('case-2')
    expect(wrapper.find('.case-manager-panel').exists()).toBe(false)
    confirm.mockRestore()
    wrapper.unmount()
  })

  it('shows the results surface even before final comparison data arrive', async () => {
    const { wrapper, store } = await setup()
    store.taskId = 'test-task'
    store.run = { status: 'completed', worker_active: false, phase: 'E', needs_follow_up: false } as typeof store.run
    store.results = { task_id: 'test-task', phase: 'E', scheme: null, forecasts: [], metrics: {}, gate: { status: 'KEEP' }, report_artifacts: [], costs: {} }
    await flushPromises()
    expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="forecast-surface"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="research-evidence-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在整理最终方案对比')
    expect(wrapper.find('.observatory').classes()).toContain('is-results')
    expect(wrapper.find('[data-test="header-new-task"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('restores existing sessions without restarting compute', async () => {
    sessionStorage.setItem('hydro-demo-session', JSON.stringify({ taskId: 'existing', mode: 'live', draft: { basin_id: 'old', model_id: 'xaj', start_date: '2020-01-01', end_date: '2020-01-03', forcing_mode: 'R', base_scheme_id: 'base', allow_optimization: true, max_agent_decision_rounds: 20, max_optimization_cycles: 4 }, startedAt: null }))
    const { wrapper, store } = await setup()
    expect(api.getTask).toHaveBeenCalledWith('existing')
    expect(store.draft.basin_id).toBe('basin-restored')
    expect(store.draft.validation_days).toBe(30)
    expect(store.draft.final_test_days).toBe(30)
    expect(api.startRun).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
