import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { DEMO_PRESET } from '../demo/preset'
import type { ResultSummary, RunSummary, TaskCreateRequest, TaskSummary, TimelineItem } from '../types/api'

export type RunMode = 'live' | 'replay' | 'simulated'

export type DraftConfig = {
  model_plan_id?: string | null
  basin_id: string
  model_id: 'xaj' | 'gr4j' | 'openhydronet'
  start_date: string
  end_date: string
  forcing_mode: 'R' | 'F'
  base_scheme_id: string
  allow_optimization: boolean
  validation_days: number
  final_test_days: number
  max_agent_decision_rounds: number
  max_optimization_cycles: number
  campaign_mode: 'smoke' | 'target_quality' | 'convergence'
  campaign_max_model_evaluations: number
  name?: string | null
}

export type ConditionState = 'unchecked' | 'ok' | 'warn' | 'fail'

const SESSION_KEY = 'hydro-demo-session'
const RESULT_VISUAL_SETTLE_TICKS = 75

type SessionSnapshot = {
  taskId: string
  mode: RunMode
  draft: DraftConfig
  startedAt: number | null
}

function loadSession(): SessionSnapshot | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    return JSON.parse(raw) as SessionSnapshot
  } catch {
    return null
  }
}

function defaultDraft(): DraftConfig {
  return {
    ...DEMO_PRESET,
    model_plan_id: null,
    name: '',
  }
}

function hydrateDraft(saved?: Partial<DraftConfig> | null): DraftConfig {
  const merged = { ...defaultDraft(), ...(saved || {}) }
  if (
    merged.campaign_mode !== 'smoke'
    && merged.campaign_mode !== 'target_quality'
    && merged.campaign_mode !== 'convergence'
  ) {
    merged.campaign_mode = DEMO_PRESET.campaign_mode
  }
  if (!Number.isFinite(merged.campaign_max_model_evaluations) || merged.campaign_max_model_evaluations < 1) {
    merged.campaign_max_model_evaluations = DEMO_PRESET.campaign_max_model_evaluations
  }
  return merged
}

