import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ObservatoryView from '../views/ObservatoryView.vue'
import { useDemoStore } from '../stores/demo'
import { api } from '../api/client'
vi.mock('../components/ForecastChart.vue', () => ({ default: { template: '<div data-test="chart" />' } }))
vi.mock('../components/HydrographComparisonChart.vue', () => ({ default: { template: '<div data-test="hydrograph" />' } }))
vi.mock('../api/client', () => ({ api: { health: vi.fn(async () => ({ status: 'ok', mode: 'demo' })), listTasks: vi.fn(async () => []), createTask: vi.fn(async () => ({task_id:'test-task'})), startRun: vi.fn(async () => ({ status:'running',worker_active:true })), getRun: vi.fn(async () => ({ status:'running',worker_active:true })), getTimeline: vi.fn(async () => []), getTask: vi.fn(async () => ({ basin_id:'basin-restored',start_date:'2021-01-01',end_date:'2021-01-03',forcing_mode:'R' })) } }))
async function setup(path='/') {
  const router = createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:ObservatoryView}]})
  await router.push(path)
  const wrapper = mount(ObservatoryView,{global:{plugins:[router]}})
  await flushPromises()
  return {wrapper,router,store:useDemoStore()}
}
beforeEach(()=>{sessionStorage.clear();setActivePinia(createPinia());vi.clearAllMocks()})
describe('single page observatory',()=>{
 it('starts only on submit and stays on the same page',async()=>{
  const {wrapper,router}=await setup()
  expect(api.startRun).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('模拟演示')
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(api.createTask).toHaveBeenCalledTimes(1)
  expect(api.startRun).toHaveBeenCalledTimes(1)
  expect(router.currentRoute.value.path).toBe('/')
  expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(true)
  expect(wrapper.find('.water-scene').exists()).toBe(false)
  expect(wrapper.find('fieldset').attributes('disabled')).toBeDefined()
  wrapper.unmount()
 })
 it('places data preparation left of the task pane and leaves the journal unnumbered',async()=>{
  const {wrapper}=await setup()
  const children=[...wrapper.find('.observatory-grid').element.children]
  expect(children[0].className).toContain('main-stage')
  expect(children[1].className).toContain('task-pane')
  expect(children[2].className).toContain('journal-pane')
  expect(wrapper.find('.task-pane .overline').text()).toBe('02 / 流域与任务')
  expect(wrapper.find('.journal-pane .overline').text()).toBe('执行记录')
  expect(wrapper.find('.record-count').exists()).toBe(false)
  expect(wrapper.find('.water-scene').exists()).toBe(false)
  expect(wrapper.find('.stage-track').exists()).toBe(false)
  expect(wrapper.find('.hero-copy').exists()).toBe(false)
  wrapper.unmount()
 })
 it('renders arriving results in place and exposes report links',async()=>{
  const {wrapper,store,router}=await setup()
  store.taskId='test-task'
  store.run={status:'completed',worker_active:false,phase:'E',needs_follow_up:false} as typeof store.run
  store.results={
    task_id:'test-task',
    phase:'E',
    scheme:{
      scheme_id:'s',
      status:'frozen',
      content_hash:'h',
      model_id:'xaj',
      provenance:{},
      parameters:{K:0.5,SM:30},
      base_parameters:{K:0.75,SM:20},
      parameter_delta:{K:-0.25,SM:10},
    },
    forecasts:[{forecast_id:'f',scheme_id:'s',issue_time:'2020-01-01',lead_values:{1:10},unit:'m3/s'}],
    metrics:{},
    gate:{status:'KEEP',reason_codes:['insufficient_absolute_skill'],metrics:{base_primary:-300,candidate_primary:-220}},
    diagnosis:{hypothesis:'MODEL',phenomenon:'洪峰低估',hypotheses_json:JSON.stringify([{id:'MODEL',strength:0.8,phenomenon:'洪峰低估'}])},
    optimize:{strategy_id:'xaj-peak-bias-v1',param_groups:'runoff,routing',objective:'composite',metrics:{objective_value:0.12}},
    report_artifacts:['report.md'],
    costs:{},
  }
  await flushPromises()
  expect(wrapper.find('[data-test="chart"]').exists()).toBe(true)
  expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(false)
  expect(wrapper.find('[data-test="forecast-surface"]').exists()).toBe(true)
  expect(wrapper.find('.observatory').classes()).toContain('is-results')
  expect(wrapper.find('[data-test="header-new-task"]').text()).toBe('新建任务')
  expect(wrapper.find('[data-test="header-case-picker"]').exists()).toBe(true)
  expect(wrapper.find('[data-test="param-tuning"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('新安江参数如何被调整')
  expect(wrapper.text()).toContain('保留原方案')
  expect(wrapper.find('a[href*="/report/"]').attributes('href')).toBe('/api/tasks/test-task/report/report.md')
  expect(router.currentRoute.value.path).toBe('/')
  wrapper.unmount()
 })
 it('shows the results surface even before forecast series arrive',async()=>{
  const {wrapper,store}=await setup()
  store.taskId='test-task'
  store.run={status:'completed',worker_active:false,phase:'E',needs_follow_up:false} as typeof store.run
  store.results={task_id:'test-task',phase:'E',scheme:null,forecasts:[],metrics:{},gate:{status:'KEEP'},report_artifacts:[],costs:{}}
  await flushPromises()
  expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(false)
  expect(wrapper.find('[data-test="forecast-surface"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('正在整理过程线与预报记录')
  expect(wrapper.find('.observatory').classes()).toContain('is-results')
  expect(wrapper.find('[data-test="header-new-task"]').exists()).toBe(true)
  wrapper.unmount()
 })
 it('restores existing sessions without restarting compute',async()=>{
  sessionStorage.setItem('hydro-demo-session',JSON.stringify({taskId:'existing',mode:'live',draft:{basin_id:'old',model_id:'xaj',start_date:'2020-01-01',end_date:'2020-01-03',forcing_mode:'R',base_scheme_id:'base',allow_optimization:true,max_agent_decision_rounds:20,max_optimization_cycles:4},startedAt:null}))
  const {wrapper,store}=await setup()
  expect(api.getTask).toHaveBeenCalledWith('existing')
  expect(store.draft.basin_id).toBe('basin-restored')
  expect(api.startRun).not.toHaveBeenCalled()
  wrapper.unmount()
 })
})
