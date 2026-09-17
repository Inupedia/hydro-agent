<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ExecutionJournal from '../components/ExecutionJournal.vue'
import LiveWorkflow from '../components/LiveWorkflow.vue'
import ModelPreparation from '../components/ModelPreparation.vue'
import type { ModelPlan } from '../types/api'
import GlassSelect from '../components/GlassSelect.vue'
import ObservatoryResultsStack from '../components/ObservatoryResultsStack.vue'
import GlassDialog from '../components/GlassDialog.vue'
import RenameDialog from '../components/RenameDialog.vue'
import SkillsLibrarySheet from '../components/SkillsLibrarySheet.vue'
import { RippleButton } from '../components/ui'
import { useDemoStore } from '../stores/demo'
import { DEMO_PRESET } from '../demo/preset'
import { api } from '../api/client'
import { gsap, motionDuration, prefersReducedMotion } from '../motion/gsap'
import { basinLabel, providerErrorZh, workbenchErrorZh } from '../demo/stages'
import { asWorkbenchModelId, modelShortLabel } from '../modelLabels'
import { useMediaQuery } from '../composables/useMediaQuery'

type MobileStep = 'prepare' | 'task' | 'journal' | 'results'
const MOBILE_STEPS: MobileStep[] = ['prepare', 'task', 'journal', 'results']
const MOBILE_STEP_LABEL: Record<MobileStep, string> = {
  prepare: '数据准备',
  task: '流域与任务',
  journal: '执行记录',
  results: '运行结果',
}

const demo = useDemoStore()
const route = useRoute()
const busy = ref(false)
const serviceMode = ref<string | null>(null)
const connected = ref(false)
const modelingAvailable = ref(false)
const basins = ref<import('../types/api').BasinInfo[]>([])
const basinOptions = computed(() =>
  basins.value.length
    ? basins.value
    : [{ basin_id: demo.draft.basin_id, label: basinLabel(demo.draft.basin_id), ready_for_build: true }],
)
const selectedBasin = computed(() =>
  basinOptions.value.find((basin) => basin.basin_id === demo.draft.basin_id),
)
const basinSelectOptions = computed(() =>
  basinOptions.value.map((basin) => ({
    value: basin.basin_id,
    label: `${basin.label} · ${basin.basin_id}${basin.ready_for_build === false ? '（资料不完整）' : ''}`,
    disabled: basin.ready_for_build === false,
  })),
)
const modelSelectOptions = [
  { value: 'xaj', label: '新安江' },
  { value: 'gr4j', label: 'GR4J' },
  { value: 'hbv', label: 'HBV-light' },
  { value: 'tank', label: '水箱模型' },
  { value: 'sac-sma', label: 'SAC-SMA' },
  { value: 'openhydronet', label: 'OpenHydroNet · 尚未启用', disabled: true },
]
const footerModelLabel = computed(() =>
  modelShortLabel(demo.results?.scheme?.model_id || demo.draft.model_id),
)
const forcingSelectOptions = [
  { value: 'R', label: '实测日资料 · 历史率定' },
  { value: 'F', label: '预报资料 · 当前未开放', disabled: true },
]
const campaignSelectOptions = [
  { value: 'smoke', label: '连通验证' },
  { value: 'target_quality', label: '目标质量' },
]
const campaignMode = computed({
  get: () => demo.draft.campaign_mode,
  set: (value: string) => {
    if (value === 'smoke' || value === 'target_quality' || value === 'convergence') {
      demo.draft.campaign_mode = value
    }
  },
})
const caseSelectOptions = computed(() => [
  { value: '', label: demo.caseLibrary.length ? '选择一份已完成记录' : '暂无已完成记录' },
  ...demo.caseLibrary.map((task) => ({
    value: task.task_id,
    label: caseLabel(task),
  })),
])
function caseLabel(task: { task_id: string; name?: string | null; start_date?: string | null; basin_id: string }) {
  const title = task.name?.trim()
  if (title) return `${title} · ${basinLabel(task.basin_id)}`
  return `${task.start_date || task.task_id} · ${basinLabel(task.basin_id)}`
}
function planCaption(plan: ModelPlan | null, planId: string | null | undefined) {
  if (plan?.name?.trim()) return `${plan.name.trim()}（${plan.plan_id}）`
  return planId || ''
}
function openRenameCase(task: { task_id: string; name?: string | null; start_date?: string | null; basin_id: string }) {
  renameCaseTarget.value = task
}