export const useDemoStore = defineStore('demo', () => {
  const saved = loadSession()
  const draft = ref<DraftConfig>(hydrateDraft(saved?.draft))

  const taskId = ref<string | null>(saved?.taskId || null)
  const mode = ref<RunMode>(saved?.mode || 'live')
  const followScreen = ref(true)
  const run = ref<RunSummary | null>(null)
  const timeline = ref<TimelineItem[]>([])
  const results = ref<ResultSummary | null>(null)
  const error = ref<string | null>(null)
  const startedAt = ref<number | null>(saved?.startedAt ?? null)
  const polling = ref<number | null>(null)
  const caseLibrary = ref<TaskSummary[]>([])
  const settingsOpen = ref(false)
  const taskMeta = ref<TaskSummary | null>(null)

  const conditions = ref({
    service: 'unchecked' as ConditionState,
    serviceDetail: '尚未检查',
    source: 'unchecked' as ConditionState,
    sourceDetail: '尚未检查',
    model: 'unchecked' as ConditionState,
    modelDetail: '尚未检查',
  })

  const isRunning = computed(
    () => Boolean(run.value?.worker_active) || run.value?.status === 'running',
  )
  const isQueued = computed(() => run.value?.status === 'queued')
  const isCompleted = computed(
    () =>
      run.value?.status === 'completed' ||
      (run.value?.phase === 'E' && run.value?.needs_follow_up === false),
  )
  const isFailed = computed(
    () => run.value?.status === 'failed' || run.value?.status === 'error',
  )
  let completeSettleTicks = 0

  function persistSession() {
    if (!taskId.value) {
      sessionStorage.removeItem(SESSION_KEY)
      return
    }
    const snap: SessionSnapshot = {
      taskId: taskId.value,
      mode: mode.value,
      draft: { ...draft.value },
      startedAt: startedAt.value,
    }
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(snap))
  }

  watch([taskId, mode, draft, startedAt], persistSession, { deep: true })

  async function checkConditions() {
    conditions.value.service = 'unchecked'
    conditions.value.serviceDetail = '检查中…'
    conditions.value.source = 'unchecked'
    conditions.value.sourceDetail = '检查中…'
    conditions.value.model = 'unchecked'
    conditions.value.modelDetail = '检查中…'
    try {
      const health = await api.health()
      if (health.status === 'ok') {
        conditions.value.service = 'ok'
        conditions.value.serviceDetail =
          health.mode === 'real'
            ? `已连接 · ${health.provider_model || '真实模式'}`
            : `已连接 · ${health.mode || '演示'}模式`
        conditions.value.model =
          health.mode === 'real' || draft.value.model_id === 'xaj' || draft.value.model_id === 'gr4j'
            ? 'ok'
            : 'warn'
        conditions.value.modelDetail =
          draft.value.model_id === 'xaj'
            ? '新安江模型可用'
            : draft.value.model_id === 'gr4j'
              ? 'GR4J 模型可用'
              : '所选模型尚未启用'
      } else {
        conditions.value.service = 'fail'
        conditions.value.serviceDetail = '服务响应异常'
        conditions.value.model = 'unchecked'
        conditions.value.modelDetail = '尚未检查'
      }
    } catch (err) {
      conditions.value.service = 'fail'
      conditions.value.serviceDetail = String((err as Error).message || err)
      conditions.value.model = 'fail'
      conditions.value.modelDetail = '无法确认模型状态'
    }

    conditions.value.source = 'unchecked'
    conditions.value.sourceDetail =
      '资料是否齐全将在任务启动后由服务端检查；此处尚未检查'
  }

  async function loadCaseLibrary() {
    try {
      const tasks = await api.listTasks()
      caseLibrary.value = tasks
        .filter((t) => t.status === 'completed')
        .slice(0, 12)
    } catch {
      try {
        await new Promise((r) => setTimeout(r, 1200))
        const tasks = await api.listTasks()
        caseLibrary.value = tasks
          .filter((t) => t.status === 'completed')
          .slice(0, 12)
      } catch {
        caseLibrary.value = []
      }
    }
  }

  function applyTaskMeta(task: TaskSummary) {
    draft.value.basin_id = task.basin_id
    draft.value.model_id =
      task.model_id === 'openhydronet'
        ? 'openhydronet'
        : task.model_id === 'gr4j'
          ? 'gr4j'
          : 'xaj'
    draft.value.model_plan_id = task.model_plan_id ?? null
    if (task.start_date) draft.value.start_date = task.start_date
    if (task.end_date) draft.value.end_date = task.end_date
    if (task.validation_days != null) draft.value.validation_days = task.validation_days
    if (task.final_test_days != null) draft.value.final_test_days = task.final_test_days
    if (task.forcing_mode === 'R' || task.forcing_mode === 'F') {
      draft.value.forcing_mode = task.forcing_mode
    }
  }

  async function createTaskFromDraft() {
    error.value = null
    const body: TaskCreateRequest = { ...draft.value }
    if (!body.model_plan_id) {
      delete body.model_plan_id
    }
    const trimmed = body.name?.trim()
    if (trimmed) body.name = trimmed
    else delete body.name
    const task = await api.createTask(body)
    taskId.value = task.task_id
    taskMeta.value = task
    mode.value = 'live'
    run.value = null
    timeline.value = []
    results.value = null
    startedAt.value = null
    persistSession()
    return task
  }

  async function openCaseReplay(task: TaskSummary) {
    error.value = null
    stopPolling()
    applyTaskMeta(task)
    taskId.value = task.task_id
    taskMeta.value = task
    mode.value = 'replay'
    run.value = null
    timeline.value = []
    results.value = null
    startedAt.value = null
    followScreen.value = true
    completeSettleTicks = 0
    startPolling()
    persistSession()
  }

  async function deleteCases(tasks: TaskSummary[]) {
    error.value = null
    const unique = [...new Map(tasks.map((task) => [task.task_id, task])).values()]
    if (!unique.length) return
    if ((isRunning.value || isQueued.value) && unique.some((task) => task.task_id === taskId.value)) {
      throw new Error('任务正在运行，无法删除')
    }

    // Delete sequentially: SQLite immutability triggers are process-wide and
    // concurrent deletes used to race so only one case was removed.
    const deletedIds = new Set<string>()
    const failedIds: string[] = []
    for (const task of unique) {
      try {
        await api.deleteTask(task.task_id)
        deletedIds.add(task.task_id)
      } catch {
        failedIds.push(task.task_id)
      }
    }

    if (taskId.value && deletedIds.has(taskId.value)) resetSession()
    await loadCaseLibrary()
    if (failedIds.length) throw new Error(`有 ${failedIds.length} 个历史案例删除失败`)
  }

  async function deleteCase(task: TaskSummary) {
    await deleteCases([task])
  }

  async function renameCase(task: TaskSummary, name: string | null) {
    error.value = null
    const updated = await api.renameTask(task.task_id, name)
    caseLibrary.value = caseLibrary.value.map((row) => (row.task_id === updated.task_id ? updated : row))
    if (taskMeta.value?.task_id === updated.task_id) taskMeta.value = updated
    return updated
  }

  async function startRun() {
    if (!taskId.value) throw new Error('尚未创建任务')
    if (mode.value === 'replay') {
      await refresh()
      return
    }
    error.value = null
    startedAt.value = Date.now()
    completeSettleTicks = 0
    run.value = await api.startRun(taskId.value)
    startPolling()
    persistSession()
  }

  async function refresh() {
    if (!taskId.value) return
    try {
      const [nextRun, nextTimeline] = await Promise.all([
        api.getRun(taskId.value),
        api.getTimeline(taskId.value),
      ])
      run.value = nextRun
      timeline.value = nextTimeline
      const settled = isCompleted.value || isFailed.value || mode.value === 'replay'
      if (settled) {
        try {
          results.value = await api.getResults(taskId.value)
        } catch {
          // Keep run/timeline if results are not ready yet.
        }
        const visuals =
          Boolean(results.value?.test_hydrograph?.series?.length) ||
          Boolean(results.value?.calibration_hydrograph?.series?.length)
        // Report/hydrograph files are finalized after the run state can already read completed.
        // Keep checking long enough for the final comparison to upgrade from metric bars to process lines.
        if (visuals || isFailed.value || ++completeSettleTicks >= RESULT_VISUAL_SETTLE_TICKS) stopPolling()
      } else {
        completeSettleTicks = 0
      }
      error.value = null
    } catch (err) {
      error.value = String((err as Error).message || err)
    }
  }

  function startPolling() {
    stopPolling()
    void refresh()
    polling.value = window.setInterval(() => {
      void refresh()
    }, 800)
  }

  function stopPolling() {
    if (polling.value != null) {
      clearInterval(polling.value)
      polling.value = null
    }
  }

  async function pauseFollow() {
    followScreen.value = false
  }

  async function resumeFollow() {
    followScreen.value = true
  }

  async function pauseCompute() {
    if (!taskId.value || mode.value !== 'live') return
    run.value = await api.pauseRun(taskId.value)
  }

  async function resumeCompute() {
    if (!taskId.value || mode.value !== 'live') return
    run.value = await api.resumeRun(taskId.value)
    startPolling()
  }

  function restoreTask(id: string, nextMode?: RunMode) {
    taskId.value = id
    if (nextMode) mode.value = nextMode
    void api
      .getTask(id)
      .then((task) => {
        taskMeta.value = task
        applyTaskMeta(task)
      })
      .catch(() => {
        taskMeta.value = null
      })
    completeSettleTicks = 0
    startPolling()
    persistSession()
  }

  function openSettings() {
    settingsOpen.value = true
  }

  function closeSettings() {
    settingsOpen.value = false
  }

  function resetSession() {
    stopPolling()
    taskId.value = null
    taskMeta.value = null
    run.value = null
    timeline.value = []
    results.value = null
    error.value = null
    startedAt.value = null
    completeSettleTicks = 0
    followScreen.value = true
    settingsOpen.value = false
    mode.value = 'live'
    draft.value = defaultDraft()
    sessionStorage.removeItem(SESSION_KEY)
  }

  function applyDemoPreset() {
    if (taskId.value || isRunning.value) return
    const plan = draft.value.basin_id === DEMO_PRESET.basin_id ? draft.value.model_plan_id : null
    draft.value = { ...defaultDraft(), model_plan_id: plan }
    persistSession()
  }

  return {
    draft,
    taskId,
    taskMeta,
    mode,
    followScreen,
    run,
    timeline,
    results,
    error,
    startedAt,
    conditions,
    caseLibrary,
    settingsOpen,
    isRunning,
    isQueued,
    isCompleted,
    isFailed,
    checkConditions,
    loadCaseLibrary,
    createTaskFromDraft,
    openCaseReplay,
    deleteCase,
    deleteCases,
    renameCase,
    startRun,
    refresh,
    startPolling,
    stopPolling,
    pauseFollow,
    resumeFollow,
    pauseCompute,
    resumeCompute,
    restoreTask,
    openSettings,
    closeSettings,
    resetSession,
    applyDemoPreset,
  }
})
