<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ExecutionJournal from '../components/ExecutionJournal.vue'
import HydrographComparisonChart from '../components/HydrographComparisonChart.vue'
import SchemeComparisonMetricsChart from '../components/SchemeComparisonMetricsChart.vue'
import LiveWorkflow from '../components/LiveWorkflow.vue'
import ModelPreparation from '../components/ModelPreparation.vue'
import type { ModelPlan } from '../types/api'
import HydrologistTune from '../components/HydrologistTune.vue'
import ParamTuningPanel from '../components/ParamTuningPanel.vue'
import ResearchEvidencePanel from '../components/ResearchEvidencePanel.vue'
import { useDemoStore } from '../stores/demo'
import { api } from '../api/client'
import { gsap, motionDuration, prefersReducedMotion } from '../motion/gsap'
import { basinLabel } from '../demo/stages'

const demo = useDemoStore()
const route = useRoute()
const busy = ref(false)
const serviceMode = ref<string | null>(null)
const connected = ref(false)
const modelingAvailable = ref(false)
const hydrologistAvailable = ref(false)
const basins = ref<import('../types/api').BasinInfo[]>([])
const basinOptions = computed(() =>
  basins.value.length
    ? basins.value
    : [{ basin_id: demo.draft.basin_id, label: basinLabel(demo.draft.basin_id), ready_for_build: true }],
)
const selectedBasin = computed(() =>
  basinOptions.value.find((basin) => basin.basin_id === demo.draft.basin_id),
)
const planReady = computed(() => !!demo.draft.model_plan_id)
let syncingPlanBasin = false
function selectPlan(plan: ModelPlan | null) {
  if (demo.taskId) return
  if (!plan) {
    demo.draft.model_plan_id = null
    return
  }
  const previous = demo.draft.model_plan_id
  syncingPlanBasin = true
  if (demo.draft.basin_id !== plan.basin_id) {
    demo.draft.basin_id = plan.basin_id
  }
  demo.draft.model_plan_id = plan.plan_id
  const datesNeedRepair = !!plan.suggested_start && demo.draft.start_date < plan.suggested_start
  if (previous !== plan.plan_id || datesNeedRepair) {
    demo.draft.forcing_mode = 'R'
    if (plan.suggested_start) demo.draft.start_date = plan.suggested_start
    if (plan.suggested_end) demo.draft.end_date = plan.suggested_end
  }
  void nextTick(() => {
    syncingPlanBasin = false
  })
}
const now = ref(Date.now())
const advanced = ref(false)
const taskPane = ref<HTMLElement | null>(null)
const mainStage = ref<HTMLElement | null>(null)
const journalPane = ref<HTMLElement | null>(null)
const forecastSurface = ref<HTMLElement | null>(null)
const tuningMount = ref<HTMLElement | null>(null)
const caseManagerOpen = ref(false)
const selectedCaseIds = ref<string[]>([])
let timer: number | undefined
let layoutTween: ReturnType<typeof gsap.timeline> | null = null