function closeRenameCase() {
  if (renameCaseBusy.value) return
  renameCaseTarget.value = null
}

async function saveRenameCase(name: string | null) {
  const task = renameCaseTarget.value
  if (!task) return
  renameCaseBusy.value = true
  try {
    await demo.renameCase(task as never, name)
    renameCaseTarget.value = null
  } catch (err) {
    demo.error = String((err as Error).message || err)
  } finally {
    renameCaseBusy.value = false
  }
}
const selectedCaseId = computed({
  get: () => (demo.mode === 'replay' ? demo.taskId || '' : ''),
  set: (id: string) => {
    void openCase(id)
  },
})
const comparisonOverline = computed(() => {
  if (!finalComparison.value) return '过程线整理中'
  return finalComparison.value.kind === 'independent_test' ? '独立检验' : '率定窗口'
})
const comparisonTitle = computed(() => {
  if (finalComparison.value?.kind === 'independent_test') {
    return '最终方案是否贴住观测过程线'
  }
  if (finalComparison.value) return '率定窗里，观测与方案差在哪里'
  return '最终方案对比'
})
const comparisonSubtitle = computed(() => {
  if (finalComparison.value?.kind === 'independent_test') {
    return '观测 · 基准方案 · 最终冻结方案 · 单位 m³/s'
  }
  if (finalComparison.value) return '独立检验尚未就绪 · 当前先看率定窗对比'
  return '指标先对照；过程线写入后会自动补上观测、基准与最终方案。'
})
const comparisonMeta = computed(() => {
  if (finalComparison.value?.kind === 'independent_test') {
    return `${finalComparison.value.evaluated_days} 天 · 观测 / 基准 / 最终方案`
  }
  if (finalComparison.value) return '观测 / 基准 / 候选方案'
  return '方案指标已就绪 · 过程线继续整理'
})
const planReady = computed(() => !!demo.draft.model_plan_id)
const boundPlan = ref<ModelPlan | null>(null)
const planDateMin = computed(() => boundPlan.value?.data_start || boundPlan.value?.suggested_start || undefined)
const planDateMax = computed(() => boundPlan.value?.data_end || undefined)
const demoPresetLoaded = computed(
  () =>
    demo.draft.basin_id === DEMO_PRESET.basin_id &&
    demo.draft.start_date === DEMO_PRESET.start_date &&
    demo.draft.end_date === DEMO_PRESET.end_date &&
    demo.draft.validation_days === DEMO_PRESET.validation_days &&
    demo.draft.final_test_days === DEMO_PRESET.final_test_days &&
    demo.draft.max_agent_decision_rounds === DEMO_PRESET.max_agent_decision_rounds &&
    demo.draft.max_optimization_cycles === DEMO_PRESET.max_optimization_cycles &&
    demo.draft.campaign_mode === DEMO_PRESET.campaign_mode &&
    demo.draft.campaign_max_model_evaluations === DEMO_PRESET.campaign_max_model_evaluations,
)
let syncingPlanBasin = false
function selectPlan(plan: ModelPlan | null) {
  if (demo.taskId) return
  if (!plan) {
    demo.draft.model_plan_id = null
    boundPlan.value = null
    return
  }
  const basinChanged = demo.draft.basin_id !== plan.basin_id
  syncingPlanBasin = true
  if (demo.draft.basin_id !== plan.basin_id) {
    demo.draft.basin_id = plan.basin_id
  }
  demo.draft.model_plan_id = plan.plan_id
  boundPlan.value = plan
  const datesNeedRepair = (!!plan.suggested_start && demo.draft.start_date < plan.suggested_start)
    || (!!plan.data_end && (demo.draft.end_date > plan.data_end || demo.draft.start_date > plan.data_end))
  if (basinChanged || datesNeedRepair) {
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
const desktopResultsStack = ref<{ forecastSurface: HTMLElement | null; tuningMount: HTMLElement | null } | null>(null)
const caseManagerOpen = ref(false)
const skillsLibraryOpen = ref(false)
const selectedCaseIds = ref<string[]>([])
const renameCaseTarget = ref<{ task_id: string; name?: string | null; start_date?: string | null; basin_id: string } | null>(null)
const renameCaseBusy = ref(false)
const runNotice = ref<{ overline: string; title: string; body: string } | null>(null)
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
const isMobile = useMediaQuery('(max-width: 900px)')
const showRunActivity = computed(
  () =>
    busy.value ||
    demo.isRunning ||
    demo.isQueued ||
    !!demo.run?.paused ||
    demo.isFailed ||
    (!!demo.taskId && !!demo.run && demo.run.status !== 'created' && !demo.isCompleted),
)
const showWorkflow = computed(() => !isMobile.value && !showResultsStage.value && showRunActivity.value)
const focusStage = computed(() => showWorkflow.value && !demo.isCompleted)
const mobilePreferredStep = computed<MobileStep>(() => {
  if (showResultsStage.value) return 'results'
  if (showRunActivity.value || (demo.isCompleted && demo.isFailed)) return 'journal'
  if (demo.draft.model_plan_id || !modelingAvailable.value || !!demo.taskId) return 'task'
  return 'prepare'
})
const mobileStep = ref<MobileStep>('prepare')
const mobileStepIndex = computed(() => MOBILE_STEPS.indexOf(mobileStep.value))
const mobileLocked = computed(
  () => mobilePreferredStep.value === 'journal' || mobilePreferredStep.value === 'results',
)
const canMobileBack = computed(
  () => !mobileLocked.value && mobileStepIndex.value > 0,
)
const canMobileForward = computed(
  () =>
    !mobileLocked.value &&
    mobileStepIndex.value < MOBILE_STEPS.indexOf(mobilePreferredStep.value),
)
const headerCaption = computed(() => {
  if (isMobile.value) return MOBILE_STEP_LABEL[mobileStep.value]
  if (focusStage.value) return '执行中'
  if (demo.mode === 'replay') return '案例回放'
  if (showResultsStage.value) return '运行结果'
  return '工作台'
})

let deckTouchX = 0
let deckTouchY = 0
let deckTouchActive = false

function goMobileStep(step: MobileStep) {
  if (mobileLocked.value) return
  const target = MOBILE_STEPS.indexOf(step)
  const ceiling = MOBILE_STEPS.indexOf(mobilePreferredStep.value)
  if (target < 0 || target > ceiling) return
  mobileStep.value = step
}

function mobileBack() {
  if (!canMobileBack.value) return
  goMobileStep(MOBILE_STEPS[mobileStepIndex.value - 1])
}

function mobileForward() {
  if (!canMobileForward.value) return
  goMobileStep(MOBILE_STEPS[mobileStepIndex.value + 1])
}

function onDeckTouchStart(event: TouchEvent) {
  if (!isMobile.value || mobileLocked.value || event.touches.length !== 1) return
  const target = event.target as HTMLElement | null
  if (target?.closest('input, textarea, select, [data-no-swipe]')) return
  deckTouchActive = true
  deckTouchX = event.touches[0].clientX
  deckTouchY = event.touches[0].clientY
}

function onDeckTouchEnd(event: TouchEvent) {
  if (!deckTouchActive || !isMobile.value || mobileLocked.value) return
  deckTouchActive = false
  const touch = event.changedTouches[0]
  if (!touch) return
  const dx = touch.clientX - deckTouchX
  const dy = touch.clientY - deckTouchY
  if (Math.abs(dx) < 64 || Math.abs(dx) < Math.abs(dy) * 1.35) return
  if (dx > 0) mobileBack()
  else mobileForward()
}

watch(
  mobilePreferredStep,
  (preferred, previous) => {
    if (!isMobile.value) return
    if (preferred === 'journal' || preferred === 'results') {
      mobileStep.value = preferred
      return
    }
    const nextIdx = MOBILE_STEPS.indexOf(preferred)
    const prevIdx = previous == null ? -1 : MOBILE_STEPS.indexOf(previous)
    if (nextIdx > prevIdx) mobileStep.value = preferred
  },
  { immediate: true },
)

watch(isMobile, (mobile) => {
  if (mobile) mobileStep.value = mobilePreferredStep.value
})

const completedActions = computed(() =>
  demo.timeline
    .filter((t) => t.action && !['failed', 'error', 'skipped', 'running'].includes(t.status))
    .map((t) => t.action as string),
)
const gateStatus = computed(() => {
  const fromResults = demo.results?.gate?.status
  if (typeof fromResults === 'string') return fromResults
  const gate = [...demo.timeline].reverse().find((t) => t.action === 'A06_GATE' || t.action === 'A07_RESOLVE')
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
const mode = computed(() =>
  demo.mode === 'replay' ? '历史记录' : serviceMode.value === 'real' ? '真实计算' : serviceMode.value ? '模拟演示' : '连接待确认',
)
const allCasesSelected = computed(
  () => demo.caseLibrary.length > 0 && demo.caseLibrary.every((task) => selectedCaseIds.value.includes(task.task_id)),
)
const elapsed = computed(() => {
  if (demo.isQueued) {
    const place = demo.run?.queue_position
    return place ? `排队等待第 ${place} 位` : '排队等待计算席位'
  }
  if (!demo.startedAt || demo.isCompleted || demo.isFailed) return demo.isCompleted ? '已结束' : '等待开始'
  const seconds = Math.max(0, Math.floor((now.value - demo.startedAt) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
})
const error = computed(
  () => workbenchErrorZh(demo.error) || providerErrorZh(demo.run?.llm_error) || demo.error || demo.run?.llm_error,
)

function showQueuedNotice() {
  const place = demo.run?.queue_position
  const used = demo.run?.worker_slots_used ?? 0
  const max = demo.run?.worker_slots_max ?? 5
  runNotice.value = {
    overline: '计算席位',
    title: '已加入排队',
    body: place
      ? `当前最多同时运行 ${max} 个任务，已有 ${used} 个正在计算。你排在第 ${place} 位，席位空出后会自动开始，无需重复提交。`
      : `当前最多同时运行 ${max} 个任务。席位空出后会自动开始，无需重复提交。`,
  }
}

function showSeatFullNotice(raw: string) {
  runNotice.value = {
    overline: '计算席位',
    title: '暂时无法开始',
    body: workbenchErrorZh(raw) || '计算席位已满（最多同时运行 5 个任务）。任务已保存，请稍后再点开始运行。',
  }
}

function closeRunNotice() {
  runNotice.value = null
}

async function begin() {
  busy.value = true
  try {
    if (!demo.taskId) await demo.createTaskFromDraft()
    await demo.startRun()
    if (demo.isQueued) showQueuedNotice()
  } catch (err) {
    const raw = String((err as Error).message || err)
    demo.error = raw
    if (workbenchErrorZh(raw)) showSeatFullNotice(raw)
  } finally {
    busy.value = false
  }
}
async function resume() {
  busy.value = true
  try {
    await demo.resumeCompute()
    if (demo.isQueued) showQueuedNotice()
  } catch (err) {
    const raw = String((err as Error).message || err)
    demo.error = raw
    if (workbenchErrorZh(raw)) showSeatFullNotice(raw)
  } finally {
    busy.value = false
  }
}
async function openCase(id: string) {
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
function openSkillsLibrary() {
  skillsLibraryOpen.value = true
}
function closeSkillsLibrary() {
  skillsLibraryOpen.value = false
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
  mobileStep.value = modelingAvailable.value ? 'prepare' : 'task'
  void nextTick(() => {
    if (isMobile.value) return
    const task = taskPane.value
    if (task) gsap.set(task, { autoAlpha: 1, pointerEvents: 'auto', clearProps: 'transform,opacity,visibility' })
  })
}

function animateFocus(enter: boolean) {
  if (isMobile.value) return
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
  const chart = desktopResultsStack.value?.forecastSurface || forecastSurface.value
  const tuning = desktopResultsStack.value?.tuningMount || tuningMount.value
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
  if (isMobile.value) return
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
      boundPlan.value = null
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
      demo.draft.model_id = asWorkbenchModelId(task.model_id)
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
  <div
    class="observatory"
    :class="{ 'is-focus': focusStage, 'is-results': showResultsStage, 'is-mobile': isMobile }"
    :data-mobile-step="isMobile ? mobileStep : undefined"
  >
    <header class="observatory-header">
      <a href="/" class="observatory-brand"><span class="brand-symbol" aria-hidden="true">≈</span><span>Hydro<span class="brand-light">Agent</span><small>水文智能体 · 观测台</small></span></a>
      <div class="header-caption">{{ headerCaption }}</div>
      <div class="header-end">
        <button
          type="button"
          class="manage-button"
          data-test="header-skills-library"
          @click="openSkillsLibrary"
        >
          专业技能
        </button>
        <div v-if="showResultsStage" class="header-actions">
          <label class="header-case-picker">已有案例
            <GlassSelect
              v-model="selectedCaseId"
              data-test="header-case-picker"
              aria-label="已有案例"
              compact
              :disabled="demo.isRunning || demo.isQueued || busy"
              :options="caseSelectOptions"
            />
          </label>
          <button data-test="header-delete-case" type="button" class="manage-button" :disabled="demo.isRunning || demo.isQueued || busy || !demo.caseLibrary.length" @click="openCaseManager">管理</button>
          <button data-test="header-new-task" type="button" class="header-new-task" @click="newTask">新建任务</button>
        </div>
        <div class="connection"><i :class="{ online: connected }" />{{ mode }}</div>
      </div>
    </header>

    <SkillsLibrarySheet :open="skillsLibraryOpen" :task-id="demo.taskId" @close="closeSkillsLibrary" />

    <GlassDialog
      :open="!!runNotice"
      test-id="run-notice"
      :overline="runNotice?.overline || '计算席位'"
      :title="runNotice?.title || ''"
      labelled-by="run-notice-title"
      @close="closeRunNotice"
    >
      <p>{{ runNotice?.body }}</p>
      <template #footer>
        <button class="start-button" data-test="run-notice-ack" type="button" @click="closeRunNotice">知道了</button>
      </template>
    </GlassDialog>

    <GlassDialog
      :open="caseManagerOpen"
      test-id="case-manager"
      overline="历史案例"
      title="批量管理"
      labelled-by="case-manager-title"
      @close="closeCaseManager"
    >
      <template #toolbar>
        <span>共 {{ demo.caseLibrary.length }} 份已完成记录</span>
        <button type="button" class="text-button" @click="toggleAllCases">{{ allCasesSelected ? '取消全选' : '全选' }}</button>
      </template>
      <label v-for="task in demo.caseLibrary" :key="task.task_id" class="glass-dialog-item case-manager-item">
        <input v-model="selectedCaseIds" type="checkbox" :value="task.task_id" />
        <span>
          <strong>{{ task.name?.trim() || task.start_date || task.task_id }}</strong>
          <small>{{ basinLabel(task.basin_id) }} · {{ task.task_id }}</small>
        </span>
        <button type="button" class="text-button" :disabled="busy" @click.prevent="openRenameCase(task)">重命名</button>
      </label>
      <template #footer>
        <span>已选 {{ selectedCaseIds.length }} 份</span>
        <button type="button" class="danger-button" data-test="delete-selected-cases" :disabled="!selectedCaseIds.length || busy" @click="deleteSelectedCases">删除选中</button>
      </template>
    </GlassDialog>

    <RenameDialog
      :open="!!renameCaseTarget"
      overline="历史案例"
      title="重命名案例"
      hint="留空则恢复为日期编号。"
      placeholder="例如：腰古 2000 汛期率定"
      :initial-name="renameCaseTarget?.name"
      :busy="renameCaseBusy"
      test-id="rename-case-dialog"
      @close="closeRenameCase"
      @save="saveRenameCase"
    />

    <main class="observatory-grid">
      <div
        class="mobile-deck"
        data-test="mobile-deck"
        @touchstart.passive="onDeckTouchStart"
        @touchend="onDeckTouchEnd"
      >
      <section ref="mainStage" class="main-stage glass-pane" :class="{ 'main-stage--focus': focusStage, 'main-stage--results': showResultsStage && !isMobile }">
        <LiveWorkflow v-if="showWorkflow" :action="action" :status="demo.run?.paused ? 'paused' : demo.run?.status" :completed-actions="completedActions" :gate-status="gateStatus" :expanded="focusStage" :workflow-version="demo.taskMeta?.workflow_version" />
        <ModelPreparation v-else-if="modelingAvailable && !demo.taskId" :basin-id="demo.draft.basin_id" :selected-id="demo.draft.model_plan_id" :locked="busy" @selected="selectPlan" />
        <ObservatoryResultsStack
          v-else-if="showResultsStage && !isMobile"
          ref="desktopResultsStack"
          :task-id="demo.taskId"
          :comparison="finalComparison"
          :results="demo.results"
          :show-tuning="showTuning"
          :overline="comparisonOverline"
          :title="comparisonTitle"
          :subtitle="comparisonSubtitle"
          :meta="comparisonMeta"
        />
        <div v-else class="prep-placeholder"><span class="overline">数据准备</span><h2>等待建模服务</h2><p>建模服务就绪后，将在此完成资料检查、单元划分与边界复核。</p></div>
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
                <GlassSelect
                  v-model="demo.draft.basin_id"
                  data-test="basin-selector"
                  aria-label="研究流域"
                  :disabled="locked"
                  :options="basinSelectOptions"
                />
              </label>
              <p v-if="demo.draft.model_plan_id" class="basin-caption">已绑定方案：{{ planCaption(boundPlan, demo.draft.model_plan_id) }}</p>
              <p v-else-if="serviceMode === 'real'" class="basin-caption">请先在左侧完成数据准备</p>
              <div class="section-heading subsection">
                <span class="overline">预报任务</span>
                <button
                  v-if="demo.draft.basin_id === 'yaogu'"
                  class="text-button"
                  data-test="demo-preset"
                  type="button"
                  @click="demo.applyDemoPreset()"
                >{{ demoPresetLoaded ? '重新载入演示默认值' : '载入演示默认值' }}</button>
              </div>
              <p v-if="demo.draft.basin_id === 'yaogu'" class="basin-caption">演示窗口 {{ DEMO_PRESET.start_date }} 至 {{ DEMO_PRESET.end_date }}，按开发期筛选，不代表正式研究结论。复现请使用 365 天预热、单元集总方案。</p>
              <div :class="{ 'is-locked': serviceMode === 'real' && !planReady }">
                <fieldset :disabled="locked || (serviceMode === 'real' && !planReady)">
                  <label>运行名称（可选）
                    <input
                      v-model="demo.draft.name"
                      type="text"
                      maxlength="80"
                      data-test="task-name"
                      placeholder="例如：腰古 2000 汛期率定"
                    />
                  </label>
                  <div class="date-fields">
                    <label>开始日期<input v-model="demo.draft.start_date" data-test="start-date" type="date" :min="planDateMin" :max="planDateMax" required /></label>
                    <label>结束日期<input v-model="demo.draft.end_date" data-test="end-date" type="date" :min="demo.draft.start_date" :max="planDateMax" required /></label>
                  </div>
                  <label>计算模型
                    <GlassSelect v-model="demo.draft.model_id" aria-label="计算模型" :options="modelSelectOptions" />
                  </label>
                  <label>气象资料
                    <GlassSelect v-model="demo.draft.forcing_mode" aria-label="气象资料" :options="forcingSelectOptions" />
                  </label>
                  <label class="toggle-row"><span>允许尝试改进方案</span><input v-model="demo.draft.allow_optimization" type="checkbox" role="switch" /></label>
                  <label>模型评估预算<input v-model.number="demo.draft.campaign_max_model_evaluations" data-test="campaign-budget" type="number" min="1" required /><small>本次率定最多运行多少次模型；预算越大，搜索可能更充分，也更耗时。</small></label>
                  <button class="text-button" data-test="runtime-settings" type="button" :aria-expanded="advanced" @click="advanced = !advanced">{{ advanced ? '收起运行设置 −' : '运行设置 +' }}</button>
                  <div v-if="advanced" class="advanced-fields">
                    <label>基础方案<input v-model="demo.draft.base_scheme_id" required /></label>
                    <label>开发验证窗（天）<input v-model.number="demo.draft.validation_days" data-test="development-days" type="number" min="3" max="90" required /><small>候选方案在此做 Gate；最终测试不会参与选择。</small></label>
                    <label>最终测试窗（天）<input v-model.number="demo.draft.final_test_days" data-test="final-test-days" type="number" min="3" max="90" required /><small>方案冻结后只读、单次消费。</small></label>
                    <label>最多决策轮次<input v-model.number="demo.draft.max_agent_decision_rounds" type="number" min="1" max="100" required /></label>
                    <label>最多改进次数<input v-model.number="demo.draft.max_optimization_cycles" type="number" min="0" max="4" required /></label>
                    <label>停止策略
                      <GlassSelect v-model="campaignMode" data-test="campaign-mode" aria-label="停止策略" :options="campaignSelectOptions" />
                      <small>连通验证只按模型评估预算停止，不宣称收敛或发布合格。</small>
                    </label>
                  </div>
                </fieldset>
              </div>
            </fieldset>
          </div>
          <div class="pane-actions">
            <RippleButton
              v-if="!demo.run || demo.run.status === 'created'"
              class="start-button"
              :disabled="busy || !connected || (serviceMode === 'real' && !demo.draft.model_plan_id)"
              type="submit"
            >
              {{ busy ? '正在启动…' : planReady ? '开始运行' : '请先完成建模' }}
            </RippleButton>
            <RippleButton
              v-else-if="demo.run.paused && demo.mode !== 'replay'"
              type="button"
              class="start-button"
              :disabled="busy"
              @click="resume"
            >
              继续计算
            </RippleButton>
            <button v-else-if="demo.isQueued" type="button" class="start-button" disabled>排队等待计算席位{{ demo.run.queue_position ? `（第 ${demo.run.queue_position} 位）` : '' }}</button>
            <button v-else-if="demo.isRunning" type="button" class="start-button" disabled>正在计算<span class="activity-dot" /></button>
            <RippleButton v-else type="button" class="start-button" @click="newTask">新建任务</RippleButton>
            <p class="source-note">{{ demo.draft.forcing_mode === 'R' ? `使用 ${selectedBasin?.label || demo.draft.basin_id} 本地日资料做历史率定与检验，不代表业务预报。` : '预报资料可用性将在运行时检查。' }}</p>
            <div class="case-picker-row">
              <label class="case-picker">已有案例
                <GlassSelect
                  v-model="selectedCaseId"
                  aria-label="已有案例"
                  :disabled="demo.isRunning || demo.isQueued || busy"
                  :options="caseSelectOptions"
                />
              </label>
              <button data-test="delete-case" type="button" class="manage-button" :disabled="demo.isRunning || demo.isQueued || busy || !demo.caseLibrary.length" @click="openCaseManager">管理</button>
            </div>
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

      <aside class="results-pane glass-pane" aria-label="运行结果">
        <ObservatoryResultsStack
          v-if="showResultsStage && isMobile"
          :task-id="demo.taskId"
          :comparison="finalComparison"
          :results="demo.results"
          :show-tuning="showTuning"
          :overline="comparisonOverline"
          :title="comparisonTitle"
          :subtitle="comparisonSubtitle"
          :meta="comparisonMeta"
        />
      </aside>
      </div>

      <nav v-if="isMobile" class="mobile-step-bar" aria-label="工作台步骤" data-test="mobile-step-bar">
        <ol class="mobile-step-dots">
          <li
            v-for="step in MOBILE_STEPS"
            :key="step"
            :class="{
              'is-current': mobileStep === step,
              'is-reached': MOBILE_STEPS.indexOf(step) <= MOBILE_STEPS.indexOf(mobilePreferredStep),
              'is-locked': mobileLocked && step !== mobilePreferredStep,
            }"
          >
            <button
              type="button"
              :disabled="
                (mobileLocked && step !== mobilePreferredStep) ||
                MOBILE_STEPS.indexOf(step) > MOBILE_STEPS.indexOf(mobilePreferredStep)
              "
              :aria-current="mobileStep === step ? 'step' : undefined"
              @click="goMobileStep(step)"
            >
              {{ MOBILE_STEP_LABEL[step] }}
            </button>
          </li>
        </ol>
      </nav>
    </main>

    <footer class="observatory-footer"><span>水文智能体 <span class="footer-divider">/</span> 观测台</span><span>{{ footerModelLabel }}模型 · 可追溯执行</span></footer>
  </div>
</template>

<style src="../observatory.css"></style>
<style scoped>
.pane-form label small {
  display: block;
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
}
</style>
