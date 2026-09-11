import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import type { ResultSummary, RunSummary, TaskCreateRequest, TaskSummary, TimelineItem } from '../types/api'

export type RunMode = 'live' | 'replay' | 'simulated'

export type DraftConfig = {
  model_plan_id?: string | null
  basin_id: string
  model_id: 'xaj' | 'openhydronet'
  start_date: string
  end_date: string
  forcing_mode: 'R' | 'F'
  base_scheme_id: string
  allow_optimization: boolean
  max_agent_decision_rounds: number
  max_optimization_cycles: number
}

export type ConditionState = 'unchecked' | 'ok' | 'warn' | 'fail'

const SESSION_KEY = 'hydro-demo-session'

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
    basin_id: 'yaogu',
    model_id: 'xaj',
    start_date: '1991-01-01',
    end_date: '1991-01-31',
    forcing_mode: 'R',
    base_scheme_id: 'scheme-base',
    allow_optimization: true,
    max_agent_decision_rounds: 20,
    max_optimization_cycles: 4,
    model_plan_id: null,
  }
}

export const useDemoStore = defineStore('demo', () => {
  const saved = loadSession()
  const draft = ref<DraftConfig>(saved?.draft || defaultDraft())

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
          health.mode === 'real' || draft.value.model_id === 'xaj' ? 'ok' : 'warn'
        conditions.value.modelDetail =
          draft.value.model_id === 'xaj' ? '新安江模型可用' : '所选模型尚未启用'
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

    // No dedicated source-readiness endpoint yet — stay honest.
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
      // Service may still be starting after compose recreate.
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
    draft.value.model_id = task.model_id === 'openhydronet' ? 'openhydronet' : 'xaj'
    draft.value.model_plan_id = task.model_plan_id ?? null
    if (task.start_date) draft.value.start_date = task.start_date
    if (task.end_date) draft.value.end_date = task.end_date
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

  async function startRun() {
    if (!taskId.value) throw new Error('尚未创建任务')
    if (mode.value === 'replay') {
      // Replay only follows recorded state; never restart compute.
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
      const settled =
        isCompleted.value || isFailed.value || mode.value === 'replay'
      if (settled) {
        try {
          results.value = await api.getResults(taskId.value)
        } catch {
          // Keep run/timeline if results are not ready yet.
        }
        const visuals =
          Boolean(results.value?.forecasts?.length) ||
          Boolean(results.value?.test_hydrograph?.series?.length) ||
          Boolean(results.value?.calibration_hydrograph?.series?.length)
        if (visuals || isFailed.value || ++completeSettleTicks >= 8) stopPolling()
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
    void api.getTask(id).then((task) => {
      taskMeta.value = task
      applyTaskMeta(task)
    }).catch(() => {
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
    isCompleted,
    isFailed,
    checkConditions,
    loadCaseLibrary,
    createTaskFromDraft,
    openCaseReplay,
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
  }
})