const locked = computed(() => busy.value || !!demo.taskId)
const action = computed(() => demo.run?.llm_decision_action || demo.run?.last_action || demo.timeline.at(-1)?.action)
const finalComparison = computed(() => {
  const test = demo.results?.test_hydrograph
  if (test?.series?.length) return test
  const calibration = demo.results?.calibration_hydrograph
  return calibration?.series?.length ? calibration : null
})
const hasHydrograph = computed(() => !!finalComparison.value)
const showResultsStage = computed(() => demo.isCompleted && !demo.isFailed && !!demo.results)
const showWorkflow = computed(
  () =>
    !showResultsStage.value &&
    (busy.value ||
      demo.isRunning ||
      !!demo.run?.paused ||
      demo.isFailed ||
      (!!demo.taskId && !!demo.run && demo.run.status !== 'created' && !demo.isCompleted)),
)
const focusStage = computed(() => showWorkflow.value && !demo.isCompleted)
const completedActions = computed(() =>
  demo.timeline
    .filter((t) => t.action && !['failed', 'error', 'skipped', 'running'].includes(t.status))
    .map((t) => t.action as string),
)
const gateStatus = computed(() => {
  const fromResults = demo.results?.gate?.status
  if (typeof fromResults === 'string') return fromResults
  const gate = [...demo.timeline].reverse().find((t) => t.action === 'A08_GATE' || t.action === 'A09_RESOLVE')
  return typeof gate?.status === 'string' ? gate.status : null
})
const showTuning = computed(
  () =>
    !focusStage.value &&
    !!demo.results &&
    (!!demo.results.diagnosis ||
      !!demo.results.optimize ||
      !!(demo.results.scheme?.parameter_delta && Object.keys(demo.results.scheme.parameter_delta).length) ||
      !!(demo.results.scheme?.parameters && Object.keys(demo.results.scheme.parameters).length)),
)
const showHydrologist = computed(
  () =>
    hydrologistAvailable.value &&
    !focusStage.value &&
    !!demo.taskId &&
    !!demo.draft.model_plan_id &&
    (showTuning.value ||
      demo.run?.paused ||
      demo.run?.status === 'idle' ||
      !!demo.results?.optimize ||
      completedActions.value.includes('A06_DIAGNOSE') ||
      completedActions.value.includes('A07_OPTIMIZE')),
)
const mode = computed(() =>
  demo.mode === 'replay' ? '历史记录' : serviceMode.value === 'real' ? '真实计算' : serviceMode.value ? '模拟演示' : '连接待确认',
)
const allCasesSelected = computed(
  () => demo.caseLibrary.length > 0 && demo.caseLibrary.every((task) => selectedCaseIds.value.includes(task.task_id)),
)
const elapsed = computed(() => {
  if (!demo.startedAt || demo.isCompleted || demo.isFailed) return demo.isCompleted ? '已结束' : '等待开始'
  const seconds = Math.max(0, Math.floor((now.value - demo.startedAt) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
})
const error = computed(() => demo.error || demo.run?.llm_error)

async function begin() {
  busy.value = true
  try {
    if (!demo.taskId) await demo.createTaskFromDraft()
    await demo.startRun()
  } catch (err) {
    demo.error = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}
async function resume() {
  busy.value = true
  try {
    await demo.resumeCompute()
  } catch (err) {
    demo.error = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}
async function openCase(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const task = demo.caseLibrary.find((t) => t.task_id === id)
  if (task) await demo.openCaseReplay(task)
}
function openCaseManager() {
  if (!demo.caseLibrary.length) return
  selectedCaseIds.value =
    demo.mode === 'replay' && demo.taskId && demo.caseLibrary.some((task) => task.task_id === demo.taskId)
      ? [demo.taskId]
      : []
  caseManagerOpen.value = true
}
function closeCaseManager() {
  caseManagerOpen.value = false
  selectedCaseIds.value = []
}
function toggleAllCases() {
  selectedCaseIds.value = allCasesSelected.value
    ? []
    : demo.caseLibrary.map((task) => task.task_id)
}
async function deleteSelectedCases() {
  const selected = demo.caseLibrary.filter((task) => selectedCaseIds.value.includes(task.task_id))
  if (!selected.length) return
  if (!window.confirm(`删除选中的 ${selected.length} 份历史案例？此操作不可恢复。`)) return
  const deletesCurrent = !!demo.taskId && selectedCaseIds.value.includes(demo.taskId)
  busy.value = true
  try {
    await demo.deleteCases(selected)
    closeCaseManager()
    if (deletesCurrent) history.replaceState(null, '', '/')
  } catch (err) {
    demo.error = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
}
function newTask() {
  demo.resetSession()
  history.replaceState(null, '', '/')
  void nextTick(() => {
    const task = taskPane.value
    if (task) gsap.set(task, { autoAlpha: 1, pointerEvents: 'auto', clearProps: 'transform,opacity,visibility' })
  })
}

function animateFocus(enter: boolean) {
  layoutTween?.kill()
  const reduced = prefersReducedMotion()
  const dur = motionDuration(0.55)
  const task = taskPane.value
  const main = mainStage.value
  if (!main) return

  layoutTween = gsap.timeline({ defaults: { ease: 'power3.out' } })
  if (enter) {
    if (task) {
      layoutTween.to(task, { autoAlpha: 0, duration: dur * 0.45, pointerEvents: 'none' }, 0)
    }
    layoutTween.fromTo(
      main,
      { scale: reduced ? 1 : 0.97, transformOrigin: '50% 40%' },
      { scale: 1, duration: dur, clearProps: 'transform' },
      0,
    )
    const workflow = main.querySelector('.live-workflow')
    if (workflow) {
      layoutTween.fromTo(
        workflow,
        { scale: reduced ? 1 : 0.9, autoAlpha: 0.4, y: 18 },
        { scale: 1, autoAlpha: 1, y: 0, duration: dur, ease: 'power3.out', clearProps: 'transform' },
        0.06,
      )
    }
  } else {
    if (task) {
      gsap.set(task, { pointerEvents: 'auto' })
      layoutTween.to(task, { autoAlpha: 1, duration: dur }, 0)
    }
    layoutTween.fromTo(main, { scale: reduced ? 1 : 1.02 }, { scale: 1, duration: dur, clearProps: 'transform' }, 0)
  }
}

function animateResultsSurfaces() {
  const chart = forecastSurface.value
  const tuning = tuningMount.value
  const dur = motionDuration(0.6)
  if (chart) {
    gsap.fromTo(
      chart,
      { autoAlpha: prefersReducedMotion() ? 1 : 0.2, y: prefersReducedMotion() ? 0 : 16 },
      {
        autoAlpha: 1,
        y: 0,
        duration: dur,
        ease: 'power3.out',
        clearProps: 'transform,opacity,visibility',
        onInterrupt: () => gsap.set(chart, { clearProps: 'transform,opacity,visibility' }),
      },
    )
  }
  if (tuning) {
    gsap.fromTo(
      tuning,
      { autoAlpha: prefersReducedMotion() ? 1 : 0.2, y: prefersReducedMotion() ? 0 : 20 },
      {
        autoAlpha: 1,
        y: 0,
        duration: dur,
        delay: 0.08,
        ease: 'power3.out',
        clearProps: 'transform,opacity,visibility',
      },
    )
  }
}

watch(focusStage, async (enter, was) => {
  await nextTick()
  if (was === undefined && !enter) return
  if (!enter && showResultsStage.value) {
    layoutTween?.kill()
    const task = taskPane.value
    if (task) gsap.set(task, { autoAlpha: 0, pointerEvents: 'none' })
    animateResultsSurfaces()
    return
  }
  animateFocus(enter)
})

watch(
  () => demo.draft.basin_id,
  (id, prev) => {
    if (syncingPlanBasin) return
    if (prev && id !== prev && !demo.taskId) {
      demo.draft.model_plan_id = null
    }
  },
)

watch(
  () => [showWorkflow.value, showResultsStage.value, hasHydrograph.value, showTuning.value] as const,
  async ([workflow, resultsStage, hydrograph, tuning]) => {
    if (workflow) return
    await nextTick()
    if (resultsStage || hydrograph || tuning) animateResultsSurfaces()
  },
)

onMounted(async () => {
  timer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
  void demo.loadCaseLibrary()
  try {
    const health = await api.health()
    connected.value = health.status === 'ok'
    modelingAvailable.value = !!health.model_preparation
    hydrologistAvailable.value = !!health.hydrologist_tune
    serviceMode.value = health.mode || null
    if (health.basin_catalog) {
      try {
        basins.value = await api.listBasins()
      } catch {
        basins.value = []
      }
    }
    if (!demo.taskId && !basins.value.some((basin) => basin.basin_id === demo.draft.basin_id && basin.ready_for_build)) {
      demo.draft.basin_id = basins.value.find((basin) => basin.ready_for_build)?.basin_id || 'yaogu'
    }
  } catch {
    connected.value = false
  }
  const id = String(route.params.taskId || demo.taskId || '')
  if (id) {
    try {
      const task = await api.getTask(id)
      demo.draft.basin_id = task.basin_id
      demo.draft.model_plan_id = task.model_plan_id ?? null
      if (task.start_date) demo.draft.start_date = task.start_date
      if (task.end_date) demo.draft.end_date = task.end_date
      if (task.forcing_mode) demo.draft.forcing_mode = task.forcing_mode
      demo.draft.model_id = task.model_id === 'openhydronet' ? 'openhydronet' : 'xaj'
      demo.restoreTask(id)
    } catch (err) {
      demo.error = String((err as Error).message || err)
    }
  }
  await nextTick()
  if (focusStage.value) animateFocus(true)
  else if (showResultsStage.value || hasHydrograph.value || showTuning.value) animateResultsSurfaces()
})
onUnmounted(() => {
  clearInterval(timer)
  demo.stopPolling()
  layoutTween?.kill()
})
</script>

<template>
  <div class="observatory" :class="{ 'is-focus': focusStage, 'is-results': showResultsStage }">
    <header class="observatory-header">
      <a href="/" class="observatory-brand"><span class="brand-symbol" aria-hidden="true">≈</span><span>Hydro<span class="brand-light">Agent</span><small>水文智能体 · 课题工作台</small></span></a>
      <div class="header-caption">{{ focusStage ? '执行中' : demo.mode === 'replay' ? '案例回放' : showResultsStage ? '运行结果' : '工作台' }}</div>
      <div class="header-end">
        <div v-if="showResultsStage" class="header-actions">
          <label class="header-case-picker">已有案例
            <select data-test="header-case-picker" aria-label="已有案例" :disabled="demo.isRunning || busy" :value="demo.mode === 'replay' ? demo.taskId : ''" @change="openCase">
              <option value="">{{ demo.caseLibrary.length ? '选择一份已完成记录' : '暂无已完成记录' }}</option>
              <option v-for="task in demo.caseLibrary" :key="task.task_id" :value="task.task_id">{{ task.start_date || task.task_id }} · {{ basinLabel(task.basin_id) }}</option>
            </select>
          </label>
          <button data-test="header-delete-case" type="button" class="case-delete" :disabled="demo.isRunning || busy || !demo.caseLibrary.length" @click="openCaseManager">管理</button>
          <button data-test="header-new-task" type="button" class="header-new-task" @click="newTask">新建任务</button>
        </div>
        <div class="connection"><i :class="{ online: connected }" />{{ mode }}</div>
      </div>
    </header>

    <div v-if="caseManagerOpen" class="case-manager-backdrop" @click.self="closeCaseManager">
      <section class="case-manager-panel glass-pane" role="dialog" aria-modal="true" aria-label="批量管理历史案例">
        <header class="case-manager-head">
          <div><span class="overline">历史案例</span><h2>批量管理</h2></div>
          <button type="button" class="case-manager-close" aria-label="关闭" @click="closeCaseManager">×</button>
        </header>
        <div class="case-manager-toolbar">
          <span>共 {{ demo.caseLibrary.length }} 份已完成记录</span>
          <button type="button" class="text-button" @click="toggleAllCases">{{ allCasesSelected ? '取消全选' : '全选' }}</button>
        </div>
        <div class="case-manager-list">
          <label v-for="task in demo.caseLibrary" :key="task.task_id" class="case-manager-item">
            <input v-model="selectedCaseIds" type="checkbox" :value="task.task_id" />
            <span><strong>{{ task.start_date || task.task_id }}</strong><small>{{ basinLabel(task.basin_id) }} · {{ task.task_id }}</small></span>
          </label>
        </div>
        <footer class="case-manager-footer">
          <span>已选 {{ selectedCaseIds.length }} 份</span>
          <button type="button" class="case-delete" data-test="delete-selected-cases" :disabled="!selectedCaseIds.length || busy" @click="deleteSelectedCases">删除选中</button>
        </footer>
      </section>
    </div>

    <main class="observatory-grid">
      <section ref="mainStage" class="main-stage glass-pane" :class="{ 'main-stage--focus': focusStage, 'main-stage--results': showResultsStage }">
        <LiveWorkflow v-if="showWorkflow" :action="action" :status="demo.run?.paused ? 'paused' : demo.run?.status" :completed-actions="completedActions" :gate-status="gateStatus" :expanded="focusStage" :workflow-version="demo.taskMeta?.workflow_version" />
        <ModelPreparation v-else-if="modelingAvailable && !demo.taskId" :basin-id="demo.draft.basin_id" :selected-id="demo.draft.model_plan_id" :locked="busy" @selected="selectPlan" />
        <div v-else-if="showResultsStage" ref="forecastSurface" class="forecast-surface" data-test="forecast-surface">
          <div class="chart-title">
            <h2>最终方案对比</h2>
            <span v-if="finalComparison?.kind === 'independent_test'">独立检验 · {{ finalComparison.evaluated_days }} 天 · 观测 / 基准 / 最终方案</span>
            <span v-else-if="finalComparison">率定窗口 · 观测 / 基准 / 候选方案</span>
            <span v-else>方案指标已就绪 · 过程线继续整理</span>
          </div>
          <template v-if="finalComparison">
            <HydrographComparisonChart :comparison="finalComparison" />
            <p class="chart-note">{{ finalComparison.kind === 'independent_test' ? '主图保留最终判断所需的过程线：观测、原始基准和最终冻结方案。' : '独立检验过程线尚未就绪，当前显示率定窗口对比。' }}</p>
          </template>
          <SchemeComparisonMetricsChart :comparison="finalComparison" :gate="demo.results?.gate" />
          <div v-if="!finalComparison" class="results-pending"><span class="overline">过程线整理中</span><h2>指标图先保留最终对比</h2><p>运行已结束。若独立检验过程线稍后写入，这里会自动补上观测、基准与最终方案的时序曲线。</p></div>
          <ResearchEvidencePanel v-if="demo.taskId" :task-id="demo.taskId" />
        </div>
        <div v-else class="prep-placeholder"><span class="overline">数据准备</span><h2>等待建模服务</h2><p>建模服务就绪后，将在此完成资料检查、单元划分与边界复核。</p></div>
        <div v-if="showHydrologist" class="hydrologist-mount"><HydrologistTune :plan-id="demo.draft.model_plan_id" :task-id="demo.taskId" :locked="busy || demo.isRunning" /></div>
        <div v-if="showTuning" ref="tuningMount" class="tuning-mount"><ParamTuningPanel :diagnosis="demo.results?.diagnosis" :optimize="demo.results?.optimize" :scheme="demo.results?.scheme" /></div>
      </section>

      <aside ref="taskPane" class="task-pane glass-pane">
        <div class="pane-head">
          <div class="section-heading"><span class="overline">流域与任务</span></div>
          <h2>研究流域</h2>
          <p class="muted">选择本地资料完整的流域，再建立并复核计算方案。</p>
        </div>
        <form class="pane-form" @submit.prevent="begin">
          <div class="pane-body">
            <fieldset :disabled="locked">
              <label>研究流域
                <select v-model="demo.draft.basin_id" data-test="basin-selector" aria-label="研究流域">
                  <option v-for="basin in basinOptions" :key="basin.basin_id" :value="basin.basin_id" :disabled="basin.ready_for_build === false">{{ basin.label }} · {{ basin.basin_id }}{{ basin.ready_for_build === false ? '（资料不完整）' : '' }}</option>
                </select>
              </label>
              <p v-if="demo.draft.model_plan_id" class="basin-caption">已绑定方案：{{ demo.draft.model_plan_id }}</p>
              <p v-else-if="serviceMode === 'real'" class="basin-caption">请先在左侧完成数据准备</p>
              <div class="section-heading subsection"><span class="overline">预报任务</span></div>
              <div :class="{ 'is-locked': serviceMode === 'real' && !planReady }">
                <fieldset :disabled="locked || (serviceMode === 'real' && !planReady)">
                  <div class="date-fields"><label>开始日期<input v-model="demo.draft.start_date" type="date" required /></label><label>结束日期<input v-model="demo.draft.end_date" type="date" :min="demo.draft.start_date" required /></label></div>
                  <label>计算模型<select v-model="demo.draft.model_id"><option value="xaj">新安江 · XAJ</option><option value="openhydronet" disabled>OpenHydroNet · 尚未启用</option></select></label>
                  <label>气象资料<select v-model="demo.draft.forcing_mode"><option value="R">实测日资料 · 历史率定</option><option value="F" disabled>预报资料 · 当前未开放</option></select></label>
                  <label class="toggle-row"><span>允许尝试改进方案</span><input v-model="demo.draft.allow_optimization" type="checkbox" role="switch" /></label>
                  <button class="text-button" type="button" :aria-expanded="advanced" @click="advanced = !advanced">{{ advanced ? '收起运行设置 −' : '运行设置 +' }}</button>
                  <div v-if="advanced" class="advanced-fields">
                    <label>基础方案<input v-model="demo.draft.base_scheme_id" required /></label>
                    <label>开发验证窗（天）<input v-model.number="demo.draft.validation_days" data-test="development-days" type="number" min="3" max="90" required /><small>候选方案在此做 Gate；最终测试不会参与选择。</small></label>
                    <label>最终测试窗（天）<input v-model.number="demo.draft.final_test_days" data-test="final-test-days" type="number" min="3" max="90" required /><small>方案冻结后只读、单次消费。</small></label>
                    <label>最多决策轮次<input v-model.number="demo.draft.max_agent_decision_rounds" type="number" min="1" max="20" required /></label>
                    <label>最多改进次数<input v-model.number="demo.draft.max_optimization_cycles" type="number" min="0" max="4" required /></label>
                  </div>
                </fieldset>
              </div>
            </fieldset>
          </div>
          <div class="pane-actions">
            <button v-if="!demo.run || demo.run.status === 'created'" class="start-button" :disabled="busy || !connected || (serviceMode === 'real' && !demo.draft.model_plan_id)" type="submit">{{ busy ? '正在启动…' : planReady ? '开始运行' : '请先完成建模' }}</button>
            <button v-else-if="demo.run.paused && demo.mode !== 'replay'" type="button" class="start-button" :disabled="busy" @click="resume">继续计算</button>
            <button v-else-if="demo.isRunning" type="button" class="start-button" disabled>正在计算<span class="activity-dot" /></button>
            <button v-else type="button" class="start-button" @click="newTask">新建任务</button>
            <p class="source-note">{{ demo.draft.forcing_mode === 'R' ? `使用 ${selectedBasin?.label || demo.draft.basin_id} 本地日资料做历史率定与检验，不代表业务预报。` : '预报资料可用性将在运行时检查。' }}</p>
            <div class="case-picker-row"><label class="case-picker">已有案例<select aria-label="已有案例" :disabled="demo.isRunning || busy" :value="demo.mode === 'replay' ? demo.taskId : ''" @change="openCase"><option value="">{{ demo.caseLibrary.length ? '选择一份已完成记录' : '暂无已完成记录' }}</option><option v-for="task in demo.caseLibrary" :key="task.task_id" :value="task.task_id">{{ task.start_date || task.task_id }} · {{ basinLabel(task.basin_id) }}</option></select></label><button data-test="delete-case" type="button" class="case-delete" :disabled="demo.isRunning || busy || !demo.caseLibrary.length" @click="openCaseManager">管理</button></div>
          </div>
        </form>
      </aside>

      <aside ref="journalPane" class="journal-pane glass-pane">
        <ExecutionJournal
          :task-id="demo.taskId"
          :events="demo.timeline"
          :running="demo.isRunning"
          :completed="demo.isCompleted"
          :failed="demo.isFailed"
          :elapsed="elapsed"
          :current-action="action"
          :error="error"
          @refresh="demo.refresh()"
        />
      </aside>
    </main>
    <footer class="observatory-footer"><span>HYDRO-AGENT <span class="footer-divider">/</span> 课题工作台</span><span>新安江模型 · 可追溯执行</span></footer>
  </div>
</template>

<style src="../observatory.css"></style>
<style scoped>
.case-manager-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(26, 28, 34, 0.2);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
.case-manager-panel {
  width: min(520px, 100%);
  max-height: min(680px, 78vh);
  padding: 20px;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
}
.case-manager-head,
.case-manager-toolbar,
.case-manager-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.case-manager-head h2 { margin: 4px 0 0; }
.case-manager-close {
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 50%;
  background: var(--neutral-soft);
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
}
.case-manager-toolbar {
  padding: 12px 0 10px;
  border-bottom: 1px solid var(--separator);
  color: var(--text-secondary);
  font-size: 12px;
}
.case-manager-list {
  min-height: 0;
  display: grid;
  gap: 7px;
  padding: 10px 0;
  overflow: auto;
  scrollbar-gutter: stable;
}
.case-manager-item {
  display: grid !important;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 10px !important;
  padding: 10px 11px;
  border: 1px solid var(--separator);
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.case-manager-item input { width: 15px; height: 15px; margin: 0; }
.case-manager-item span { display: grid; min-width: 0; gap: 2px; }
.case-manager-item strong { font-size: 13px; }
.case-manager-item small { overflow: hidden; color: var(--text-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.case-manager-footer {
  padding-top: 12px;
  border-top: 1px solid var(--separator);
  color: var(--text-secondary);
  font-size: 12px;
}
.advanced-fields small {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
}
@media (prefers-reduced-transparency: reduce) {
  .case-manager-backdrop {
    background: rgba(26, 28, 34, 0.32);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>