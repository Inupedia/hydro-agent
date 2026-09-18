<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ExecutionJournal from '../components/ExecutionJournal.vue'
import AgentActivityPanel from '../components/AgentActivityPanel.vue'
import LiveWorkflow from '../components/LiveWorkflow.vue'
import ModelPreparation from '../components/ModelPreparation.vue'
import type { ModelPlan } from '../types/api'
import GlassSelect from '../components/GlassSelect.vue'
import ObservatoryResultsStack from '../components/ObservatoryResultsStack.vue'
import GlassDialog from '../components/GlassDialog.vue'
import RenameDialog from '../components/RenameDialog.vue'
import CaseSkillUsageDialog from '../components/CaseSkillUsageDialog.vue'
import SkillsLibrarySheet from '../components/SkillsLibrarySheet.vue'
import LLMSettingsSheet from '../components/LLMSettingsSheet.vue'
import { RippleButton } from '../components/ui'
import { PhBookOpenText, PhFolderSimple, PhPlay, PhPlus, PhSlidersHorizontal, PhStop, PhTrash } from '@phosphor-icons/vue'
import { useDemoStore } from '../stores/demo'
import { api } from '../api/client'
import { gsap, motionDuration, prefersReducedMotion } from '../motion/gsap'
import { basinLabel, providerErrorZh, workbenchErrorZh } from '../demo/stages'
import { asWorkbenchModelId, modelShortLabel } from '../modelLabels'
import { useMediaQuery } from '../composables/useMediaQuery'

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
  { value: 'tank', label: '三层 Tank + Nash' },
  { value: 'sac-sma', label: 'SAC-SMA（NOAA-OWP）' },
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
const caseLibraryOpen = ref(false)
const skillsLibraryOpen = ref(false)
const caseSkillUsageOpen = ref(false)
const llmConfigOpen = ref(false)
const newTaskConfirmOpen = ref(false)
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
// Tablet keeps the compact two-column workbench. The deck is reserved for actual
// phone widths, where a three-pane task flow can no longer remain legible.
const isMobile = useMediaQuery('(max-width: 760px)')
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
const headerCaption = computed(() => {
  if (focusStage.value) return '执行中'
  if (demo.mode === 'replay') return '案例回放'
  if (showResultsStage.value) return '运行结果'
  return ''
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
async function cancelRun() {
  if (!demo.taskId || busy.value || !confirm('终止后将结束本次任务，已产生的过程记录会保留。确定终止吗？')) return
  busy.value = true
  try {
    await demo.cancelCompute()
  } catch (err) {
    demo.error = String((err as Error).message || err)
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
function openCaseLibrary() {
  caseLibraryOpen.value = true
}
function closeCaseLibrary() {
  caseLibraryOpen.value = false
}
async function openCaseFromLibrary(id: string) {
  await openCase(id)
  closeCaseLibrary()
}
function closeCaseManager() {
  caseManagerOpen.value = false
  selectedCaseIds.value = []
}
function openSkillsLibrary() {
  skillsLibraryOpen.value = true
}
function openSkillUsage() {
  caseSkillUsageOpen.value = true
}
function closeSkillsLibrary() {
  skillsLibraryOpen.value = false
}
function openLLMConfig() {
  llmConfigOpen.value = true
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
    if (isMobile.value) return
    const task = taskPane.value
    if (task) gsap.set(task, { autoAlpha: 1, pointerEvents: 'auto', clearProps: 'transform,opacity,visibility' })
  })
}
function requestNewTask() {
  if (demo.taskId && (demo.isRunning || demo.isQueued)) {
    newTaskConfirmOpen.value = true
    return
  }
  newTask()
}
async function confirmNewTask() {
  newTaskConfirmOpen.value = false
  busy.value = true
  try {
    await demo.cancelCompute()
    newTask()
  } catch (err) {
    demo.error = String((err as Error).message || err)
  } finally {
    busy.value = false
  }
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
    :class="{
      'is-focus': focusStage,
      'is-results': showResultsStage,
      'is-mobile': isMobile,
      'is-mobile-setup': isMobile && !demo.taskId,
      'is-mobile-running': isMobile && !!demo.taskId && !showResultsStage,
      'is-mobile-results': isMobile && showResultsStage,
    }"
  >
    <header class="observatory-header">
      <a href="/" class="observatory-brand"><span class="brand-symbol" aria-hidden="true">≈</span><span>Hydro<span class="brand-light">Agent</span><small>水文智能体 · 观测台</small></span></a>
      <div v-if="headerCaption" class="header-caption">{{ headerCaption }}</div>
      <div class="header-end">
        <button
          v-if="demo.mode !== 'replay'"
          type="button"
          class="manage-button"
          data-test="header-skills-library"
          @click="openSkillsLibrary"
        >
          <PhBookOpenText :size="16" weight="duotone" aria-hidden="true" />
          Agent 能力
        </button>
        <button
          v-else
          type="button"
          class="manage-button"
          data-test="header-skill-usage"
          @click="openSkillUsage"
        >
          <PhBookOpenText :size="16" weight="duotone" aria-hidden="true" />
          查看 Skills / Tools
        </button>
        <div class="header-actions">
          <button
            v-if="demo.mode !== 'replay'"
            data-test="header-case-library"
            type="button"
            class="manage-button"
            :disabled="demo.isRunning || demo.isQueued || busy"
            @click="openCaseLibrary"
          >
            <PhFolderSimple :size="16" weight="duotone" aria-hidden="true" />
            案例库
          </button>
          <button
          v-if="demo.taskId"
            data-test="header-new-task"
            type="button"
            class="header-new-task"
            @click="requestNewTask"
          >
            <PhStop v-if="demo.isRunning || demo.isQueued" :size="16" weight="fill" aria-hidden="true" />
            <PhPlus v-else :size="16" weight="bold" aria-hidden="true" />
            {{ demo.isRunning || demo.isQueued ? '停止任务' : '新建任务' }}
          </button>
        </div>
        <div v-if="showResultsStage" class="header-actions header-actions--result">
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
          <button v-if="demo.mode !== 'replay'" data-test="header-delete-case" type="button" class="manage-button" :disabled="demo.isRunning || demo.isQueued || busy || !demo.caseLibrary.length" @click="openCaseManager">
            <PhSlidersHorizontal :size="16" weight="duotone" aria-hidden="true" />
            管理
          </button>
        </div>
        <button
          v-if="demo.mode !== 'replay'"
          type="button"
          class="header-control llm-config-button"
          data-test="llm-config"
          :aria-label="`模型服务配置，当前 ${mode}`"
          :title="mode"
          @click="openLLMConfig"
        >
          <PhSlidersHorizontal :size="16" aria-hidden="true" />
          配置
          <span class="visually-hidden">{{ mode }}</span>
        </button>
      </div>
    </header>

    <SkillsLibrarySheet :open="skillsLibraryOpen" :task-id="demo.taskId" @close="closeSkillsLibrary" />
    <CaseSkillUsageDialog :open="caseSkillUsageOpen" :task-id="demo.taskId" @close="caseSkillUsageOpen = false" />
    <LLMSettingsSheet :open="llmConfigOpen" @close="llmConfigOpen = false" />

    <GlassDialog
      :open="newTaskConfirmOpen"
      test-id="new-task-confirm"
      overline="新建任务"
      title="退出本次运行？"
      labelled-by="new-task-confirm-title"
      @close="newTaskConfirmOpen = false"
    >
      <p>当前运行记录会保留，但新建任务后将离开本次运行。确定继续吗？</p>
      <template #footer>
        <button type="button" class="start-button" :disabled="busy" @click="confirmNewTask">停止任务</button>
      </template>
    </GlassDialog>

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
      :open="caseLibraryOpen"
      test-id="case-library"
      overline="案例库"
      title="已完成任务"
      labelled-by="case-library-title"
      size="wide"
      @close="closeCaseLibrary"
    >
      <template #toolbar>
        <div class="case-library-toolbar-copy">
          <span>选择一份记录进入只读回放</span>
          <small>共 {{ demo.caseLibrary.length }} 份记录</small>
        </div>
        <button type="button" class="text-button" :disabled="!demo.caseLibrary.length" @click="openCaseManager">管理案例</button>
      </template>
      <div v-if="!demo.caseLibrary.length" class="case-library-empty">
        <strong>还没有已完成案例</strong>
        <span>完成一次运行后，记录会保存在这里。</span>
      </div>
      <button
        v-for="task in demo.caseLibrary"
        :key="task.task_id"
        type="button"
        class="glass-dialog-item case-library-item"
        :disabled="busy"
        @click="openCaseFromLibrary(task.task_id)"
      >
        <span>
          <strong>{{ task.name?.trim() || task.start_date || task.task_id }}</strong>
          <small>{{ basinLabel(task.basin_id) }} · {{ task.start_date || task.task_id }}</small>
        </span>
        <span class="case-library-item-chevron" aria-hidden="true">›</span>
      </button>
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
        <button type="button" class="danger-button" data-test="delete-selected-cases" :disabled="!selectedCaseIds.length || busy" @click="deleteSelectedCases">
          <PhTrash :size="16" weight="bold" aria-hidden="true" />
          删除选中
        </button>
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
      <div class="mobile-deck" data-test="mobile-deck">
      <section ref="mainStage" class="main-stage glass-pane" :class="{ 'main-stage--focus': focusStage, 'main-stage--results': showResultsStage && !isMobile }">
        <template v-if="showWorkflow">
          <LiveWorkflow :action="action" :status="demo.run?.paused ? 'paused' : demo.run?.status" :completed-actions="completedActions" :gate-status="gateStatus" :expanded="focusStage" :workflow-version="demo.taskMeta?.workflow_version">
          <template #inspector>
          <AgentActivityPanel
            :task-id="demo.taskId"
            :event-count="demo.timeline.length"
            :current-action="action"
            :running="demo.isRunning"
          />
          </template>
          </LiveWorkflow>
        </template>
        <template v-else-if="!demo.taskId">
          <div class="setup-route">
            <div>
              <span class="overline">新建任务</span>
              <h2>先确定研究流域，再准备计算模型</h2>
            </div>
            <ol aria-label="任务创建流程">
              <li class="is-current">选择流域</li>
              <li :class="{ 'is-current': planReady }">准备模型</li>
              <li :class="{ 'is-ready': planReady }">配置运行</li>
            </ol>
          </div>
          <div class="basin-picker">
            <div class="basin-picker-heading">
              <h3>研究流域</h3>
              <p class="basin-picker-subtitle">{{ selectedBasin?.ready_for_build === false ? '该流域资料尚未齐全，暂不能建立模型。' : '流域确定后，可复用既有方案或建立新的计算单元。' }}</p>
            </div>
            <GlassSelect
              v-model="demo.draft.basin_id"
              data-test="basin-selector"
              aria-label="研究流域"
              :disabled="locked"
              :options="basinSelectOptions"
            />
          </div>
          <ModelPreparation
            v-if="modelingAvailable"
            :basin-id="demo.draft.basin_id"
            :selected-id="demo.draft.model_plan_id"
            :locked="busy"
            embedded
            @selected="selectPlan"
          />
          <div v-else class="prep-placeholder">
            <span class="overline">模型准备</span>
            <h2>建模服务暂未连接</h2>
            <p>可以先配置任务参数；连接建模服务后，将在此建立计算单元并复核流域边界。</p>
          </div>
        </template>
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
          <div class="section-heading"><span class="overline">配置运行</span></div>
          <h2>本次运行</h2>
          <p class="muted">{{ planReady ? `已使用 ${basinLabel(demo.draft.basin_id)} 的模型方案。` : '请先在左侧完成流域选择和模型准备。' }}</p>
        </div>
        <form class="pane-form" @submit.prevent="begin">
          <div class="pane-body">
            <fieldset :disabled="locked">
              <p v-if="demo.draft.model_plan_id" class="basin-caption">已绑定方案：{{ planCaption(boundPlan, demo.draft.model_plan_id) }}</p>
              <p v-else-if="serviceMode === 'real'" class="basin-caption">请先在左侧完成数据准备</p>
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
              data-test="start-run"
              :beam="!busy && connected && (serviceMode !== 'real' || planReady)"
              :beam-radius="12"
              :beam-size="64"
              :beam-duration="6"
              :disabled="busy || !connected || (serviceMode === 'real' && !demo.draft.model_plan_id)"
              type="submit"
            >
              <PhPlay
                v-if="!busy && (serviceMode !== 'real' || planReady)"
                :size="16"
                weight="fill"
                aria-hidden="true"
              />
              {{
                busy
                  ? '正在启动…'
                  : serviceMode === 'real' && !planReady
                    ? '请先完成建模'
                    : '开始运行'
              }}
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
            <button v-if="demo.isQueued || demo.isRunning" type="button" class="start-button cancel-button" :disabled="busy" @click="cancelRun">{{ busy ? '正在终止…' : '终止任务' }}</button>
            <RippleButton v-else-if="demo.run && !demo.isQueued && !demo.isRunning" type="button" class="start-button" @click="requestNewTask">新建任务</RippleButton>
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
        <div v-if="isMobile && (demo.isRunning || demo.isQueued)" class="mobile-run-actions">
          <button type="button" class="mobile-primary-action" :disabled="busy" @click="cancelRun">
            {{ busy ? '正在终止…' : '终止任务' }}
          </button>
        </div>
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
        <div v-if="isMobile && showResultsStage" class="mobile-run-actions">
          <button type="button" class="mobile-primary-action" @click="requestNewTask">新建任务</button>
        </div>
      </aside>
      </div>
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
